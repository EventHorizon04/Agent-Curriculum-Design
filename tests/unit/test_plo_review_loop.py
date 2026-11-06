from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from curriculum_agent.config import settings
from curriculum_agent.models import AlignmentFinding, FeedbackAction, KsecCoverage, PLOSetReview
from curriculum_agent.stages import plo_review as pr
from curriculum_agent.stages import plo_review_loop as loop
from curriculum_agent.stages.plo_feedback import (
    REASON_ALIGNED_EARLIER,
    REASON_KSEC_NO_NEED,
    LoopMemory,
)
from tests.unit.test_api_plos import _plo


def _rev(
    by: str = "agent", n: int = 0, *, work: bool = True, fp: str | None = None
) -> PLOSetReview:
    """`work` gives the review one agreed finding, so "pass" is not its verdict:
    since final review M3 the loop reads "pass" off the review, not off the rows."""
    return PLOSetReview(
        program_id="p",
        plo_fingerprint=fp or f"f{n}",
        model="m",
        created_at=datetime(2026, 11, 3, 1, 2, n),
        reviewed_by=by,
        agreement_threshold=2,
        alignment=(
            [AlignmentFinding(plo_id="PLO1", reason_th="ไม่ตรง", agreed_runs=2)]
            if work and by == "agent"
            else []
        ),
    )


def _row(outcome: str, rnd: int, reason: str = "x") -> FeedbackAction:
    return FeedbackAction(
        program_id="p",
        review_created_at=datetime(2026, 11, 3),
        kind="bloom",
        outcome=outcome,
        outcome_reason_th=reason,
        round=rnd,
    )


class _Env:
    def __init__(self, mp: pytest.MonkeyPatch, reviews: list[PLOSetReview | Exception]) -> None:
        self.reviews = list(reviews)
        self.sends: list[list[FeedbackAction] | Exception] = []
        self.send_kwargs: list[dict[str, object]] = []
        self.review_calls = 0
        self.live = [_plo("PLO1", ["N1"])]
        self.trail = AsyncMock()
        self.store = AsyncMock()
        self.once = AsyncMock(return_value=(_rev(), []))

        async def _review(_pid: str, _plos: object) -> PLOSetReview:
            self.review_calls += 1
            item = self.reviews.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        async def _send(*_a: object, **kw: object) -> list[FeedbackAction]:
            self.send_kwargs.append(kw)
            item = self.sends.pop(0)
            if isinstance(item, Exception):
                raise item
            sink = kw.get("sink")
            if isinstance(sink, list):
                sink.extend(item)  # as the real send_back records its rows
            return item

        self.send = AsyncMock(side_effect=_send)
        mp.setattr(pr, "_review", _review)
        mp.setattr(pr, "_review_once_with_send_back", self.once)
        mp.setattr(loop, "send_back", self.send)
        mp.setattr(loop, "PLOFeedbackRepository", lambda: self.trail)
        mp.setattr(loop, "PLOReviewRepository", lambda: self.store)
        mp.setattr(
            loop,
            "PLORepository",
            lambda: AsyncMock(list_by_program=AsyncMock(return_value=self.live)),
        )
        mp.setattr(settings, "plo_review_loop_mode", "apply")
        mp.setattr(settings, "plo_review_max_rounds", 5)
        mp.setattr(settings, "plo_review_send_back", True)
        mp.setattr(settings, "plo_review_loop_timeout_seconds", 5400)

    def ends(self) -> list[FeedbackAction]:
        rows = [c.args[0][0] for c in self.trail.add.await_args_list]
        return [r for r in rows if r.kind == "loop_end"]


async def test_off_mode_is_phase4(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [])
    monkeypatch.setattr(settings, "plo_review_loop_mode", "off")
    got = await loop.run_review_loop("p", [])
    assert got == env.once.return_value
    env.once.assert_awaited_once_with("p", [])
    env.send.assert_not_awaited()
    assert env.review_calls == 0


