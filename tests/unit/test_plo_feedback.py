from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, call

import pytest

from curriculum_agent.config import settings
from curriculum_agent.models import (
    PLO,
    BloomFinding,
    BloomLevel,
    FeedbackAction,
    KsecFinding,
    PLOSetReview,
    RedundancyFinding,
    UnusedNeedFinding,
)
from curriculum_agent.prompts.plo_feedback import build_bloom_redraft_note_th
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
    expected = build_bloom_redraft_note_th(BloomLevel.APPLY, "ระดับสูงเกินไป")
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
