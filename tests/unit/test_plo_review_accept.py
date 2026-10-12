from __future__ import annotations

from datetime import datetime

from curriculum_agent.models import (
    PLO,
    BloomLevel,
    KSECCategory,
    Need,
    ReviewToolCall,
    SMARTCheck,
)
from curriculum_agent.stages.plo_review import accept_review, code_only_review, has_agent_findings
from curriculum_agent.stages.plo_review_agent import (
    BloomVerdict,
    KsecVerdict,
    Redundancy,
    ReviewFinish,
    UnusedVerdict,
)
from curriculum_agent.stages.plo_review_facts import (
    build_dossier,
    current_ksec,
    is_stale,
    need_demands,
    plo_fingerprint,
)

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)
_NOW = datetime(2026, 10, 5, 12, 0, 0)


def _need(nid: str, ksec: KSECCategory) -> Need:
    return Need(
        need_id=nid,
        program_id="p",
        statement_th=f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        ksec_category=ksec,
        bloom_level=BloomLevel.APPLY,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=0.5,
    )


def _plo(pid: str, need_ids: list[str], *, statement: str | None = None) -> PLO:
    return PLO(
        plo_id=pid,
        program_id="p",
        statement_th=statement or f"วิเคราะห์ระบบงาน {pid} เพื่อเสนอแนวทางแก้ปัญหา",
        bloom_level=BloomLevel.APPLY,
        action_verb_th="วิเคราะห์",
        smart_check=_SMART,
        source_need_ids=need_ids,
        source_evidence_ids=["E1"],
        rationale_th="เหตุผล",
    )


NEEDS = {"n1": _need("n1", KSECCategory.S), "n2": _need("n2", KSECCategory.EC)}
DEMANDS = need_demands(NEEDS.values())
PLOS = [_plo("PLO1", ["n1"]), _plo("PLO2", ["n2"]), _plo("PLO3", ["n1", "n2"])]


UNUSED = _need("u1", KSECCategory.S)  # cited by nothing in PLOS
DOSSIER = build_dossier(
    PLOS, [*NEEDS.values(), UNUSED], program_context=None, degree_level="bachelor"
)


def _accept(answer: ReviewFinish, calls: list[ReviewToolCall] | None = None):
    return accept_review(
        answer,
        PLOS,
        NEEDS,
        DOSSIER,
        program_id="p",
        fingerprint="f",
        model="m",
        created_at=_NOW,
        tool_calls=calls or (),
    )


# ------------------------------ current_ksec ------------------------------


def test_current_ksec_expands_ec_and_follows_ksec_order() -> None:
    assert current_ksec(PLOS[1], NEEDS) == ["E", "C"]
    assert current_ksec(PLOS[2], NEEDS) == ["S", "E", "C"]


def test_current_ksec_ignores_an_unknown_need() -> None:
    assert current_ksec(_plo("PLO9", ["gone", "n1"]), NEEDS) == ["S"]


# ------------------------------ fingerprint ------------------------------


def test_fingerprint_ignores_order_and_moves_on_each_field() -> None:
    base = plo_fingerprint(PLOS, DEMANDS)
    assert plo_fingerprint(list(reversed(PLOS)), DEMANDS) == base
    changed = [PLOS[0].model_copy(update={"statement_th": "ออกแบบระบบ"}), *PLOS[1:]]
    assert plo_fingerprint(changed, DEMANDS) != base
    for field, value in [
        ("bloom_level", BloomLevel.CREATE),
        ("action_verb_th", "ออกแบบ"),
        ("is_optional", True),
        ("source_need_ids", ["n2"]),
    ]:
        assert (
            plo_fingerprint([PLOS[0].model_copy(update={field: value}), *PLOS[1:]], DEMANDS) != base
        )