async def test_max_rounds_zero_is_phase4(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [])
    monkeypatch.setattr(settings, "plo_review_max_rounds", 0)
    await loop.run_review_loop("p", [])
    env.once.assert_awaited_once()
    env.trail.add.assert_not_awaited()


async def test_shadow_one_review_planned_rows_no_write(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_rev()])
    monkeypatch.setattr(settings, "plo_review_loop_mode", "shadow")
    env.sends.append([_row("planned", 1)])
    review, rows = await loop.run_review_loop("p", [])
    assert env.review_calls == 1
    assert {k: v for k, v in env.send_kwargs[0].items() if k != "sink"} == {
        "round_no": 1,
        "dry_run": True,
    }
    assert [r.outcome for r in rows] == ["planned", "stopped"]
    (end,) = env.ends()
    assert end.round == 1 and end.outcome_reason_th == "โหมดทดลอง — ยังไม่แก้ PLO"
    env.store.upsert.assert_awaited_once_with(review)


async def test_apply_pass_on_first_review(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_rev(work=False)])
    env.sends.append([_row("skipped", 1, REASON_KSEC_NO_NEED)])
    _, rows = await loop.run_review_loop("p", [])
    assert env.review_calls == 1
    (end,) = env.ends()
    assert end.round == 1 and end.outcome_reason_th == "ผ่านการตรวจ — ไม่มีข้อที่ต้องแก้"
    assert rows[-1] is end


async def test_loop_stops_when_round_applies_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_rev(n=1), _rev(n=2)])
    env.sends.append([_row("skipped", 1, "PLO นี้ถูกแก้หลังการตรวจ — ไม่ส่งกลับ")])
    _, rows = await loop.run_review_loop("p", [])
    assert env.review_calls == 1
    (end,) = env.ends()
    assert end.round == 1 and end.outcome_reason_th == "รอบนี้แก้อะไรไม่ได้ — หยุด"
    assert len(rows) == 2


async def test_cap_ends_with_review(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_rev(n=i) for i in range(6)])
    env.sends.extend([[_row("applied", i)] for i in range(1, 6)])
    review, rows = await loop.run_review_loop("p", [])
    assert env.review_calls == 6 and env.send.await_count == 5
    assert review.plo_fingerprint == "f5"
    (end,) = env.ends()
    assert end.round == 6 and end.outcome_reason_th == "ส่งกลับครบ 5 รอบแล้ว"
    assert [k["round_no"] for k in env.send_kwargs] == [1, 2, 3, 4, 5]
    assert env.send_kwargs[0]["memory"] is env.send_kwargs[4]["memory"]
    assert len(rows) == 6


async def test_timeout_runs_final_review(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_rev(n=1), _rev(n=2)])
    monkeypatch.setattr(settings, "plo_review_loop_timeout_seconds", 1)

    async def _hang(*_a: object, **kw: object) -> list[FeedbackAction]:
        sink = kw["sink"]
        assert isinstance(sink, list)
        sink.append(_row("applied", 1))  # written before the budget ran out
        await asyncio.sleep(10)
        return []

    env.send.side_effect = _hang
    real = asyncio.timeout
    monkeypatch.setattr(loop.asyncio, "timeout", lambda _s: real(0.05))
    review, rows = await loop.run_review_loop("p", [])
    assert env.review_calls == 2 and review.plo_fingerprint == "f2"
    (end,) = env.ends()
    assert end.round == 1 and end.outcome_reason_th == "หมดเวลา 1 วินาที — ตรวจชุดสุดท้ายแล้ว"
    assert env.send.await_count == 1
    assert [r.outcome for r in rows] == ["applied", "stopped"] and rows[-1] is end


async def test_exception_in_round_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_rev(n=1), _rev(n=2)])
    env.sends.append(RuntimeError("boom"))
    review, _rows = await loop.run_review_loop("p", [])
    assert review.plo_fingerprint == "f2"
    (end,) = env.ends()
    assert end.round == 1 and end.outcome_reason_th == "เกิดข้อผิดพลาด — หยุด"


