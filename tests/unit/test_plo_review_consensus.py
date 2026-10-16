from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pytest

from curriculum_agent.models import (
    BloomFinding,
    BloomLevel,
    KsecFinding,
    PLOSetReview,
    RedundancyFinding,
    ReviewToolCall,
    UnusedNeedFinding,
)
from curriculum_agent.stages.plo_review_consensus import agreement_threshold, consensus_review

_WHEN = datetime(2026, 10, 17, 9, 0)


def _unused(verdict: str | None = None, reason: str = "") -> UnusedNeedFinding:
    return UnusedNeedFinding(
        need_id="n9",
        statement_th="ต้องการบัณฑิตที่ออกแบบโปรแกรมท่องเที่ยวได้",
        demand_score=0.4,
        ksec_category="S",
        exclusion="lost_on_demand",
        verdict=verdict,
        reason_th=reason,
    )


def _run(
    *,
    groups: Sequence[list[str]] = (),
    ksec: dict[str, list[str]] | None = None,
    bloom: dict[str, BloomLevel | None] | None = None,
    verdict: str | None = None,
    summary: str = "สรุป",
    tool: str = "check_verbs",
) -> PLOSetReview:
    ksec = ksec if ksec is not None else {"PLO1": ["S"], "PLO2": ["S"]}
    return PLOSetReview(
        program_id="p",
        plo_fingerprint="fp",
        model="m",
        created_at=_WHEN,
        redundancies=[
            RedundancyFinding(plo_ids=g, reason_th=f"ซ้ำ {'-'.join(g)}", suggestion_th="รวม")
            for g in groups
        ],
        ksec=[
            KsecFinding(
                plo_id=pid, current=["S"], suggested=s, agrees=set(s) == {"S"}, reason_th=pid
            )
            for pid, s in ksec.items()
        ],
        bloom=[
            BloomFinding(
                plo_id=pid, declared=BloomLevel.APPLY, suggested_level=lv, reason_th=f"{pid} {lv}"
            )
            for pid, lv in (bloom or {}).items()
        ],
        unused_needs=[_unused(verdict, f"เหตุผล {verdict}" if verdict else "")],
        summary_th=summary,
        tool_calls=[ReviewToolCall(tool=tool, arg="PLO1")],
    )


def _consensus(*runs: PLOSetReview) -> PLOSetReview:
    return consensus_review(list(runs), runs_requested=3, max_group=3)


def test_threshold_is_more_than_half() -> None:
    assert [agreement_threshold(n) for n in (1, 2, 3, 4, 5)] == [1, 2, 2, 3, 3]


def test_fewer_than_two_runs_is_refused() -> None:
    with pytest.raises(ValueError):
        consensus_review([_run()], runs_requested=3, max_group=3)


def test_identical_runs_give_the_answer_back_with_full_agreement() -> None:
    a = _run(groups=[["PLO1", "PLO2"]], bloom={"PLO1": BloomLevel.ANALYZE}, verdict="consider")
    review = _consensus(a, a.model_copy(), a.model_copy())
    assert [(r.plo_ids, r.agreed_runs) for r in review.redundancies] == [(["PLO1", "PLO2"], 3)]
    assert [k.agreed_runs for k in review.ksec] == [3, 3]
    assert (
        review.bloom[0].suggested_level == BloomLevel.ANALYZE and review.bloom[0].agreed_runs == 3
    )
    assert review.unused_needs[0].verdict == "consider" and review.unused_needs[0].agreed_runs == 3
    assert (review.runs_requested, review.runs_succeeded, review.agreement_threshold) == (3, 3, 2)


def test_a_pair_two_runs_name_passes_and_a_pair_one_names_is_kept_below() -> None:
    review = _consensus(
        _run(groups=[["PLO4", "PLO9"]]),
        _run(groups=[["PLO4", "PLO9"], ["PLO6", "PLO8"]]),
        _run(groups=[["PLO1", "PLO4"]]),
    )
    found = {tuple(r.plo_ids): r.agreed_runs for r in review.redundancies}
    assert found == {("PLO4", "PLO9"): 2, ("PLO6", "PLO8"): 1, ("PLO1", "PLO4"): 1}


def test_a_pair_counts_once_per_run_even_in_overlapping_groups() -> None:
    review = _consensus(
        _run(groups=[["PLO1", "PLO2"], ["PLO1", "PLO2", "PLO3"]]),
        _run(),
        _run(),
    )
    assert {tuple(r.plo_ids): r.agreed_runs for r in review.redundancies}[("PLO1", "PLO2")] == 1