def test_is_stale_compares_fingerprints() -> None:
    review, _ = accept_review(
        ReviewFinish(kind="finish", summary_th="ดี"),
        PLOS,
        NEEDS,
        DOSSIER,
        program_id="p",
        fingerprint=plo_fingerprint(PLOS, DEMANDS),
        model="m",
        created_at=_NOW,
    )
    assert not is_stale(review, PLOS, DEMANDS)
    assert is_stale(review, PLOS[:2], DEMANDS)


# ------------------------------ redundancy ------------------------------


def test_redundancy_keeps_known_ids_and_drops_short_or_oversized_groups() -> None:
    review, drops = _accept(
        ReviewFinish(
            kind="finish",
            redundancies=[
                Redundancy(plo_ids=["PLO1", "PLO2"], reason_th="ซ้ำ", suggestion_th="รวม"),
                Redundancy(plo_ids=["PLO1", "PLO99"], reason_th="ซ้ำ"),
                Redundancy(plo_ids=["PLO1", "PLO2", "PLO3", "PLO1"], reason_th="ซ้ำ"),
                Redundancy(plo_ids=["PLO2", "PLO1"], reason_th="ซ้ำอีก"),
                Redundancy(plo_ids=["PLO2", "PLO3"], reason_th="  "),
            ],
        )
    )
    assert [r.plo_ids for r in review.redundancies] == [["PLO1", "PLO2"], ["PLO1", "PLO2", "PLO3"]]
    assert drops["redundancy"] == 3


def test_a_group_naming_more_than_three_distinct_plos_is_dropped() -> None:
    plos = [*PLOS, _plo("PLO4", ["n1"])]
    review, _ = accept_review(
        ReviewFinish(
            kind="finish",
            redundancies=[Redundancy(plo_ids=["PLO1", "PLO2", "PLO3", "PLO4"], reason_th="ซ้ำ")],
        ),
        plos,
        NEEDS,
        DOSSIER,
        program_id="p",
        fingerprint="f",
        model="m",
        created_at=_NOW,
    )
    assert review.redundancies == []


# ------------------------------ KSEC ------------------------------


def test_ksec_current_and_agrees_are_computed_in_code() -> None:
    review, drops = _accept(
        ReviewFinish(
            kind="finish",
            ksec=[
                KsecVerdict(plo_id="PLO1", suggested=["s", "E"], reason_th="มีจริยธรรมด้วย"),
                KsecVerdict(plo_id="PLO2", suggested=["EC"], reason_th="ตรง"),
                KsecVerdict(plo_id="PLO2", suggested=["K"], reason_th="ซ้ำ plo_id"),
                KsecVerdict(plo_id="PLO99", suggested=["K"], reason_th="ไม่มีจริง"),
                KsecVerdict(plo_id="PLO3", suggested=["X", "Y"], reason_th="ไม่มีหมวดจริง"),
            ],
        )
    )
    by_id = {k.plo_id: k for k in review.ksec}
    assert set(by_id) == {"PLO1", "PLO2"}
    assert by_id["PLO1"].current == ["S"] and by_id["PLO1"].suggested == ["S", "E"]
    assert by_id["PLO1"].agrees is False
    assert by_id["PLO2"].suggested == ["E", "C"] and by_id["PLO2"].agrees is True
    assert drops["ksec"] == 3


def test_ksec_accepts_the_e_bar_c_spelling() -> None:
    review, _ = _accept(
        ReviewFinish(
            kind="finish", ksec=[KsecVerdict(plo_id="PLO2", suggested=["E|C"], reason_th="ตรง")]
        )
    )
    assert review.ksec[0].suggested == ["E", "C"]


# ------------------------------ Bloom ------------------------------