async def test_provider_timeout_in_round_is_an_error_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_rev(n=1), _rev(n=2)])
    env.sends.append(TimeoutError("provider"))
    review, _rows = await loop.run_review_loop("p", [])
    assert review.plo_fingerprint == "f2"
    (end,) = env.ends()
    assert end.round == 1 and end.outcome_reason_th == "เกิดข้อผิดพลาด — หยุด"


async def test_timeout_in_first_review_with_failing_final_review_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Env(monkeypatch, [TimeoutError("x"), RuntimeError("y")])
    real = asyncio.timeout
    monkeypatch.setattr(loop.asyncio, "timeout", lambda _s: real(0.05))

    async def _slow(*_a: object) -> PLOSetReview:
        await asyncio.sleep(10)
        raise AssertionError

    monkeypatch.setattr(pr, "_review", _slow)
    with pytest.raises(TimeoutError):
        await loop.run_review_loop("p", [])


async def test_shadow_through_fresh_review_with_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_rev()])
    monkeypatch.setattr(settings, "plo_review_loop_mode", "shadow")

    async def _plan(*_a: object, **kw: object) -> list[FeedbackAction]:
        sink = kw["sink"]
        assert isinstance(sink, list)
        sink.append(_row("planned", 1))
        return sink

    env.send.side_effect = _plan
    review, rows = await pr.fresh_review_with_feedback("p", [])
    assert [r.outcome for r in rows] == ["planned", "stopped"]
    assert rows[-1].kind == "loop_end" and review.reviewed_by == "agent"
    assert "p" not in pr._REVIEW_IN_FLIGHT


async def test_first_review_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    _Env(monkeypatch, [RuntimeError("db")])
    with pytest.raises(RuntimeError):
        await loop.run_review_loop("p", [])


async def test_code_only_review_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_rev("code_only")])
    await loop.run_review_loop("p", [])
    env.send.assert_not_awaited()
    (end,) = env.ends()
    assert end.round == 1 and end.outcome_reason_th == "ไม่มีผลตรวจจาก agent — ไม่ส่งกลับ"


async def test_send_back_switch_off_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_rev()])
    monkeypatch.setattr(settings, "plo_review_send_back", False)
    await loop.run_review_loop("p", [])
    env.send.assert_not_awaited()
    # Its own reason since final review M3: the review was the agent's.
    assert env.ends()[0].outcome_reason_th == "ปิดการส่งกลับ — ไม่แก้ PLO"


async def test_trail_write_failure_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_rev("code_only")])
    env.trail.add.side_effect = RuntimeError("db")
    _, rows = await loop.run_review_loop("p", [])
    assert rows[-1].kind == "loop_end"


# --------------------- final review M3: stop reasons say what happened ---------------------


def _need_repo(monkeypatch: pytest.MonkeyPatch, needs: list[object]) -> None:
    from curriculum_agent.stages import plo_feedback as pf  # noqa: PLC0415

    repo = AsyncMock(list_active_by_program=AsyncMock(return_value=needs))
    monkeypatch.setattr(pf, "NeedRepository", lambda: repo)


async def test_send_back_returning_early_is_not_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _Env(monkeypatch, [_rev(n=1)])
    env.sends.append([])  # agreed work, but send_back stopped before writing a row
    await loop.run_review_loop("p", [])
    (end,) = env.ends()
    assert end.round == 1 and end.outcome_reason_th == "ส่งกลับไม่สำเร็จ — หยุด"
    assert loop.REASON_SEND_BACK_FAILED == "ส่งกลับไม่สำเร็จ — หยุด"