def test_a_three_plo_group_needs_every_pair_to_pass() -> None:
    full = _consensus(
        _run(groups=[["PLO4", "PLO6", "PLO9"]]),
        _run(groups=[["PLO4", "PLO6", "PLO9"]]),
        _run(),
    )
    assert [(r.plo_ids, r.agreed_runs) for r in full.redundancies] == [
        (["PLO4", "PLO6", "PLO9"], 2)
    ]

    chain = _consensus(
        _run(groups=[["PLO4", "PLO9"], ["PLO6", "PLO9"]]),
        _run(groups=[["PLO4", "PLO9"], ["PLO6", "PLO9"]]),
        _run(),
    )
    main = sorted(tuple(r.plo_ids) for r in chain.redundancies if r.agreed_runs >= 2)
    assert main == [("PLO4", "PLO9"), ("PLO6", "PLO9")]


def test_a_component_larger_than_the_cap_is_split_into_its_passing_pairs() -> None:
    groups = [["PLO1", "PLO2"], ["PLO2", "PLO3"], ["PLO3", "PLO4"]]
    review = _consensus(_run(groups=groups), _run(groups=groups), _run())
    assert all(len(r.plo_ids) == 2 for r in review.redundancies)
    assert len(review.redundancies) == 3


def test_redundancy_text_comes_from_the_run_overlapping_most() -> None:
    review = _consensus(
        _run(groups=[["PLO1", "PLO2", "PLO3"]]),
        _run(groups=[["PLO1", "PLO2"]]),
        _run(),
    )
    pair = next(r for r in review.redundancies if r.plo_ids == ["PLO1", "PLO2"])
    assert pair.reason_th == "ซ้ำ PLO1-PLO2"


def test_ksec_takes_the_most_given_set_and_a_tie_prefers_current() -> None:
    review = _consensus(
        _run(ksec={"PLO1": ["K", "S"]}),
        _run(ksec={"PLO1": ["S"]}),
    )
    assert review.ksec[0].suggested == ["S"] and review.ksec[0].agreed_runs == 1
    assert review.agreement_threshold == 2


def test_ksec_votes_only_over_the_runs_that_have_the_plo() -> None:
    review = _consensus(
        _run(ksec={"PLO1": ["S"], "PLO2": ["K"]}),
        _run(ksec={"PLO1": ["S"]}),
        _run(ksec={"PLO1": ["S"], "PLO2": ["K"]}),
    )
    plo2 = next(k for k in review.ksec if k.plo_id == "PLO2")
    assert plo2.suggested == ["K"] and plo2.agreed_runs == 2


def test_bloom_counts_runs_proposing_a_change_and_a_tie_takes_the_nearer_level() -> None:
    review = _consensus(
        _run(bloom={"PLO1": BloomLevel.CREATE}),
        _run(bloom={"PLO1": BloomLevel.ANALYZE}),
        _run(),
    )
    assert review.bloom[0].suggested_level == BloomLevel.ANALYZE
    assert review.bloom[0].agreed_runs == 2


def test_a_bloom_comment_without_a_change_is_not_carried() -> None:
    review = _consensus(_run(bloom={"PLO1": None}), _run(bloom={"PLO1": BloomLevel.APPLY}), _run())
    assert review.bloom == []


def test_unused_without_a_majority_has_no_verdict() -> None:
    review = _consensus(_run(verdict="consider"), _run(verdict="ok_to_leave"), _run())
    assert review.unused_needs[0].verdict is None and review.unused_needs[0].agreed_runs == 1
    assert review.unused_needs[0].demand_score == 0.4  # code facts kept


def test_text_and_per_run_fields_come_from_the_most_representative_run() -> None:
    review = _consensus(
        _run(groups=[["PLO6", "PLO8"]], summary="หนึ่ง", tool="bloom_lookup"),
        _run(groups=[["PLO4", "PLO9"]], summary="สอง", tool="need_detail"),
        _run(groups=[["PLO4", "PLO9"]], summary="สาม", tool="check_verbs"),
    )
    assert review.summary_th == "สอง" and review.tool_calls[0].tool == "need_detail"


def test_a_stored_review_without_the_new_fields_reads_as_one_run() -> None:
    raw = _run(groups=[["PLO1", "PLO2"]]).model_dump(mode="json")
    for key in ("runs_requested", "runs_succeeded", "agreement_threshold"):
        raw.pop(key)
    for r in raw["redundancies"]:
        r.pop("agreed_runs")
    review = PLOSetReview.model_validate(raw)
    assert (review.runs_requested, review.runs_succeeded, review.agreement_threshold) == (1, 1, 1)
    assert review.redundancies[0].agreed_runs == 1


def test_pair_findings_are_ordered_by_plo_number_not_by_string() -> None:
    review = _consensus(_run(groups=[["PLO10", "PLO11"], ["PLO2", "PLO3"]]), _run(), _run())
    assert [r.plo_ids for r in review.redundancies] == [["PLO2", "PLO3"], ["PLO10", "PLO11"]]
