"""Review -> send-back loop (phase 6).

`run_review_loop` wraps stage 06 and send-back: review the live PLO set, send the
agreed findings back, review again, until a stop condition holds. The caller
(`plo_review.fresh_review_with_feedback`) holds the `_REVIEW_IN_FLIGHT` guard.

Modes (`settings.plo_review_loop_mode`):
- `off`, or `plo_review_max_rounds == 0`: the phase-4 single pass.
- `shadow`: one review, then a dry-run send-back (rows `planned`, nothing changes).
- `apply`: up to `plo_review_max_rounds` send-back rounds under one time budget.

Every stop of the loop writes one `loop_end` trail row with its round and a Thai
reason. Nothing past the first stored review can fail the caller.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from loguru import logger

from curriculum_agent.config import settings
from curriculum_agent.data.repositories import (
    PLOFeedbackRepository,
    PLORepository,
    PLOReviewRepository,
)
from curriculum_agent.models import PLO, FeedbackAction, PLOSetReview
from curriculum_agent.stages import plo_review
from curriculum_agent.stages.plo_feedback import (
    LoopMemory,
    actionable_count,
    has_agreed_work,
    send_back,
)

REASON_SHADOW = "โหมดทดลอง — ยังไม่แก้ PLO"
REASON_PASS = "ผ่านการตรวจ — ไม่มีข้อที่ต้องแก้"
REASON_NO_CHANGE = "รอบนี้แก้อะไรไม่ได้ — หยุด"
REASON_NO_AGENT = "ไม่มีผลตรวจจาก agent — ไม่ส่งกลับ"
REASON_ERROR = "เกิดข้อผิดพลาด — หยุด"
REASON_SEND_BACK_OFF = "ปิดการส่งกลับ — ไม่แก้ PLO"
REASON_SEND_BACK_FAILED = "ส่งกลับไม่สำเร็จ — หยุด"
REASON_REVIEWER_LATE = "ผู้ตรวจไม่ตอบในรอบนี้ — ใช้ผลตรวจรอบก่อน"


def _reason_cap(max_rounds: int) -> str:
    return f"ส่งกลับครบ {max_rounds} รอบแล้ว"


def _reason_timeout(seconds: int) -> str:
    return f"หมดเวลา {seconds} วินาที — ตรวจชุดสุดท้ายแล้ว"


@dataclass
class _Run:
    """What the loop has produced so far, kept outside the timeout scope so an
    abandoned round still leaves its review and rows behind."""

    program_id: str
    review: PLOSetReview | None = None
    rows: list[FeedbackAction] = field(default_factory=list)
    round_no: int = 0
    stop_reason: str | None = None


async def _end(run: _Run, reason: str) -> None:
    """Write the one `loop_end` row. A failed write is logged, never raised."""
    created = run.review.created_at if run.review else datetime.now(UTC).replace(tzinfo=None)
    row = FeedbackAction(
        program_id=run.program_id,
        review_created_at=created,
        kind="loop_end",
        outcome="stopped",
        outcome_reason_th=reason,
        round=run.round_no,
    )
    run.rows.append(row)
    logger.info(f"plo_review_loop: {run.program_id} stopped at round {run.round_no}: {reason}")
    try:
        await PLOFeedbackRepository().add([row])
    except Exception as exc:
        logger.error(f"plo_review_loop: could not write trail row {row.model_dump_json()}: {exc!r}")


async def _review_live(run: _Run, plos: Sequence[PLO] | None) -> Sequence[PLO]:
    """Review `plos` (the live stored set when None) and store the review. Returns
    the set that was reviewed."""
    if plos is None:
        plos = await PLORepository().list_by_program(run.program_id)
    review = await plo_review._review(run.program_id, plos)
    await PLOReviewRepository().upsert(review)
    run.review = review
    return plos


async def _keep_last_agent_review(run: _Run, last_agent: PLOSetReview) -> None:
    """A later round's reviewer did not answer: show the last agent review again,
    so the checkpoint keeps its comments — but only while it still describes the
    stored set. When the set changed after it (it normally did: that round applied
    something), the code-only review stays, because a stored review must describe
    the stored set."""
    review = run.review
    assert review is not None
    if review.plo_fingerprint != last_agent.plo_fingerprint:
        return
    await PLOReviewRepository().upsert(last_agent)
    run.review = last_agent


async def _rounds(run: _Run, plos: Sequence[PLO]) -> None:
    max_rounds = settings.plo_review_max_rounds
    mem = LoopMemory()
    last_agent: PLOSetReview | None = None
    for i in range(1, max_rounds + 2):
        run.round_no = i
        reviewed = await _review_live(run, plos if i == 1 else None)
        review = run.review
        assert review is not None
        if i == max_rounds + 1:
            await _end(run, _reason_cap(max_rounds))
            return
        if not settings.plo_review_send_back:
            await _end(run, REASON_SEND_BACK_OFF)
            return
        if review.reviewed_by != "agent":
            if last_agent is not None:
                await _keep_last_agent_review(run, last_agent)
                await _end(run, REASON_REVIEWER_LATE)
            else:
                await _end(run, REASON_NO_AGENT)
            return
        last_agent = review
        # "Pass" is a fact about the review (nothing agreed to act on), read before
        # send-back changes the set, never inferred from the rows it wrote.
        work = await has_agreed_work(run.program_id, review, reviewed, mem)
        # `send_back` appends each row to `run.rows` as it writes it, so an abandoned
        # round still has them in the result. Called on a pass too: it records the
        # KSEC gaps that have no Need, the designer's comments.
        start = len(run.rows)
        await send_back(run.program_id, review, reviewed, round_no=i, memory=mem, sink=run.rows)
        rows = run.rows[start:]
        if not work:
            await _end(run, REASON_PASS)
            return
        if actionable_count(rows) == 0:
            # There was agreed work and no row says what came of it: send_back
            # stopped early (it logs why and never raises).
            await _end(run, REASON_SEND_BACK_FAILED)
            return
        if not any(r.outcome == "applied" for r in rows):
            await _end(run, REASON_NO_CHANGE)
            return


async def _apply(run: _Run, plos: Sequence[PLO]) -> None:
    seconds = settings.plo_review_loop_timeout_seconds
    try:
        async with asyncio.timeout(seconds) as scope:
            await _rounds(run, plos)
        return
    except Exception as exc:
        # A provider's own TimeoutError is an in-round failure, not the loop budget.
        expired = isinstance(exc, TimeoutError) and scope.expired()
        if run.review is None and not expired:
            raise  # the first review failed: the caller sees its error
        if expired:
            logger.warning(f"plo_review_loop: {run.program_id} out of time at round {run.round_no}")
        else:
            logger.warning(
                f"plo_review_loop: round {run.round_no} for {run.program_id} failed: {exc!r}"
            )
        await _final_review(run)
        if run.review is None:
            raise  # out of time before any review, and the final one failed too
        await _end(run, _reason_timeout(seconds) if expired else REASON_ERROR)


async def _final_review(run: _Run) -> None:
    """One last review of the stored set, stored, no send-back. Best effort: when
    it fails the last stored review stands."""
    try:
        await _review_live(run, None)
    except Exception as exc:
        logger.warning(f"plo_review_loop: final review for {run.program_id} failed: {exc!r}")


async def run_review_loop(
    program_id: str, plos: Sequence[PLO]
) -> tuple[PLOSetReview, list[FeedbackAction]]:
    """Run the review loop in the configured mode; return the last stored review and
    every trail row written by this call. Raises only when no review could be made
    at all (a read failure on the first review), as the single pass always did."""
    mode = settings.plo_review_loop_mode
    if mode == "off" or settings.plo_review_max_rounds == 0:
        return await plo_review._review_once_with_send_back(program_id, plos)

    run = _Run(program_id=program_id)
    if mode == "shadow":
        await _review_live(run, plos)
        assert run.review is not None
        run.round_no = 1
        try:
            await send_back(program_id, run.review, plos, round_no=1, dry_run=True, sink=run.rows)
        except Exception as exc:
            logger.warning(f"plo_review_loop: shadow send-back for {program_id} failed: {exc!r}")
        await _end(run, REASON_SHADOW)
    else:
        await _apply(run, plos)
    assert run.review is not None
    return run.review, run.rows