async def test_a_ksec_gap_with_an_eligible_need_is_work(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit.test_plo_feedback import _ksec_need  # noqa: PLC0415

    _need_repo(monkeypatch, [_ksec_need("N7", ["E"], 0.9)])
    review = _rev(n=1, work=False).model_copy(update={"ksec_coverage": KsecCoverage(missing=["E"])})
    env = _Env(monkeypatch, [review])
    env.sends.append([_row("skipped", 1, "เกินเพดาน")])
    await loop.run_review_loop("p", [])
    assert env.ends()[0].outcome_reason_th == "รอบนี้แก้อะไรไม่ได้ — หยุด"


async def test_a_ksec_gap_without_a_need_is_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit.test_plo_feedback import _ksec_need  # noqa: PLC0415

    _need_repo(monkeypatch, [_ksec_need("N7", ["E"], 0.9, unwritten=True)])
    review = _rev(n=1, work=False).model_copy(update={"ksec_coverage": KsecCoverage(missing=["E"])})
    env = _Env(monkeypatch, [review])
    env.sends.append([_row("skipped", 1, REASON_KSEC_NO_NEED)])
    await loop.run_review_loop("p", [])
    assert env.ends()[0].outcome_reason_th == "ผ่านการตรวจ — ไม่มีข้อที่ต้องแก้"


async def test_pass_is_read_off_the_review_not_the_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """A review with nothing agreed is a pass even when send-back wrote a row a
    stale count would call actionable."""
    env = _Env(monkeypatch, [_rev(n=1, work=False)])
    env.sends.append([_row("skipped", 1, "อะไรก็ได้")])
    await loop.run_review_loop("p", [])
    assert env.ends()[0].outcome_reason_th == "ผ่านการตรวจ — ไม่มีข้อที่ต้องแก้"


# --------------------- final review M4: a late outage keeps the comments ---------------------

LATE = "ผู้ตรวจไม่ตอบในรอบนี้ — ใช้ผลตรวจรอบก่อน"


async def test_late_code_only_review_restores_the_last_agent_review_on_the_same_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _rev(n=1, fp="same")
    env = _Env(monkeypatch, [agent, _rev("code_only", n=2, fp="same")])
    env.sends.append([_row("applied", 1)])
    review, _rows = await loop.run_review_loop("p", [])
    assert review is agent
    assert [c.args[0] for c in env.store.upsert.await_args_list][-1] is agent
    (end,) = env.ends()
    assert end.round == 2 and end.outcome_reason_th == LATE


async def test_late_code_only_review_on_a_changed_set_is_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    late = _rev("code_only", n=2)
    env = _Env(monkeypatch, [_rev(n=1), late])
    env.sends.append([_row("applied", 1)])
    review, _rows = await loop.run_review_loop("p", [])
    assert review is late  # a stored review must describe the stored set
    assert env.store.upsert.await_count == 2
    assert env.ends()[0].outcome_reason_th == LATE


async def test_a_first_round_code_only_review_still_says_no_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _Env(monkeypatch, [_rev("code_only", n=1)])
    await loop.run_review_loop("p", [])
    assert env.ends()[0].outcome_reason_th == "ไม่มีผลตรวจจาก agent — ไม่ส่งกลับ"


async def test_round_with_only_guarded_alignment_is_a_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 1 applies an alignment redraft on PLO1; round 2's only agreed finding
    is alignment on PLO1 again (guarded, decision 28): a pass, no third review."""
    env = _Env(monkeypatch, [_rev(n=1), _rev(n=2)])
    calls: list[int] = []

    async def _send(*_a: object, **kw: object) -> list[FeedbackAction]:
        mem = kw["memory"]
        assert isinstance(mem, LoopMemory)
        rnd = kw["round_no"]
        assert isinstance(rnd, int)
        calls.append(rnd)
        if rnd == 1:
            mem.aligned.add(frozenset({"N1"}))
            rows = [_row("applied", 1)]
        else:
            rows = [_row("skipped", 2, REASON_ALIGNED_EARLIER)]
        sink = kw["sink"]
        assert isinstance(sink, list)
        sink.extend(rows)
        return rows

    monkeypatch.setattr(loop, "send_back", _send)
    await loop.run_review_loop("p", [])
    assert calls == [1, 2]
    assert env.review_calls == 2
    assert env.ends()[0].outcome_reason_th == "ผ่านการตรวจ — ไม่มีข้อที่ต้องแก้"
