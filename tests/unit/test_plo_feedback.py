from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, call

import pytest

from curriculum_agent.config import settings
from curriculum_agent.models import (
    PLO,
    AlignmentFinding,
    BloomFinding,
    BloomLevel,
    FeedbackAction,
    KsecCoverage,
    KsecFinding,
    Need,
    PLOSetReview,
    RedundancyFinding,
    UnusedNeedFinding,
)
from curriculum_agent.prompts.plo_feedback import (
    build_bloom_redraft_note_th,
    build_ksec_gap_note_th,
)
from curriculum_agent.smart_vocabulary import forbidden_words_in
from curriculum_agent.stages import plo_feedback as pf
from curriculum_agent.stages import plo_review as pr
from curriculum_agent.stages.need_dedup import MAX_GROUP_SIZE
from curriculum_agent.stages.plo_redraft import RedraftFailed, RedraftRefused
from curriculum_agent.stages.plo_review_facts import need_demands, plo_fingerprint
from tests.unit.test_api_plos import _need, _plo, _program
from tests.unit.test_plo_redraft import _install


def _unused(nid: str, *, verdict: str | None = "consider", **kw: object) -> UnusedNeedFinding:
    return UnusedNeedFinding(
        need_id=nid,
        statement_th="ความต้องการ",
        demand_score=0.5,
        exclusion=str(kw.pop("exclusion", "lost_on_demand")),
        verdict=verdict,
        reason_th=f"เหตุผล {nid}",
        **kw,  # type: ignore[arg-type]
    )


def _review(**kw: object) -> PLOSetReview:
    base: dict[str, object] = {
        "program_id": "cs-test",
        "plo_fingerprint": "f",
        "model": "m",
        "created_at": datetime(2026, 11, 3, 1, 2, 3),
        "reviewed_by": "agent",
        "agreement_threshold": 2,
    }
    base.update(kw)
    return PLOSetReview(**base)  # type: ignore[arg-type]


def _bloom(plo_id: str, reason: str = "ต่ำไป") -> BloomFinding:
    return BloomFinding(
        plo_id=plo_id,
        declared=BloomLevel.CREATE,
        suggested_level=BloomLevel.APPLY,
        reason_th=reason,
        agreed_runs=2,
    )


def _red(*ids: str) -> RedundancyFinding:
    return RedundancyFinding(plo_ids=list(ids), reason_th="ซ้ำ", agreed_runs=2)


_LAST: list[_Env] = []


async def _sb(review: PLOSetReview, reviewed: list[PLO] | None = None) -> list[FeedbackAction]:
    """send_back over the set the review judged (the env's starting set by default)."""
    env = _LAST[-1]
    return await pf.send_back("cs-test", review, env.initial if reviewed is None else reviewed)


class _Env:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, plos: list[PLO]) -> None:
        self.plos = plos
        self.initial = list(plos)
        self.draft_update: dict[str, object] = {}
        _LAST.append(self)
        monkeypatch.setattr(settings, "plo_review_send_back", True)
        self.program = AsyncMock(get=AsyncMock(return_value=_program()))
        monkeypatch.setattr(pf, "ProgramRepository", lambda: self.program)
        self.plo_repo = AsyncMock(list_by_program=AsyncMock(side_effect=self._list))
        monkeypatch.setattr(pf, "PLORepository", lambda: self.plo_repo)
        self.trail = AsyncMock()
        monkeypatch.setattr(pf, "PLOFeedbackRepository", lambda: self.trail)
        self.redraft = AsyncMock(side_effect=self._redraft)
        monkeypatch.setattr(pf, "redraft_from_needs", self.redraft)
        # Every Need the tests name; a dry run checks a planned draft against them
        # (final review I3). `_needs` replaces the list for a test that cares.
        self.needs = [_need(f"N{i}") for i in range(1, 13)]
        self.need_repo = AsyncMock(
            list_by_program=AsyncMock(side_effect=lambda _pid: list(self.needs)),
            list_active_by_program=AsyncMock(side_effect=lambda _pid: list(self.needs)),
        )
        monkeypatch.setattr(pf, "NeedRepository", lambda: self.need_repo)

    async def _list(self, _pid: str) -> list[PLO]:
        return list(self.plos)

    async def _redraft(
        self,
        _program: object,
        _pid: str,
        need_ids: list[str],
        *,
        note_th: str | None,
        cause: str,
        accept: object = None,
    ) -> tuple[PLO, list[str]]:
        """Apply the swap the real function would: drop PLOs citing, add one."""
        gone = [p.plo_id for p in self.plos if set(p.source_need_ids) & set(need_ids)]
        new_id = gone[0] if gone else "PLO9"
        new = _plo(new_id, need_ids).model_copy(
            update={
                "statement_th": f"ใหม่ {new_id}",
                "bloom_level": BloomLevel.APPLY,
                **self.draft_update,
            }
        )
        if callable(accept) and (reason := accept(new)) is not None:
            raise RedraftRefused(422, reason)
        self.plos = [p for p in self.plos if p.plo_id not in gone] + [new]
        return new, gone


@pytest.fixture
def plos() -> list[PLO]:
    return [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, 5)]


