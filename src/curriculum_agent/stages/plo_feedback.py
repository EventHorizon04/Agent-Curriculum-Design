"""Phase 4: send the QA review's agreed findings back as redrafts, with a trail.

Runs once, right after a fresh agent review is stored (`plo_review.fresh_review`).
Three finding kinds act, in this order: redundancies first (they change which
PLOs exist), then Bloom redrafts, then unused Needs (the ceiling is judged after
the merges freed slots).

- redundancy: one PLO drafted from the union of the named PLOs' Needs;
- Bloom with a suggested level that differs from the declared one: the PLO is
  redrafted from its own Needs with a note naming the level;
- unused Need with verdict `consider`: a PLO drafted from that one Need.

Every action goes through `redraft_from_needs`, so the designer's checks and
bounds apply unchanged; a refusal or failure is a `skipped` / `failed` trail row,
never an exception. KSEC findings stay advisory. See
docs/superpowers/specs/2026-11-03-four-agent-pipeline-phase4-design.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

from loguru import logger

from curriculum_agent.config import settings
from curriculum_agent.data.repositories import (
    PLOFeedbackRepository,
    PLORepository,
    ProgramRepository,
)
from curriculum_agent.models import (
    PLO,
    BloomFinding,
    FeedbackAction,
    PLOSetReview,
    ProgramMetadata,
    RedundancyFinding,
    UnusedNeedFinding,
)
from curriculum_agent.prompts.plo_feedback import build_bloom_redraft_note_th
from curriculum_agent.stages.need_dedup import MAX_GROUP_SIZE
from curriculum_agent.stages.plo_redraft import RedraftFailed, RedraftRefused, redraft_from_needs

REASON_DRAFT_FAILED = "ร่าง PLO ไม่สำเร็จ"
REASON_ALREADY_REPLACED = "PLO นี้ถูกแทนที่ไปแล้วในรอบนี้"
REASON_PLO_MISSING = "ไม่พบ PLO นี้ในชุดปัจจุบัน"
REASON_UNUSED_NOT_WRITABLE = "Need นี้ยังไม่มีประโยคหรืออยู่นอกขอบเขตหลักสูตร"
REASON_NEED_NOW_CITED = "Need นี้มี PLO อ้างถึงแล้วในรอบนี้"
REASON_GROUP_TOO_BIG = f"รวมแล้วเกิน {MAX_GROUP_SIZE} Need"


def _naive_utc(moment: datetime) -> datetime:
    """The DB columns are naive UTC; an aware value would fail the write."""
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None)
    return moment


class _Round:
    """One send-back round: whom it acts for and which PLOs it has replaced."""

    def __init__(self, program: ProgramMetadata, program_id: str, review: PLOSetReview) -> None:
        self.program = program
        self.program_id = program_id
        self.review_created_at = _naive_utc(review.created_at)
        self.replaced: set[str] = set()

    def skipped(
        self,
        kind: str,
        reason: str,
        *,
        plo_ids: list[str],
        need_ids: list[str],
        finding_reason_th: str,
        instruction_th: str = "",
    ) -> FeedbackAction:
        return FeedbackAction(
            program_id=self.program_id,
            review_created_at=self.review_created_at,
            kind=kind,
            plo_ids=plo_ids,
            need_ids=need_ids,
            finding_reason_th=finding_reason_th,
            instruction_th=instruction_th,
            outcome="skipped",
            outcome_reason_th=reason,
        )

    def failed(
        self,
        kind: str,
        *,
        plo_ids: list[str],
        need_ids: list[str],
        finding_reason_th: str,
        instruction_th: str = "",
    ) -> FeedbackAction:
        action = self.skipped(
            kind,
            REASON_DRAFT_FAILED,
            plo_ids=plo_ids,
            need_ids=need_ids,
            finding_reason_th=finding_reason_th,
            instruction_th=instruction_th,
        )
        action.outcome = "failed"
        return action

    async def redraft(
        self,
        kind: str,
        *,
        plo_ids: list[str],
        need_ids: list[str],
        finding_reason_th: str,
        instruction_th: str = "",
    ) -> FeedbackAction:
        """Run one redraft and turn whatever happens into a trail row."""
        try:
            plo, replaced = await redraft_from_needs(
                self.program,
                self.program_id,
                need_ids,
                note_th=instruction_th or None,
                cause="review",
            )
        except RedraftRefused as exc:
            return self.skipped(
                kind,
                exc.detail_th,
                plo_ids=plo_ids,
                need_ids=need_ids,
                finding_reason_th=finding_reason_th,
                instruction_th=instruction_th,
            )
        except RedraftFailed:
            return self.failed(
                kind,
                plo_ids=plo_ids,
                need_ids=need_ids,
                finding_reason_th=finding_reason_th,
                instruction_th=instruction_th,
            )
        self.replaced.update(replaced)
        return FeedbackAction(
            program_id=self.program_id,
            review_created_at=self.review_created_at,
            kind=kind,
            outcome="applied",
            result_plo_id=plo.plo_id,
            result_statement_th=plo.statement_th,
            result_bloom_level=plo.bloom_level.value,
            plo_ids=plo_ids,
            need_ids=need_ids,
            finding_reason_th=finding_reason_th,
            instruction_th=instruction_th,
        )

    def unavailable_reason(self, named: list[str], live: dict[str, PLO]) -> str | None:
        """Why the named PLOs cannot be acted on now, or None when all are live.

        Replaced is judged first: a freed id can be reused by the new outcome, so
        presence in the live set alone would not tell a replaced PLO from a live one.
        """
        if any(pid in self.replaced for pid in named):
            return REASON_ALREADY_REPLACED
        if any(pid not in live for pid in named):
            return REASON_PLO_MISSING
        return None


async def _live_plos(program_id: str) -> dict[str, PLO]:
    """Re-read before every action: the previous one changed the set."""
    return {p.plo_id: p for p in await PLORepository().list_by_program(program_id)}


async def _send_redundancy(rnd: _Round, finding: RedundancyFinding) -> FeedbackAction:
    named = list(dict.fromkeys(finding.plo_ids))
    live = await _live_plos(rnd.program_id)
    gone = rnd.unavailable_reason(named, live)
    if gone is not None:
        return rnd.skipped(
            "redundancy", gone, plo_ids=named, need_ids=[], finding_reason_th=finding.reason_th
        )
    need_ids = list(dict.fromkeys(nid for pid in named for nid in live[pid].source_need_ids))
    if len(need_ids) > MAX_GROUP_SIZE:
        return rnd.skipped(
            "redundancy",
            REASON_GROUP_TOO_BIG,
            plo_ids=named,
            need_ids=need_ids,
            finding_reason_th=finding.reason_th,
        )
    return await rnd.redraft(
        "redundancy", plo_ids=named, need_ids=need_ids, finding_reason_th=finding.reason_th
    )


def _actionable_bloom(finding: BloomFinding) -> bool:
    return finding.suggested_level is not None and finding.suggested_level != finding.declared


async def _send_bloom(rnd: _Round, finding: BloomFinding) -> FeedbackAction:
    suggested = finding.suggested_level
    assert suggested is not None  # _actionable_bloom
    live = await _live_plos(rnd.program_id)
    gone = rnd.unavailable_reason([finding.plo_id], live)
    if gone is not None:
        return rnd.skipped(
            "bloom",
            gone,
            plo_ids=[finding.plo_id],
            need_ids=[],
            finding_reason_th=finding.reason_th,
        )
    return await rnd.redraft(
        "bloom",
        plo_ids=[finding.plo_id],
        need_ids=list(live[finding.plo_id].source_need_ids),
        finding_reason_th=finding.reason_th,
        instruction_th=build_bloom_redraft_note_th(suggested, finding.reason_th),
    )


async def _send_unused(rnd: _Round, finding: UnusedNeedFinding) -> FeedbackAction:
    if finding.unwritten or finding.exclusion == "out_of_scope":
        return rnd.skipped(
            "unused_need",
            REASON_UNUSED_NOT_WRITABLE,
            plo_ids=[],
            need_ids=[finding.need_id],
            finding_reason_th=finding.reason_th,
        )
    live = await _live_plos(rnd.program_id)
    # Redrafting from a Need a PLO now cites would replace that PLO, undoing what
    # an earlier action of this round just wrote.
    if any(finding.need_id in p.source_need_ids for p in live.values()):
        return rnd.skipped(
            "unused_need",
            REASON_NEED_NOW_CITED,
            plo_ids=[],
            need_ids=[finding.need_id],
            finding_reason_th=finding.reason_th,
        )
    return await rnd.redraft(
        "unused_need",
        plo_ids=[],
        need_ids=[finding.need_id],
        finding_reason_th=finding.reason_th,
    )


async def send_back(program_id: str, review: PLOSetReview) -> list[FeedbackAction]:
    """Act on the review's agreed findings; return the trail rows written.

    `[]` without any read when the switch is off or the review is not the agent's.
    Never raises: an unexpected error in one action makes that action `failed`; one
    outside the actions is logged and what was recorded so far is returned.
    """
    if not settings.plo_review_send_back or review.reviewed_by != "agent":
        return []
    actions: list[FeedbackAction] = []
    try:
        program = await ProgramRepository().get(program_id)
        if program is None:
            logger.warning(f"plo_feedback: program {program_id} not found, nothing sent back")
            return []
        rnd = _Round(program, program_id, review)
        threshold = review.agreement_threshold

        reds = [r for r in review.redundancies if r.agreed_runs >= threshold]
        blooms = [b for b in review.bloom if b.agreed_runs >= threshold and _actionable_bloom(b)]
        unused = [
            u for u in review.unused_needs if u.agreed_runs >= threshold and u.verdict == "consider"
        ]

        for red in reds:
            try:
                action = await _send_redundancy(rnd, red)
            except Exception as exc:
                logger.warning(f"plo_feedback: redundancy {red.plo_ids} raised: {exc!r}")
                action = rnd.failed(
                    "redundancy",
                    plo_ids=list(red.plo_ids),
                    need_ids=[],
                    finding_reason_th=red.reason_th,
                )
            actions.append(action)
        for bl in blooms:
            try:
                action = await _send_bloom(rnd, bl)
            except Exception as exc:
                logger.warning(f"plo_feedback: bloom {bl.plo_id} raised: {exc!r}")
                action = rnd.failed(
                    "bloom", plo_ids=[bl.plo_id], need_ids=[], finding_reason_th=bl.reason_th
                )
            actions.append(action)
        for un in unused:
            try:
                action = await _send_unused(rnd, un)
            except Exception as exc:
                logger.warning(f"plo_feedback: unused Need {un.need_id} raised: {exc!r}")
                action = rnd.failed(
                    "unused_need",
                    plo_ids=[],
                    need_ids=[un.need_id],
                    finding_reason_th=un.reason_th,
                )
            actions.append(action)

        for action in actions:
            logger.info(
                f"plo_feedback: {action.kind} {action.plo_ids or action.need_ids} "
                f"-> {action.outcome} {action.outcome_reason_th}".rstrip()
            )
        await PLOFeedbackRepository().add(actions)
    except Exception as exc:
        logger.warning(f"plo_feedback: send-back for {program_id} stopped early: {exc!r}")
    return actions