def test_bloom_declared_is_filled_in_code_and_a_bad_level_becomes_none() -> None:
    review, drops = _accept(
        ReviewFinish(
            kind="finish",
            bloom=[
                BloomVerdict(
                    plo_id="PLO1", suggested_level="Analyze", reason_th="กรรมคือการวิเคราะห์"
                ),
                BloomVerdict(plo_id="PLO2", suggested_level="psychic", reason_th="ระดับสูงเกิน"),
                BloomVerdict(plo_id="PLO3", suggested_level="apply", reason_th=""),
                BloomVerdict(plo_id="PLO99", suggested_level="apply", reason_th="ไม่มีจริง"),
            ],
        )
    )
    by_id = {b.plo_id: b for b in review.bloom}
    assert set(by_id) == {"PLO1", "PLO2"}
    assert by_id["PLO1"].declared is BloomLevel.APPLY
    assert by_id["PLO1"].suggested_level is BloomLevel.ANALYZE
    assert by_id["PLO2"].suggested_level is None
    assert drops["bloom"] == 2


# ------------------------------ texts, facts, findings ------------------------------


def test_texts_are_stripped_and_a_blank_answer_has_no_findings() -> None:
    review, _ = _accept(
        ReviewFinish(kind="finish", summary_th="  ดีแล้ว  ", bloom_distribution_th=" apply เป็นหลัก ")
    )
    assert review.summary_th == "ดีแล้ว"
    assert review.bloom_distribution_th == "apply เป็นหลัก"
    assert has_agent_findings(review)
    blank, _ = _accept(ReviewFinish(kind="finish", summary_th="   "))
    assert not has_agent_findings(blank)


def test_code_facts_come_from_the_dossier_not_the_answer() -> None:
    review, _ = _accept(ReviewFinish(kind="finish", summary_th="ok", coverage_th=" ขาด K "))
    assert review.ksec_coverage == DOSSIER.ksec_coverage
    assert review.bloom_histogram == DOSSIER.bloom_histogram
    assert review.coverage_th == "ขาด K"
    assert review.reviewed_by == "agent" and review.code_only_reason is None


def test_unused_verdicts_merge_onto_the_selected_needs_only() -> None:
    answer = ReviewFinish(
        kind="finish",
        summary_th="ok",
        unused_needs=[
            UnusedVerdict(need_id="u1", verdict="Consider", reason_th="นายจ้างขอ"),
            UnusedVerdict(need_id="u1", verdict="ok_to_leave", reason_th="ซ้ำ"),
            UnusedVerdict(need_id="n1", verdict="consider", reason_th="ไม่อยู่ในรายการ"),
        ],
    )
    review, drops = _accept(answer)
    [u] = review.unused_needs
    assert (u.need_id, u.verdict, u.reason_th) == ("u1", "consider", "นายจ้างขอ")
    assert u.demand_score == UNUSED.demand_score and u.exclusion == "lost_on_demand"
    assert drops["unused"] == 2


def test_an_unknown_verdict_word_keeps_the_entry_without_a_verdict() -> None:
    answer = ReviewFinish(
        kind="finish",
        summary_th="ok",
        unused_needs=[UnusedVerdict(need_id="u1", verdict="maybe", reason_th="ไม่แน่ใจ")],
    )
    [u] = _accept(answer)[0].unused_needs
    assert u.verdict is None and u.reason_th == "ไม่แน่ใจ"


def test_the_tool_calls_are_recorded() -> None:
    calls = [ReviewToolCall(tool="check_verbs", arg="PLO1")]
    review, _ = _accept(ReviewFinish(kind="finish", summary_th="ok"), calls)
    assert review.tool_calls == calls


def test_a_code_only_review_has_facts_and_no_findings() -> None:
    review = code_only_review(
        DOSSIER, program_id="p", fingerprint="f", created_at=_NOW, reason="timeout"
    )
    assert review.reviewed_by == "code_only" and review.code_only_reason == "timeout"
    assert review.model == "" and review.summary_th == ""
    assert review.ksec_coverage == DOSSIER.ksec_coverage
    assert [u.need_id for u in review.unused_needs] == ["u1"]
    assert all(u.verdict is None for u in review.unused_needs)
    assert not has_agent_findings(review)


def test_an_answer_with_nothing_has_no_agent_findings() -> None:
    review, _ = _accept(ReviewFinish(kind="finish"))
    assert not has_agent_findings(review)