async def test_order_is_redundancy_then_bloom_then_unused(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    review = _review(
        unused_needs=[_unused("N7", agreed_runs=2)],
        bloom=[_bloom("PLO3")],
        redundancies=[_red("PLO1", "PLO2")],
    )
    actions = await _sb(review)
    assert [a.kind for a in actions] == ["redundancy", "bloom", "unused_need"]
    assert all(a.outcome == "applied" for a in actions)
    assert [c.args[2] for c in env.redraft.await_args_list] == [["N1", "N2"], ["N3"], ["N7"]]
    assert all(c.kwargs["cause"] == "review" for c in env.redraft.await_args_list)
    # one write per action, right after it
    assert env.trail.add.await_args_list == [call([a]) for a in actions]
    assert actions[0].result_plo_id == "PLO1" and actions[0].result_statement_th == "ใหม่ PLO1"
    assert actions[0].review_created_at == datetime(2026, 11, 3, 1, 2, 3)


async def test_below_threshold_findings_are_ignored(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    review = _review(
        redundancies=[RedundancyFinding(plo_ids=["PLO1", "PLO2"], reason_th="ซ้ำ", agreed_runs=1)],
        unused_needs=[_unused("N7", agreed_runs=1)],
    )
    assert await _sb(review) == []
    env.redraft.assert_not_awaited()


async def test_ok_to_leave_and_unsuggested_bloom_do_not_act(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    review = _review(
        unused_needs=[_unused("N7", verdict="ok_to_leave", agreed_runs=2)],
        bloom=[
            BloomFinding(plo_id="PLO1", declared=BloomLevel.APPLY, suggested_level=None),
            BloomFinding(
                plo_id="PLO2",
                declared=BloomLevel.APPLY,
                suggested_level=BloomLevel.APPLY,
                agreed_runs=3,
            ),
        ],
    )
    assert await _sb(review) == []
    env.redraft.assert_not_awaited()


@pytest.mark.parametrize("which", ["off", "code_only"])
async def test_switch_off_or_code_only_sends_nothing_and_reads_nothing(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO], which: str
) -> None:
    env = _Env(monkeypatch, plos)
    red = [RedundancyFinding(plo_ids=["PLO1", "PLO2"], reason_th="ซ้ำ", agreed_runs=5)]
    if which == "off":
        monkeypatch.setattr(settings, "plo_review_send_back", False)
        review = _review(redundancies=red)
    else:
        review = _review(redundancies=red, reviewed_by="code_only")
    assert await _sb(review) == []
    env.program.get.assert_not_awaited()
    env.plo_repo.list_by_program.assert_not_awaited()
    env.redraft.assert_not_awaited()
    env.trail.add.assert_not_awaited()


async def test_second_finding_on_a_replaced_plo_is_skipped(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    review = _review(redundancies=[_red("PLO1", "PLO2")], bloom=[_bloom("PLO2")])
    actions = await _sb(review)
    assert [a.outcome for a in actions] == ["applied", "skipped"]
    assert actions[1].outcome_reason_th == "PLO นี้ถูกแทนที่ไปแล้วในรอบนี้"
    assert env.redraft.await_count == 1


async def test_a_plo_that_is_gone_is_skipped(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    _Env(monkeypatch, plos)
    (action,) = await _sb(_review(bloom=[_bloom("PLO99")]))
    assert action.outcome == "skipped"
    assert action.outcome_reason_th == "ไม่พบ PLO นี้ในชุดปัจจุบัน"


async def test_refusal_and_failure_are_recorded_with_their_texts(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    env.redraft.side_effect = [
        RedraftRefused(422, "เกินเพดาน PLO หลัก"),
        RedraftFailed(),
        RuntimeError("boom"),
    ]
    review = _review(
        redundancies=[_red("PLO1", "PLO2")],
        unused_needs=[_unused("N7", agreed_runs=2), _unused("N8", agreed_runs=2)],
    )
    actions = await _sb(review)
    assert [(a.outcome, a.outcome_reason_th) for a in actions] == [
        ("skipped", "เกินเพดาน PLO หลัก"),
        ("failed", "ร่าง PLO ไม่สำเร็จ"),
        ("failed", "ร่าง PLO ไม่สำเร็จ"),
    ]
    assert all(a.result_plo_id is None for a in actions)
    assert env.trail.add.await_count == 3


async def test_bloom_note_comes_from_the_builder_and_result_level_is_recorded(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    (action,) = await _sb(_review(bloom=[_bloom("PLO3", "ระดับสูงเกินไป")]))
    expected = build_bloom_redraft_note_th(
        BloomLevel.APPLY, "ระดับสูงเกินไป", old_statement_th=plos[2].statement_th
    )
    assert env.redraft.await_args.kwargs["note_th"] == expected
    assert action.instruction_th == expected
    assert "Apply" in expected and "ระดับสูงเกินไป" in expected
    assert action.plo_ids == ["PLO3"] and action.need_ids == ["N3"]
    assert action.result_bloom_level == "apply"  # the new PLO's own level


async def test_redundancy_union_is_deduplicated_and_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _Env(monkeypatch, [_plo("PLO1", ["N1", "N2"]), _plo("PLO2", ["N2", "N3"])])
    (action,) = await _sb(_review(redundancies=[_red("PLO1", "PLO2")]))
    assert action.need_ids == ["N1", "N2", "N3"]
    assert env.redraft.await_args.args[2] == ["N1", "N2", "N3"]


async def test_redundancy_over_the_group_cap_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    big = [_plo("PLO1", [f"A{i}" for i in range(3)]), _plo("PLO2", [f"B{i}" for i in range(3)])]
    env = _Env(monkeypatch, big)
    (action,) = await _sb(_review(redundancies=[_red("PLO1", "PLO2")]))
    assert action.outcome == "skipped"
    assert action.outcome_reason_th == f"รวมแล้วเกิน {MAX_GROUP_SIZE} Need"
    env.redraft.assert_not_awaited()


@pytest.mark.parametrize("flag", ["unwritten", "out_of_scope"])
async def test_unused_unwritten_or_out_of_scope_is_skipped(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO], flag: str
) -> None:
    env = _Env(monkeypatch, plos)
    finding = (
        _unused("N7", agreed_runs=2, unwritten=True)
        if flag == "unwritten"
        else _unused("N7", agreed_runs=2, exclusion="out_of_scope")
    )
    (action,) = await _sb(_review(unused_needs=[finding]))
    assert action.outcome == "skipped"
    assert action.outcome_reason_th == "Need นี้ยังไม่มีประโยคหรืออยู่นอกขอบเขตหลักสูตร"
    env.redraft.assert_not_awaited()


async def test_unused_need_now_cited_this_round_is_not_redrafted(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    review = _review(
        redundancies=[_red("PLO1", "PLO2")],
        unused_needs=[_unused("N2", agreed_runs=2)],  # N2 is now behind the merged PLO
    )
    actions = await _sb(review)
    assert [a.outcome for a in actions] == ["applied", "skipped"]
    assert env.redraft.await_count == 1


async def test_aware_review_time_is_stored_naive_utc(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    _Env(monkeypatch, plos)
    aware = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
    review = _review(created_at=aware, unused_needs=[_unused("N7", agreed_runs=2)])
    (action,) = await _sb(review)
    assert action.review_created_at == datetime(2026, 11, 3, 8, 0)
    assert action.review_created_at.tzinfo is None


async def test_an_error_outside_the_actions_is_swallowed(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    env.trail.add.side_effect = RuntimeError("db")
    review = _review(unused_needs=[_unused("N7", agreed_runs=2)])
    actions = await _sb(review)
    assert len(actions) == 1 and actions[0].outcome == "applied"


async def test_a_failed_trail_write_does_not_stop_the_round(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    env.trail.add.side_effect = [RuntimeError("db"), None]
    review = _review(unused_needs=[_unused("N7", agreed_runs=2), _unused("N8", agreed_runs=2)])
    actions = await _sb(review)
    assert [a.outcome for a in actions] == ["applied", "applied"]
    assert env.trail.add.await_count == 2


async def test_a_ksec_finding_writes_no_row(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    review = _review(
        ksec=[
            KsecFinding(plo_id="PLO1", current=["S"], suggested=["K"], agrees=False, agreed_runs=5)
        ]
    )
    assert await _sb(review) == []
    env.redraft.assert_not_awaited()
    env.trail.add.assert_not_awaited()


async def test_a_real_refusal_text_passes_through_verbatim(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    """The text comes from the real `redraft_from_needs` check, not a stand-in."""
    from curriculum_agent.stages.plo_redraft import redraft_from_needs  # noqa: PLC0415

    env = _Env(monkeypatch, plos)
    merged_away = _need("N7").model_copy(update={"merged_into": "N8"})
    _install(monkeypatch, [merged_away], [], None)
    monkeypatch.setattr(pf, "redraft_from_needs", redraft_from_needs)
    (action,) = await _sb(_review(unused_needs=[_unused("N7", agreed_runs=2)]))
    assert action.outcome == "skipped"
    assert action.outcome_reason_th == "Need นี้ถูกรวมเข้ากับ Need อื่นแล้ว — เลือก Need ที่รวมแล้วแทน"
    env.trail.add.assert_awaited_once()


@pytest.mark.parametrize("level", list(BloomLevel))
def test_bloom_note_has_no_forbidden_word_for_any_level(level: BloomLevel) -> None:
    note = build_bloom_redraft_note_th(level, "")
    assert forbidden_words_in(note) == []
    assert level.value.capitalize() in note


# --------------------- fresh_review wiring ---------------------


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> PLOSetReview:
    review = _review()
    monkeypatch.setattr(pr, "_review", AsyncMock(return_value=review))
    monkeypatch.setattr(pr, "PLOReviewRepository", lambda: AsyncMock())
    return review


async def test_fresh_review_returns_the_review_even_when_send_back_raises(
    monkeypatch: pytest.MonkeyPatch, stored: PLOSetReview
) -> None:
    monkeypatch.setattr(pr, "send_back", AsyncMock(side_effect=RuntimeError("x")))
    review, feedback = await pr.fresh_review_with_feedback("cs-test", [])
    assert review is stored and feedback == []
    assert await pr.fresh_review("cs-test", []) is stored


async def test_stored_review_is_upserted_once_and_send_back_leaves_it_alone(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    review = _review(unused_needs=[_unused("N7", agreed_runs=2)])
    before = review.model_dump()
    order: list[str] = []
    repo = AsyncMock()
    repo.upsert.side_effect = lambda _r: order.append("upsert")

    async def _tracked(*a: object, **k: object) -> tuple[PLO, list[str]]:
        order.append("redraft")
        return await env._redraft(*a, **k)  # type: ignore[arg-type]

    env.redraft.side_effect = _tracked
    monkeypatch.setattr(pr, "_review", AsyncMock(return_value=review))
    monkeypatch.setattr(pr, "PLOReviewRepository", lambda: repo)
    got, feedback = await pr.fresh_review_with_feedback("cs-test", [])
    assert got is review and review.model_dump() == before
    repo.upsert.assert_awaited_once_with(review)
    assert order == ["upsert", "redraft"]
    assert [a.outcome for a in feedback] == ["applied"]


async def test_a_reused_stored_review_sends_nothing_back(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)  # send-back switched on, every repository faked
    stored = _review(
        plo_fingerprint=plo_fingerprint(plos, need_demands([])),
        redundancies=[_red("PLO1", "PLO2")],
        unused_needs=[_unused("N7", agreed_runs=2)],
    )
    monkeypatch.setattr(
        pr, "PLOReviewRepository", lambda: AsyncMock(get=AsyncMock(return_value=stored))
    )
    monkeypatch.setattr(
        pr, "NeedRepository", lambda: AsyncMock(list_active_by_program=AsyncMock(return_value=[]))
    )
    spy = AsyncMock(return_value=[])
    monkeypatch.setattr(pr, "send_back", spy)
    fresh = AsyncMock()
    monkeypatch.setattr(pr, "fresh_review_with_feedback", fresh)
    assert await pr.review_plo_set("cs-test", plos) is stored
    spy.assert_not_awaited()
    fresh.assert_not_awaited()
    env.redraft.assert_not_awaited()
    env.trail.add.assert_not_awaited()


async def test_fresh_review_with_feedback_returns_this_rounds_actions(
    monkeypatch: pytest.MonkeyPatch, stored: PLOSetReview
) -> None:
    action = FeedbackAction(
        program_id="cs-test", review_created_at=stored.created_at, kind="bloom", outcome="applied"
    )
    send = AsyncMock(return_value=[action])
    monkeypatch.setattr(pr, "send_back", send)
    review, feedback = await pr.fresh_review_with_feedback("cs-test", [])
    assert review is stored and feedback == [action]
    send.assert_awaited_once_with("cs-test", stored, [])
    assert "cs-test" not in pr._REVIEW_IN_FLIGHT


# --------------------- review ruling: majority of runs asked for ---------------------


def _votes(agreed: int, *, requested: int, succeeded: int, threshold: int) -> PLOSetReview:
    return _review(
        runs_requested=requested,
        runs_succeeded=succeeded,
        agreement_threshold=threshold,
        unused_needs=[_unused("N7", agreed_runs=agreed)],
    )


async def test_one_run_of_five_succeeding_sends_nothing_back(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    assert await _sb(_votes(1, requested=5, succeeded=1, threshold=1)) == []
    env.redraft.assert_not_awaited()


async def test_two_votes_out_of_three_successes_of_five_are_not_enough(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    assert await _sb(_votes(2, requested=5, succeeded=3, threshold=2)) == []
    env.redraft.assert_not_awaited()


async def test_three_votes_of_five_requested_are_acted_on(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    _Env(monkeypatch, plos)
    (action,) = await _sb(_votes(3, requested=5, succeeded=3, threshold=2))
    assert action.outcome == "applied"


async def test_a_single_requested_run_acts_on_its_findings(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    _Env(monkeypatch, plos)
    (action,) = await _sb(_votes(1, requested=1, succeeded=1, threshold=1))
    assert action.outcome == "applied"


# --------------------- review ruling: PLO edited since the review ---------------------

EDITED = "PLO นี้ถูกแก้หลังการตรวจ — ไม่ส่งกลับ"


async def test_a_plo_whose_statement_changed_since_the_review_is_skipped(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    env.plos[2] = env.plos[2].model_copy(update={"statement_th": "แก้ด้วยมือ"})
    (action,) = await _sb(_review(bloom=[_bloom("PLO3")]))
    assert (action.outcome, action.outcome_reason_th) == ("skipped", EDITED)
    env.redraft.assert_not_awaited()


async def test_a_plo_whose_needs_changed_since_the_review_is_skipped(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    env.plos[0] = env.plos[0].model_copy(update={"source_need_ids": ["N1", "N9"]})
    (action,) = await _sb(_review(redundancies=[_red("PLO1", "PLO2")]))
    assert (action.outcome, action.outcome_reason_th) == ("skipped", EDITED)
    env.redraft.assert_not_awaited()


async def test_replaced_is_judged_before_edited_and_edited_before_missing(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    review = _review(
        redundancies=[_red("PLO1", "PLO2")],
        bloom=[_bloom("PLO2"), _bloom("PLO3"), _bloom("PLO4")],
    )
    original = list(env.plos)
    # PLO3 is edited by hand and PLO4 deleted, both after the review judged them.
    env.plos[2] = env.plos[2].model_copy(update={"statement_th": "แก้ด้วยมือ"})
    del env.plos[3]
    actions = await _sb(review, original)
    assert [(a.outcome, a.outcome_reason_th) for a in actions] == [
        ("applied", ""),
        ("skipped", "PLO นี้ถูกแทนที่ไปแล้วในรอบนี้"),
        ("skipped", EDITED),
        ("skipped", "ไม่พบ PLO นี้ในชุดปัจจุบัน"),
    ]


async def test_an_unedited_plo_is_still_acted_on(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    _Env(monkeypatch, plos)
    (action,) = await _sb(_review(bloom=[_bloom("PLO3")]))
    assert action.outcome == "applied"


# --------------------- review ruling: do not make an approved PLO worse ---------------------

KEEP_SMART = "ร่างใหม่ไม่ผ่าน SMART — คงข้อเดิมไว้"
KEEP_LEVEL = "ร่างใหม่ไม่ได้ระดับ Bloom ที่ขอ — คงข้อเดิมไว้"


async def test_an_escalated_draft_does_not_replace_a_passing_plo(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    env.draft_update = {"smart_escalated": True}
    (action,) = await _sb(_review(redundancies=[_red("PLO1", "PLO2")]))
    assert (action.outcome, action.outcome_reason_th) == ("skipped", KEEP_SMART)
    assert [p.plo_id for p in env.plos] == ["PLO1", "PLO2", "PLO3", "PLO4"]


async def test_an_escalated_draft_may_replace_plos_that_were_all_escalated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = [_plo(f"PLO{i}", [f"N{i}"]).model_copy(update={"smart_escalated": True}) for i in (1, 2)]
    env = _Env(monkeypatch, bad)
    env.draft_update = {"smart_escalated": True}
    (action,) = await _sb(_review(redundancies=[_red("PLO1", "PLO2")]))
    assert action.outcome == "applied"


async def test_one_passing_plo_among_the_replaced_keeps_the_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mixed = [
        _plo("PLO1", ["N1"]).model_copy(update={"smart_escalated": True}),
        _plo("PLO2", ["N2"]),
    ]
    env = _Env(monkeypatch, mixed)
    env.draft_update = {"smart_escalated": True}
    (action,) = await _sb(_review(redundancies=[_red("PLO1", "PLO2")]))
    assert (action.outcome, action.outcome_reason_th) == ("skipped", KEEP_SMART)


async def test_an_escalated_unused_need_draft_is_refused_since_nothing_is_replaced(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    env.draft_update = {"smart_escalated": True}
    (action,) = await _sb(_review(unused_needs=[_unused("N7", agreed_runs=2)]))
    assert (action.outcome, action.outcome_reason_th) == ("skipped", KEEP_SMART)
    assert len(env.plos) == 4


async def test_a_bloom_draft_at_another_level_is_refused(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    env.draft_update = {"bloom_level": BloomLevel.CREATE}  # asked for APPLY
    (action,) = await _sb(_review(bloom=[_bloom("PLO3")]))
    assert (action.outcome, action.outcome_reason_th) == ("skipped", KEEP_LEVEL)
    assert env.plos[2].statement_th != "ใหม่ PLO3"


async def test_a_redundancy_draft_is_not_held_to_a_bloom_level(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    env.draft_update = {"bloom_level": BloomLevel.EVALUATE}
    (action,) = await _sb(_review(redundancies=[_red("PLO1", "PLO2")]))
    assert action.outcome == "applied"


# --------------------- graph path with send-back switched on ---------------------


async def test_graph_review_of_a_stale_stored_review_runs_fresh_and_sends_back_once(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)  # send-back on; program/PLO/trail repos and redraft patched
    stale = _review(plo_fingerprint="an-older-set")
    fresh = _review(
        plo_fingerprint=plo_fingerprint(plos, need_demands([])),
        redundancies=[_red("PLO1", "PLO2")],
    )
    repo = AsyncMock(get=AsyncMock(return_value=stale))
    monkeypatch.setattr(pr, "PLOReviewRepository", lambda: repo)
    monkeypatch.setattr(
        pr, "NeedRepository", lambda: AsyncMock(list_active_by_program=AsyncMock(return_value=[]))
    )
    monkeypatch.setattr(pr, "_review", AsyncMock(return_value=fresh))
    spy = AsyncMock(wraps=pf.send_back)
    monkeypatch.setattr(pr, "send_back", spy)

    assert await pr.review_plo_set("cs-test", plos) is fresh

    repo.upsert.assert_awaited_once_with(fresh)
    spy.assert_awaited_once()
    assert spy.await_args.args[0] == "cs-test" and spy.await_args.args[1] is fresh
    assert [p.plo_id for p in spy.await_args.args[2]] == [p.plo_id for p in plos]
    env.redraft.assert_awaited_once()
    assert env.trail.add.await_count == 1


async def test_send_back_skips_designer_edited_plo(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    """A hand-edited PLO is not overwritten, whichever finding names it. The
    review saw the edited text, so this is not the 'edited since review' case."""
    edited = datetime(2026, 11, 4, 8, 0, 0)
    plos[1] = plos[1].model_copy(update={"designer_edited_at": edited})
    env = _Env(monkeypatch, plos)
    review = _review(
        redundancies=[_red("PLO1", "PLO2")],
        bloom=[_bloom("PLO2")],
        unused_needs=[_unused("N2", agreed_runs=2)],
    )
    actions = await _sb(review)
    assert [(a.kind, a.outcome, a.outcome_reason_th) for a in actions] == [
        ("redundancy", "skipped", pf.REASON_DESIGNER_EDITED),
        ("bloom", "skipped", pf.REASON_DESIGNER_EDITED),
        ("unused_need", "skipped", pf.REASON_DESIGNER_EDITED),
    ]
    assert pf.REASON_DESIGNER_EDITED == "PLO นี้ผู้ออกแบบแก้เอง — ไม่เขียนทับ"
    env.redraft.assert_not_awaited()


async def test_edited_since_review_is_judged_before_designer_edited(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    edited = datetime(2026, 11, 4, 8, 0, 0)
    env = _Env(monkeypatch, plos)
    env.plos[2] = env.plos[2].model_copy(
        update={"statement_th": "แก้ด้วยมือ", "designer_edited_at": edited}
    )
    (action,) = await _sb(_review(bloom=[_bloom("PLO3")]))
    assert action.outcome_reason_th == EDITED


async def test_designer_edited_is_judged_before_missing(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    edited = datetime(2026, 11, 4, 8, 0, 0)
    plos[0] = plos[0].model_copy(update={"designer_edited_at": edited})
    env = _Env(monkeypatch, plos)
    del env.plos[1]  # PLO2 vanished, PLO1 is hand-edited and unchanged since the review
    (action,) = await _sb(_review(redundancies=[_red("PLO1", "PLO2")]))
    assert action.outcome_reason_th == pf.REASON_DESIGNER_EDITED


async def test_an_unedited_neighbour_of_a_designer_edited_plo_is_still_acted_on(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    plos[1] = plos[1].model_copy(update={"designer_edited_at": datetime(2026, 11, 4)})
    env = _Env(monkeypatch, plos)
    (action,) = await _sb(_review(bloom=[_bloom("PLO3")]))
    assert action.outcome == "applied"
    env.redraft.assert_awaited_once()


# --------------------- phase 6: alignment, KSEC gap, verb, rounds, dry run ---------------------


def _align(plo_id: str) -> AlignmentFinding:
    return AlignmentFinding(plo_id=plo_id, reason_th="ไม่ตรง", suggestion_th="ปรับ", agreed_runs=2)


def _ksec_need(nid: str, cats: list[str], demand: float, **kw: bool) -> Need:
    need = _need(nid, in_scope=kw.get("in_scope", True))
    update: dict[str, object] = {"demand_score": demand, "ksec_categories": cats}
    if kw.get("unwritten"):
        update["statement_th"] = "[ต้องทบทวน] ทักษะ ก, ข"
    return need.model_copy(update=update)


def _needs(monkeypatch: pytest.MonkeyPatch, needs: list[Need]) -> None:
    repo = AsyncMock(
        list_active_by_program=AsyncMock(return_value=needs),
        list_by_program=AsyncMock(return_value=needs),
    )
    monkeypatch.setattr(pf, "NeedRepository", lambda: repo)


async def test_order_includes_alignment_and_ksec_gap(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    _Env(monkeypatch, plos)
    _needs(monkeypatch, [_ksec_need("N6", ["E"], 0.9)])
    review = _review(
        unused_needs=[_unused("N8", agreed_runs=2)],
        bloom=[_bloom("PLO3")],
        alignment=[_align("PLO4")],
        redundancies=[_red("PLO1", "PLO2")],
        ksec_coverage=KsecCoverage(missing=["E"]),
    )
    actions = await _sb(review)
    assert [a.kind for a in actions] == [
        "redundancy",
        "alignment",
        "bloom",
        "ksec_gap",
        "unused_need",
    ]


async def test_alignment_redraft_passes_its_note(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    (action,) = await _sb(_review(alignment=[_align("PLO2")]))
    note = env.redraft.await_args.kwargs["note_th"]
    assert note == action.instruction_th
    assert "ไม่ตรง" in note and plos[1].statement_th in note
    assert env.redraft.await_args.args[2] == ["N2"]
    assert action.kind == "alignment" and action.outcome == "applied"


async def test_alignment_skips_designer_edited(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    plos[1] = plos[1].model_copy(update={"designer_edited_at": datetime(2026, 11, 3)})
    env = _Env(monkeypatch, plos)
    (action,) = await _sb(_review(alignment=[_align("PLO2")]))
    assert (action.outcome, action.outcome_reason_th) == ("skipped", pf.REASON_DESIGNER_EDITED)
    env.redraft.assert_not_awaited()


async def test_ksec_gap_picks_top_eligible_need(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    _needs(
        monkeypatch,
        [
            _ksec_need("N5", ["E"], 0.4),
            _ksec_need("N6", ["E", "K"], 0.8),
            _ksec_need("N7", ["E"], 0.95, unwritten=True),
            _ksec_need("N8", ["E"], 0.99, in_scope=False),
            _ksec_need("N1", ["E"], 0.97),  # cited by PLO1
            _ksec_need("N9", ["S"], 0.9),
        ],
    )
    (action,) = await _sb(_review(ksec_coverage=KsecCoverage(missing=["E"])))
    assert action.kind == "ksec_gap" and action.outcome == "applied"
    assert action.need_ids == ["N6"] and env.redraft.await_args.args[2] == ["N6"]
    assert action.instruction_th == build_ksec_gap_note_th("E")


async def test_ksec_gap_without_candidate_is_skipped_with_exact_text(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    _needs(monkeypatch, [_ksec_need("N7", ["E"], 0.95, unwritten=True)])
    (action,) = await _sb(_review(ksec_coverage=KsecCoverage(missing=["E"])))
    assert action.outcome == "skipped"
    assert action.outcome_reason_th == "ไม่มี Need หมวดนี้ — ต้องเพิ่มที่ขั้น Need"
    assert action.outcome_reason_th == pf.REASON_KSEC_NO_NEED
    env.redraft.assert_not_awaited()


async def test_ksec_gap_ceiling_refusal_is_skipped(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    _needs(monkeypatch, [_ksec_need("N7", ["S"], 0.9)])
    env.redraft.side_effect = RedraftRefused(409, "เกินเพดาน PLO หลัก")
    (action,) = await _sb(_review(ksec_coverage=KsecCoverage(missing=["S"])))
    assert (action.outcome, action.outcome_reason_th) == ("skipped", "เกินเพดาน PLO หลัก")


async def test_bloom_verb_only_finding_acts(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    env.draft_update = {"bloom_level": BloomLevel.CREATE}
    finding = BloomFinding(
        plo_id="PLO3",
        declared=BloomLevel.CREATE,
        suggested_level=BloomLevel.CREATE,  # a verb-only vote carries the declared level
        suggested_verb_th="ประเมิน",
        suggestion_th="ใช้กริยาประเมิน",
        reason_th="กริยาไม่เหมาะ",
        agreed_runs=2,
    )
    (action,) = await _sb(_review(bloom=[finding]))
    assert action.kind == "bloom" and action.outcome == "applied"
    note = env.redraft.await_args.kwargs["note_th"]
    assert "ประเมิน" in note and "Bloom:" not in note


async def test_bloom_without_level_change_or_verb_is_not_actionable(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    finding = BloomFinding(
        plo_id="PLO3", declared=BloomLevel.CREATE, suggested_level=None, agreed_runs=2
    )
    assert await _sb(_review(bloom=[finding])) == []
    env.redraft.assert_not_awaited()


async def test_merge_drift_skip(monkeypatch: pytest.MonkeyPatch, plos: list[PLO]) -> None:
    env = _Env(monkeypatch, plos)
    memory = pf.LoopMemory(merged={("PLO1", plos[0].statement_th)})
    (action,) = await pf.send_back(
        "cs-test", _review(redundancies=[_red("PLO1", "PLO2")]), env.initial, memory=memory
    )
    assert (action.outcome, action.outcome_reason_th) == ("skipped", pf.REASON_MERGED_EARLIER)
    env.redraft.assert_not_awaited()


async def test_applied_redundancy_is_added_to_memory(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    memory = pf.LoopMemory()
    (action,) = await pf.send_back(
        "cs-test", _review(redundancies=[_red("PLO1", "PLO2")]), env.initial, memory=memory
    )
    assert action.outcome == "applied"
    assert memory.merged == {(str(action.result_plo_id), str(action.result_statement_th))}


async def test_dry_run_plans_without_redrafting(monkeypatch: pytest.MonkeyPatch) -> None:
    # Six core PLOs: merging two of four would be refused by the merge floor, which
    # a dry run now checks (final review I3).
    env = _Env(monkeypatch, _core(6))
    memory = pf.LoopMemory()
    review = _review(
        redundancies=[_red("PLO1", "PLO2")], bloom=[_bloom("PLO3")], alignment=[_align("PLO4")]
    )
    actions = await pf.send_back("cs-test", review, env.initial, dry_run=True, memory=memory)
    env.redraft.assert_not_awaited()
    assert [a.outcome for a in actions] == ["planned", "planned", "planned"]
    assert [a.kind for a in actions] == ["redundancy", "alignment", "bloom"]
    assert actions[0].need_ids == ["N1", "N2"] and actions[1].need_ids == ["N4"]
    assert actions[1].instruction_th and actions[2].instruction_th
    assert memory.merged == set()
    assert env.plos == env.initial


async def test_round_is_stored_on_every_row(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    actions = await pf.send_back(
        "cs-test", _review(bloom=[_bloom("PLO3")]), env.initial, round_no=2
    )
    assert [a.round for a in actions] == [2]
    assert env.trail.add.await_args.args[0][0].round == 2


async def test_redundancy_note_includes_both_old_statements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ps = [
        _plo("PLO1", ["N1"]).model_copy(update={"statement_th": "ร่างข้อหนึ่ง"}),
        _plo("PLO2", ["N2"]).model_copy(update={"statement_th": "ร่างข้อสอง"}),
    ]
    env = _Env(monkeypatch, ps)
    await _sb(_review(redundancies=[_red("PLO1", "PLO2")]))
    note = env.redraft.await_args.kwargs["note_th"]
    assert "ร่างข้อหนึ่ง" in note and "ร่างข้อสอง" in note and "ซ้ำ" in note


async def test_unused_consider_passes_its_note(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    await _sb(_review(unused_needs=[_unused("N7", agreed_runs=2)]))
    assert "เหตุผล N7" in env.redraft.await_args.kwargs["note_th"]


def test_actionable_count() -> None:
    def row(outcome: str, reason: str = "") -> FeedbackAction:
        return FeedbackAction(
            program_id="p",
            review_created_at=datetime(2026, 11, 3),
            kind="x",
            outcome=outcome,
            outcome_reason_th=reason,
        )

    rows = [
        row("applied"),
        row("failed"),
        row("planned"),
        row("skipped", "เกินเพดาน"),
        row("skipped", pf.REASON_KSEC_NO_NEED),
        row("stopped"),
    ]
    assert pf.actionable_count(rows) == 4


async def test_dry_run_alignment_on_plo_a_planned_redundancy_replaces_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _Env(monkeypatch, _core(6))  # above the merge floor, see the test above
    review = _review(redundancies=[_red("PLO1", "PLO2")], alignment=[_align("PLO1")])
    actions = await pf.send_back("cs-test", review, env.initial, dry_run=True)
    assert [(a.kind, a.outcome) for a in actions] == [
        ("redundancy", "planned"),
        ("alignment", "skipped"),
    ]
    assert actions[1].outcome_reason_th == pf.REASON_ALREADY_REPLACED


async def test_dry_run_unused_on_need_a_ksec_gap_planned_is_skipped(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    _needs(monkeypatch, [_ksec_need("N7", ["E"], 0.9)])
    review = _review(
        ksec_coverage=KsecCoverage(missing=["E"]), unused_needs=[_unused("N7", agreed_runs=2)]
    )
    actions = await pf.send_back("cs-test", review, env.initial, dry_run=True)
    assert [(a.kind, a.outcome) for a in actions] == [
        ("ksec_gap", "planned"),
        ("unused_need", "skipped"),
    ]
    assert actions[1].outcome_reason_th == pf.REASON_NEED_NOW_CITED


async def test_dry_run_ksec_gap_does_not_plan_the_same_need_twice(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)
    _needs(monkeypatch, [_ksec_need("N7", ["E", "K"], 0.9)])
    review = _review(ksec_coverage=KsecCoverage(missing=["E", "K"]))
    actions = await pf.send_back("cs-test", review, env.initial, dry_run=True)
    assert [a.outcome for a in actions] == ["planned", "skipped"]


# --------------------- final review I3: a dry run runs the pre-draft checks ---------------------


def _core(n: int) -> list[PLO]:
    return [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, n + 1)]


@pytest.mark.parametrize("kind", ["ksec_gap", "unused_need"])
async def test_dry_run_on_a_full_set_skips_an_addition_with_the_ceiling_text(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    env = _Env(monkeypatch, _core(10))
    _needs(monkeypatch, [*env.needs[:10], _ksec_need("N11", ["E"], 0.9)])
    review = (
        _review(ksec_coverage=KsecCoverage(missing=["E"]))
        if kind == "ksec_gap"
        else _review(unused_needs=[_unused("N11", agreed_runs=2)])
    )
    (action,) = await pf.send_back("cs-test", review, env.initial, dry_run=True)
    assert (action.kind, action.outcome) == (kind, "skipped")
    assert action.outcome_reason_th.startswith("การรวมนี้จะทำให้มี PLO หลัก 11 ข้อ เกินเพดาน 10 ข้อ")
    env.redraft.assert_not_awaited()


async def test_dry_run_merge_below_the_floor_is_skipped(
    monkeypatch: pytest.MonkeyPatch, plos: list[PLO]
) -> None:
    env = _Env(monkeypatch, plos)  # 4 core: merging two leaves 3, under MIN_CORE_AFTER_MERGE
    (action,) = await pf.send_back(
        "cs-test", _review(redundancies=[_red("PLO1", "PLO2")]), env.initial, dry_run=True
    )
    assert action.outcome == "skipped"
    assert action.outcome_reason_th.startswith("การรวมนี้จะเหลือ PLO หลัก 3 ข้อ ต่ำกว่าขั้นต่ำของการรวม 4 ข้อ")


async def test_dry_run_counts_its_own_planned_additions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _Env(monkeypatch, _core(9))
    review = _review(unused_needs=[_unused("N10", agreed_runs=2), _unused("N11", agreed_runs=2)])
    actions = await pf.send_back("cs-test", review, env.initial, dry_run=True)
    assert [a.outcome for a in actions] == ["planned", "skipped"]
    assert "11 ข้อ เกินเพดาน" in actions[1].outcome_reason_th


async def test_dry_run_counts_the_outcome_a_planned_redraft_writes_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A planned alignment redraft replaces PLO3 with a new PLO, so the set stays at
    10 and a later addition is over the ceiling, as it would be when applied."""
    env = _Env(monkeypatch, _core(10))
    review = _review(alignment=[_align("PLO3")], unused_needs=[_unused("N11", agreed_runs=2)])
    actions = await pf.send_back("cs-test", review, env.initial, dry_run=True)
    assert [(a.kind, a.outcome) for a in actions] == [
        ("alignment", "planned"),
        ("unused_need", "skipped"),
    ]
    assert "11 ข้อ เกินเพดาน" in actions[1].outcome_reason_th


def test_check_redraft_answers_what_redraft_from_needs_refuses() -> None:
    from curriculum_agent.stages.plo_redraft import check_redraft  # noqa: PLC0415

    needs = [_need(f"N{i}") for i in range(1, 12)]
    assert check_redraft(_core(4), needs, ["N1"]) is None
    assert check_redraft(_core(4), needs, ["NOPE"]) == "ไม่พบ Need: NOPE"
    ceiling = check_redraft(_core(10), needs, ["N11"])
    assert ceiling is not None and ceiling.startswith("การรวมนี้จะทำให้มี PLO หลัก 11 ข้อ")
    floor = check_redraft(_core(4), needs, ["N1", "N2"])
    assert floor is not None and floor.startswith("การรวมนี้จะเหลือ PLO หลัก 3 ข้อ")
