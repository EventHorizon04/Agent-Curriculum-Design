"""Phase 4: send the QA review's agreed findings back as redrafts, with a trail.

Runs right after a fresh agent review is stored (`plo_review.fresh_review`).
Five finding kinds act, in this order: redundancies first (they change which
PLOs exist), then alignment, Bloom/verb, KSEC gaps, and last unused Needs (the
ceiling is judged after the merges freed slots).

- redundancy: one PLO drafted from the union of the named PLOs' Needs;
- alignment: the PLO is redrafted from its own Needs with the reviewer's advice;
- Bloom (a level that differs from the declared one, or a suggested verb): the PLO
  is redrafted from its own Needs with a note naming the level and/or the verb;
- KSEC gap: for each category the set has no PLO in (a code fact, no vote), a PLO
  drafted from the best Need of that category nothing cites yet;
- unused Need with verdict `consider`: a PLO drafted from that one Need.

Every note carries the review's full advice and the old draft (masked of forbidden
words), see `prompts/plo_feedback.py`. `dry_run` runs every check and records what
would be done as `planned` rows without writing anything.

Every action goes through `redraft_from_needs`, so the designer's checks and
bounds apply unchanged; a refusal or failure is a `skipped` / `failed` trail row,
never an exception. KSEC findings stay advisory. See
docs/superpowers/specs/2026-11-03-four-agent-pipeline-phase4-design.md.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from loguru import logger

from curriculum_agent.config import settings
from curriculum_agent.data.repositories import (
    NeedRepository,
    PLOFeedbackRepository,
    PLORepository,
    ProgramRepository,
)
from curriculum_agent.models import (
    PLO,
    AlignmentFinding,
    BloomFinding,
    BloomLevel,
    FeedbackAction,
    PLOSetReview,
    ProgramMetadata,
    RedundancyFinding,
    UnusedNeedFinding,
)
from curriculum_agent.prompts.plo_feedback import (
    build_alignment_redraft_note_th,
    build_bloom_redraft_note_th,
    build_ksec_gap_note_th,
    build_redundancy_redraft_note_th,
    build_unused_redraft_note_th,
)
from curriculum_agent.stages.need_dedup import MAX_GROUP_SIZE
from curriculum_agent.stages.need_grouping import is_unwritten_need
from curriculum_agent.stages.plo_redraft import RedraftFailed, RedraftRefused, redraft_from_needs
from curriculum_agent.stages.plo_review_facts import exclusion_reason
from curriculum_agent.stages.plo_synthesis import plos_citing

REASON_DRAFT_FAILED = "ร่าง PLO ไม่สำเร็จ"
REASON_ALREADY_REPLACED = "PLO นี้ถูกแทนที่ไปแล้วในรอบนี้"
REASON_PLO_MISSING = "ไม่พบ PLO นี้ในชุดปัจจุบัน"
REASON_UNUSED_NOT_WRITABLE = "Need นี้ยังไม่มีประโยคหรืออยู่นอกขอบเขตหลักสูตร"
REASON_NEED_NOW_CITED = "Need นี้มี PLO อ้างถึงแล้วในรอบนี้"
REASON_GROUP_TOO_BIG = f"รวมแล้วเกิน {MAX_GROUP_SIZE} Need"
REASON_EDITED_SINCE_REVIEW = "PLO นี้ถูกแก้หลังการตรวจ — ไม่ส่งกลับ"
REASON_DESIGNER_EDITED = "PLO นี้ผู้ออกแบบแก้เอง — ไม่เขียนทับ"
REASON_DRAFT_ESCALATED = "ร่างใหม่ไม่ผ่าน SMART — คงข้อเดิมไว้"
REASON_DRAFT_WRONG_LEVEL = "ร่างใหม่ไม่ได้ระดับ Bloom ที่ขอ — คงข้อเดิมไว้"
REASON_KSEC_NO_NEED = "ไม่มี Need หมวดนี้ — ต้องเพิ่มที่ขั้น Need"
REASON_MERGED_EARLIER = "PLO นี้เพิ่งรวมมาในรอบก่อน"


@dataclass
class LoopMemory:
    """What the send-back loop carries between rounds.

    `merged` is the `(plo_id, statement_th)` of every PLO an applied redundancy
    wrote in an earlier round: a later review that names one of them again is
    judging the fruit of our own merge, and merging it again only drifts (decision
    13). The statement is part of the key because a freed id is reused.
    """

    merged: set[tuple[str, str]] = field(default_factory=set)


def _naive_utc(moment: datetime) -> datetime:
    """The DB columns are naive UTC; an aware value would fail the write."""
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None)
    return moment


class _Round:
    """One send-back round: whom it acts for and which PLOs it has replaced."""

    def __init__(
        self,
        program: ProgramMetadata,
        program_id: str,
        review: PLOSetReview,
        reviewed: Sequence[PLO],
        *,
        round_no: int = 0,
        dry_run: bool = False,
        memory: LoopMemory | None = None,
    ) -> None:
        self.program = program
        self.round_no = round_no
        self.dry_run = dry_run
        self.memory = memory if memory is not None else LoopMemory()
        # Needs a dry run has planned a draft for: nothing is written, so the live
        # set cannot tell a later action that the Need is taken.
        self.planned_needs: set[str] = set()
        self.reviewed = {p.plo_id: p for p in reviewed}
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
            round=self.round_no,
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
        accept: Callable[[PLO], str | None] | None = None,
    ) -> FeedbackAction:
        """Run one redraft and turn whatever happens into a trail row."""
        if self.dry_run:
            self.planned_needs.update(need_ids)
            return FeedbackAction(
                program_id=self.program_id,
                review_created_at=self.review_created_at,
                kind=kind,
                outcome="planned",
                plo_ids=plo_ids,
                need_ids=need_ids,
                finding_reason_th=finding_reason_th,
                instruction_th=instruction_th,
                round=self.round_no,
            )
        try:
            plo, replaced = await redraft_from_needs(
                self.program,
                self.program_id,
                need_ids,
                note_th=instruction_th or None,
                cause="review",
                accept=accept,
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
            round=self.round_no,
        )

    def unavailable_reason(self, named: list[str], live: dict[str, PLO]) -> str | None:
        """Why the named PLOs cannot be acted on now, or None when all are live.

        Order: replaced this round, edited since the review, designer-edited, then
        missing. Replaced
        is judged first: a freed id can be reused by the new outcome, so
        presence in the live set alone would not tell a replaced PLO from a live one.
        """
        if any(pid in self.replaced for pid in named):
            return REASON_ALREADY_REPLACED
        if any(self._edited_since_review(pid, live) for pid in named):
            return REASON_EDITED_SINCE_REVIEW
        if any(pid in live and live[pid].designer_edited_at is not None for pid in named):
            return REASON_DESIGNER_EDITED
        if any(pid not in live for pid in named):
            return REASON_PLO_MISSING
        return None

    def _edited_since_review(self, pid: str, live: dict[str, PLO]) -> bool:
        """A live PLO that is not the one the review judged: someone changed it
        (or a hand edit renumbered it) while the review ran. The review's verdict
        was about the old text, so it must not be acted on."""
        now = live.get(pid)
        if now is None:
            return False
        before = self.reviewed.get(pid)
        return (
            before is None
            or before.statement_th != now.statement_th
            or before.source_need_ids != now.source_need_ids
        )


def _keep_original_unless_better(
    live: dict[str, PLO], need_ids: list[str], level: BloomLevel | None
) -> Callable[[PLO], str | None]:
    """The agent's redraft must not make an approved outcome worse.

    A draft that failed SMART replaces only outcomes that already failed it (a
    Need nothing cites yet replaces nothing, so it is refused too); for a Bloom
    action the draft must also land on the level the review asked for.
    """
    replaced = plos_citing(live.values(), need_ids)

    def accept(draft: PLO) -> str | None:
        if draft.smart_escalated and not (replaced and all(p.smart_escalated for p in replaced)):
            return REASON_DRAFT_ESCALATED
        if level is not None and draft.bloom_level != level:
            return REASON_DRAFT_WRONG_LEVEL
        return None

    return accept


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
    if any((pid, live[pid].statement_th) in rnd.memory.merged for pid in named):
        return rnd.skipped(
            "redundancy",
            REASON_MERGED_EARLIER,
            plo_ids=named,
            need_ids=[],
            finding_reason_th=finding.reason_th,
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
    action = await rnd.redraft(
        "redundancy",
        plo_ids=named,
        need_ids=need_ids,
        finding_reason_th=finding.reason_th,
        instruction_th=build_redundancy_redraft_note_th(
            finding.reason_th, finding.suggestion_th, [live[pid].statement_th for pid in named]
        ),
        accept=_keep_original_unless_better(live, need_ids, None),
    )
    if (
        not rnd.dry_run
        and action.outcome == "applied"
        and action.result_plo_id
        and action.result_statement_th
    ):
        rnd.memory.merged.add((action.result_plo_id, action.result_statement_th))
    return action


async def _send_alignment(rnd: _Round, finding: AlignmentFinding) -> FeedbackAction:
    live = await _live_plos(rnd.program_id)
    gone = rnd.unavailable_reason([finding.plo_id], live)
    if gone is not None:
        return rnd.skipped(
            "alignment",
            gone,
            plo_ids=[finding.plo_id],
            need_ids=[],
            finding_reason_th=finding.reason_th,
        )
    plo = live[finding.plo_id]
    need_ids = list(plo.source_need_ids)
    return await rnd.redraft(
        "alignment",
        plo_ids=[finding.plo_id],
        need_ids=need_ids,
        finding_reason_th=finding.reason_th,
        instruction_th=build_alignment_redraft_note_th(
            finding.reason_th, finding.suggestion_th, plo.statement_th
        ),
        accept=_keep_original_unless_better(live, need_ids, None),
    )


def _level_change(finding: BloomFinding) -> BloomLevel | None:
    """The level the review wants, or None when it names no change. A verb-only
    finding votes for the declared level in consensus, which is "no change"."""
    suggested = finding.suggested_level
    return suggested if suggested is not None and suggested != finding.declared else None


def _actionable_bloom(finding: BloomFinding) -> bool:
    return _level_change(finding) is not None or bool((finding.suggested_verb_th or "").strip())


async def _send_bloom(rnd: _Round, finding: BloomFinding) -> FeedbackAction:
    suggested = _level_change(finding)
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
        instruction_th=build_bloom_redraft_note_th(
            suggested,
            finding.reason_th,
            suggested_verb_th=finding.suggested_verb_th,
            suggestion_th=finding.suggestion_th,
            old_statement_th=live[finding.plo_id].statement_th,
        ),
        accept=_keep_original_unless_better(
            live, list(live[finding.plo_id].source_need_ids), suggested
        ),
    )


async def _send_ksec_gap(rnd: _Round, category: str) -> FeedbackAction:
    """Fill a category the set has no PLO in, from the best Need nothing cites.

    No vote: `missing` is computed in code. A Need that is unwritten or out of
    scope is not a candidate, the same filter synthesis applies."""
    live = await _live_plos(rnd.program_id)
    cited = {nid for p in live.values() for nid in p.source_need_ids}
    candidates = [
        n
        for n in await NeedRepository().list_active_by_program(rnd.program_id)
        if category in n.ksec_categories
        and n.need_id not in cited
        and n.need_id not in rnd.planned_needs
        and not is_unwritten_need(n)
        and exclusion_reason(n) != "out_of_scope"
    ]
    reason = f"ไม่มี PLO หมวด {category}"
    if not candidates:
        return rnd.skipped(
            "ksec_gap", REASON_KSEC_NO_NEED, plo_ids=[], need_ids=[], finding_reason_th=reason
        )
    best = max(candidates, key=lambda n: n.demand_score)
    return await rnd.redraft(
        "ksec_gap",
        plo_ids=[],
        need_ids=[best.need_id],
        finding_reason_th=reason,
        instruction_th=build_ksec_gap_note_th(category),
        accept=_keep_original_unless_better(live, [best.need_id], None),
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
    # An unused Need's draft replaces whatever cites it; a hand-written outcome stays.
    if any(p.designer_edited_at is not None for p in plos_citing(live.values(), [finding.need_id])):
        return rnd.skipped(
            "unused_need",
            REASON_DESIGNER_EDITED,
            plo_ids=[],
            need_ids=[finding.need_id],
            finding_reason_th=finding.reason_th,
        )
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
        instruction_th=build_unused_redraft_note_th(finding.reason_th),
        accept=_keep_original_unless_better(live, [finding.need_id], None),
    )


async def _record(actions: list[FeedbackAction], action: FeedbackAction) -> None:
    """Keep the row and write it now, so an applied redraft is never left without
    its trail row if the round is cancelled later. A failed write is logged at
    error level with the row, and the round goes on."""
    actions.append(action)
    logger.info(
        f"plo_feedback: {action.kind} {action.plo_ids or action.need_ids} "
        f"-> {action.outcome} {action.outcome_reason_th}".rstrip()
    )
    try:
        await PLOFeedbackRepository().add([action])
    except Exception as exc:
        logger.error(f"plo_feedback: could not write trail row {action.model_dump_json()}: {exc!r}")


def actionable_count(actions: Sequence[FeedbackAction]) -> int:
    """Rows that show the round had something to do: applied, failed or planned, or
    skipped for a reason other than "no Need for this KSEC category" (a comment,
    nothing the loop can act on). The loop stops when this is 0."""
    return sum(
        1
        for a in actions
        if a.outcome in ("applied", "failed", "planned")
        or (a.outcome == "skipped" and a.outcome_reason_th != REASON_KSEC_NO_NEED)
    )


async def send_back(
    program_id: str,
    review: PLOSetReview,
    reviewed_plos: Sequence[PLO],
    *,
    round_no: int = 0,
    dry_run: bool = False,
    memory: LoopMemory | None = None,
) -> list[FeedbackAction]:
    """Act on the review's agreed findings; return the trail rows written.

    `reviewed_plos` is the set the review judged; a PLO changed since is not acted on.
    A finding counts only with a majority of the runs *asked for*, so one run of
    five that happened to succeed is never enough.

    `dry_run` records every action as `planned` and writes nothing, and leaves
    `memory` (the loop's) untouched. Every row carries `round_no`.

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
        # A dry run reads the loop's memory but must not teach it about merges that
        # never happened, so it works on a copy.
        use_memory = LoopMemory(merged=set(memory.merged)) if dry_run and memory else memory
        rnd = _Round(
            program,
            program_id,
            review,
            reviewed_plos,
            round_no=round_no,
            dry_run=dry_run,
            memory=use_memory,
        )
        threshold = max(review.agreement_threshold, review.runs_requested // 2 + 1)

        reds = [r for r in review.redundancies if r.agreed_runs >= threshold]
        aligns = [a for a in review.alignment if a.agreed_runs >= threshold]
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
            await _record(actions, action)
        for al in aligns:
            try:
                action = await _send_alignment(rnd, al)
            except Exception as exc:
                logger.warning(f"plo_feedback: alignment {al.plo_id} raised: {exc!r}")
                action = rnd.failed(
                    "alignment", plo_ids=[al.plo_id], need_ids=[], finding_reason_th=al.reason_th
                )
            await _record(actions, action)
        for bl in blooms:
            try:
                action = await _send_bloom(rnd, bl)
            except Exception as exc:
                logger.warning(f"plo_feedback: bloom {bl.plo_id} raised: {exc!r}")
                action = rnd.failed(
                    "bloom", plo_ids=[bl.plo_id], need_ids=[], finding_reason_th=bl.reason_th
                )
            await _record(actions, action)
        for category in review.ksec_coverage.missing:
            try:
                action = await _send_ksec_gap(rnd, category)
            except Exception as exc:
                logger.warning(f"plo_feedback: KSEC gap {category} raised: {exc!r}")
                action = rnd.failed(
                    "ksec_gap",
                    plo_ids=[],
                    need_ids=[],
                    finding_reason_th=f"ไม่มี PLO หมวด {category}",
                )
            await _record(actions, action)
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
            await _record(actions, action)
    except Exception as exc:
        logger.warning(f"plo_feedback: send-back for {program_id} stopped early: {exc!r}")
    return actions
