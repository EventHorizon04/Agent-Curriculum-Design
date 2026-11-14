"""Single-agent mode, Needs half: stored evidence in, stored Needs out.

The agent reads every evidence item through `get_evidence`, notes it, and saves
Need drafts that cite evidence ids. Code does the rest: a draft becomes a `Need`
with `origin="single"`, no skill rows, and every statistic (demand score, freq,
stakeholder types, classification, optional) derived from the evidence it cites
(`single_need_stats`). Nothing here asks the model to score anything.

Failure signalling: `run_single_needs` raises `fastapi.HTTPException`, the same
mechanism the multi routes use; `api/jobs._run` turns its `detail` into the job's
Thai `error_th`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import HTTPException
from loguru import logger
from pydantic import BaseModel, ValidationError

from curriculum_agent.config import settings
from curriculum_agent.data.repositories import (
    EvidenceRepository,
    NeedRepository,
    ProgramRepository,
)
from curriculum_agent.models import Need, ProgramMetadata, StakeholderEvidence
from curriculum_agent.prompts.program_context import build_program_context_th
from curriculum_agent.prompts.single_agent import (
    EvidenceIndexRow,
    NeedBrief,
    build_core_needs_short_refusal,
    build_merge_need_task,
    build_needs_task,
    build_refusal,
    build_requirement_uncited_refusal,
)
from curriculum_agent.stages.need_grouping import MIN_NEEDS
from curriculum_agent.stages.single_agent_loop import (
    DropNeed,
    Note,
    OutputAction,
    SaveNeed,
    StopReason,
    run_single_agent,
)
from curriculum_agent.stages.single_agent_tools import SingleToolContext, evidence_parts
from curriculum_agent.stages.single_need_stats import derive_need_stats, scoring_corpus_for
from curriculum_agent.stages.stakeholder_needs import classify_evidence_type

_NOT_A_PLO_STEP_TH = "ขั้นนี้ยังไม่ใช่ขั้นเขียน PLO"


class SingleNeedsResult(BaseModel):
    needs: list[Need]
    stop_reason: StopReason
    turns: int
    dropped_evidence_count: int
    unread_evidence_ids: list[str]  # not every part fetched with get_evidence
    uncited_evidence_ids: list[str]  # cited by no stored Need
    # The requirement items among them (institution, professional council): the
    # agent was refused one finish over these and kept them uncited anyway.
    uncited_requirement_evidence_ids: list[str] = []
    unnoted_evidence_ids: list[str]  # opened, no Note handed in


def program_context_for(program: ProgramMetadata) -> str:
    base = build_program_context_th(program.model_dump(mode="json")) or "หลักสูตร"
    # The prompt's level criterion asks about the programme's length.
    return f"{base} ระยะเวลาเรียน {program.duration_years} ปี"


class NeedsHandler:
    """Holds the Need drafts and keeps the tool context current. Implements TaskHandler."""

    def __init__(self, program: ProgramMetadata, evidence: list[StakeholderEvidence]) -> None:
        self._program = program
        self._evidence = list(evidence)
        self._type_by_evidence = {e.evidence_id: e.stakeholder_type for e in evidence}
        self._source_by_evidence = {e.evidence_id: e.source_name for e in evidence}
        self._drafts: dict[str, SaveNeed] = {}
        self._notes: dict[str, str] = {}
        self._requirement_refused = False
        self._core_refused = False
        self.tool_ctx = SingleToolContext(
            evidence_by_id={e.evidence_id: e for e in evidence},
            needs_by_id={},
            plos=[],
            part_chars=settings.single_agent_evidence_part_chars,
        )

    def opening_message(self) -> str:
        rows = [
            EvidenceIndexRow(
                evidence_id=e.evidence_id,
                stakeholder_type=e.stakeholder_type.value,
                source_name=e.source_name,
                classification=classify_evidence_type(e.stakeholder_type),
                total_chars=len(e.raw_text_th),
                parts=len(evidence_parts(e.raw_text_th, settings.single_agent_evidence_part_chars)),
            )
            for e in self._evidence
        ]
        return build_needs_task(
            program_context=program_context_for(self._program),
            scope_th=self._program.scope_th or None,
            evidence_index=rows,
        )

    def note_for(self, evidence_id: str) -> str | None:
        return self._notes.get(evidence_id)

    def uncited_requirement_ids(self) -> list[str]:
        """Requirement evidence (institution, professional council) no draft cites."""
        cited = {i for d in self._drafts.values() for i in d.source_evidence_ids}
        return [
            e.evidence_id
            for e in self._evidence
            if classify_evidence_type(e.stakeholder_type) == "requirement"
            and e.evidence_id not in cited
        ]

    def finish_refusal(self) -> str | None:
        """Refuse the first finish that leaves requirement evidence uncited; accept the next.

        Designer's decision of 2026-11-14: the first real run read the institution's
        vision and philosophy, cited neither, and so wrote no `requirement` Need.
        One refusal makes the agent look again; a second finish is accepted, because
        an item may name no graduate capability at all (pure institutional goals),
        and the agent is told to say so in its summary. Whatever stays uncited is in
        the job result either way (`uncited_requirement_evidence_ids`).

        The same once-only refusal applies when fewer than `MIN_NEEDS` core Needs
        exist (designer's decision of 2026-11-14, after two of three lock runs
        wrote one-item Needs that code marked optional). Each gate speaks once;
        when both hold at the same finish they share one refusal.
        """
        parts: list[str] = []
        uncited = self.uncited_requirement_ids()
        if uncited and not self._requirement_refused:
            self._requirement_refused = True
            parts.append(
                build_requirement_uncited_refusal(
                    [(i, self._source_by_evidence[i]) for i in uncited]
                )
            )
        if not self._core_refused:
            short = self._core_short_refusal()
            if short is not None:
                self._core_refused = True
                parts.append(short)
        return "\n\n".join(parts) or None

    def _core_short_refusal(self) -> str | None:
        drafts = self.drafts()
        needs = build_single_needs(self._program.program_id, drafts, self._evidence)
        core = sum(1 for n in needs if not n.is_optional)
        if core >= MIN_NEEDS:
            return None
        cited = {i for d in drafts for i in d.source_evidence_ids}
        return build_core_needs_short_refusal(
            core,
            MIN_NEEDS,
            [
                (n.need_id, n.statement_th, n.source_evidence_ids[0])
                for n in needs
                if len(n.source_evidence_ids) == 1
            ],
            [(e.evidence_id, e.source_name) for e in self._evidence if e.evidence_id not in cited],
        )

    def drafts(self) -> list[SaveNeed]:
        return list(self._drafts.values())

    def noted_evidence_ids(self) -> set[str]:
        return set(self._notes)

    def fully_read_evidence_ids(self) -> set[str]:
        """Items whose every part was fetched; one part of a long item is not a read."""
        read = self.tool_ctx.read_parts
        return {
            e.evidence_id
            for e in self._evidence
            if all(
                (e.evidence_id, part) in read
                for part in range(
                    1, len(evidence_parts(e.raw_text_th, self.tool_ctx.part_chars)) + 1
                )
            )
        }

    def handle(self, action: OutputAction) -> str:
        if isinstance(action, Note):
            if action.evidence_id not in self._type_by_evidence:
                return build_refusal(f"ไม่พบหลักฐานรหัส {action.evidence_id} ในหลักสูตรนี้")
            self._notes[action.evidence_id] = action.points_th
            return f"รับโน้ตของ {action.evidence_id} แล้ว"
        if isinstance(action, SaveNeed):
            return self._save(action)
        if isinstance(action, DropNeed):
            if action.need_id not in self._drafts:
                return build_refusal(f"ไม่พบ Need รหัส {action.need_id}")
            del self._drafts[action.need_id]
            self._refresh_briefs()
            return f"ลบ Need {action.need_id} แล้ว"
        return build_refusal(_NOT_A_PLO_STEP_TH)

    def _save(self, action: SaveNeed) -> str:
        unknown = [i for i in action.source_evidence_ids if i not in self._type_by_evidence]
        if unknown:
            return build_refusal(f"ไม่พบหลักฐานรหัส {', '.join(unknown)} ในหลักสูตรนี้")
        if action.need_id is None:
            need_id = str(uuid.uuid4())
        elif action.need_id in self._drafts:
            need_id = action.need_id
        else:
            return build_refusal(
                f"ไม่พบ Need รหัส {action.need_id} ให้แก้ (ใช้ need_id: null เพื่อบันทึกข้อใหม่)"
            )
        draft = action.model_copy(update={"need_id": need_id})
        candidate = {**self._drafts, need_id: draft}
        try:
            briefs = self._briefs_for(list(candidate.values()))
        except ValidationError as exc:
            # A draft the Need model rejects is refused; the earlier drafts stay.
            reason = "; ".join(str(e["msg"]) for e in exc.errors())
            return build_refusal(f"Need นี้ไม่ผ่านการตรวจรูปแบบ: {reason}")
        self._drafts = candidate
        self.tool_ctx.needs_by_id = briefs
        return f"บันทึก Need แล้ว need_id: {need_id}"

    def _refresh_briefs(self) -> None:
        self.tool_ctx.needs_by_id = self._briefs_for(self.drafts())

    def _briefs_for(self, drafts: list[SaveNeed]) -> dict[str, NeedBrief]:
        """Briefs for these drafts: the corpus is all of them, so one save moves every score."""
        built = build_single_needs(self._program.program_id, drafts, self._evidence)
        return {n.need_id: brief_of(n) for n in built}


def build_single_needs(
    program_id: str, drafts: Sequence[SaveNeed], evidence: Sequence[StakeholderEvidence]
) -> list[Need]:
    """One `Need` per draft; statistics come from the evidence each one cites."""
    type_by_evidence = {e.evidence_id: e.stakeholder_type for e in evidence}
    corpus = scoring_corpus_for(
        (i for d in drafts for i in d.source_evidence_ids), type_by_evidence
    )
    needs: list[Need] = []
    for draft in drafts:
        ids = list(dict.fromkeys(draft.source_evidence_ids))
        stats = derive_need_stats(ids, type_by_evidence, corpus)
        needs.append(
            Need(
                need_id=draft.need_id or str(uuid.uuid4()),
                program_id=program_id,
                statement_th=draft.statement_th,
                rationale_th=draft.rationale_th,
                ksec_categories=draft.ksec_categories,
                bloom_level=draft.bloom_level,
                member_skill_ids=[],
                top_skill_ids=[],
                source_evidence_ids=ids,
                stakeholder_coverage=stats.stakeholder_coverage,
                source_stakeholder_types=stats.source_stakeholder_types,
                freq=stats.freq,
                demand_score=stats.demand_score,
                is_optional=stats.is_optional,
                classification_coverage=stats.classification_coverage,
                in_field_skill_count=0,
                graduate_capability_skill_count=0,
                origin="single",
            )
        )
    return needs


async def run_single_needs(program_id: str) -> SingleNeedsResult:
    program = await ProgramRepository().get(program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="ไม่พบหลักสูตร")
    evidence = await EvidenceRepository().list_by_program(program_id)
    if not evidence:
        raise HTTPException(
            status_code=422,
            detail="ยังไม่มีหลักฐานผู้มีส่วนได้ส่วนเสีย กรุณาเพิ่มหลักฐานก่อนสร้าง Need",
        )

    handler = NeedsHandler(program, evidence)
    outcome = await run_single_agent(handler)

    drafts = handler.drafts()
    if not drafts:
        # Nothing is replaced: a previous run's Needs survive a run that wrote none.
        raise HTTPException(
            status_code=502, detail=f"ตัวแทนไม่ได้เขียน Need เลย ({outcome.stop_reason})"
        )
    needs = build_single_needs(program_id, drafts, evidence)

    core = sum(1 for n in needs if not n.is_optional)
    if core < MIN_NEEDS:
        logger.warning(
            f"single needs produced only {core} non-optional Needs (policy is at least "
            f"{MIN_NEEDS}) — the designer must add more at the review checkpoint"
        )
    await NeedRepository().replace_by_program(program_id, needs)

    all_ids = [e.evidence_id for e in evidence]
    opened = set(outcome.opened_evidence_ids)
    fully_read = handler.fully_read_evidence_ids()
    cited = {i for n in needs for i in n.source_evidence_ids}
    noted = handler.noted_evidence_ids()
    return SingleNeedsResult(
        needs=needs,
        stop_reason=outcome.stop_reason,
        turns=outcome.turns,
        dropped_evidence_count=outcome.dropped_evidence_count,
        unread_evidence_ids=[i for i in all_ids if i not in fully_read],
        uncited_evidence_ids=[i for i in all_ids if i not in cited],
        uncited_requirement_evidence_ids=handler.uncited_requirement_ids(),
        unnoted_evidence_ids=[i for i in all_ids if i in opened and i not in noted],
    )


_NOT_A_MERGE_STEP_TH = "ขั้นนี้คือรวม Need: ใช้ save_need หนึ่งครั้งเท่านั้น"


def _merged_need(
    program_id: str,
    draft: SaveNeed,
    originals: Sequence[Need],
    all_active: Sequence[Need],
    evidence: Sequence[StakeholderEvidence],
    *,
    reason_th: str | None,
) -> Need:
    """The merged Need: wording from the agent, trail and statistics from code.

    The agent's tags and evidence list are ignored; the tags are the originals' union
    and the evidence is theirs combined, so the merge cannot gain or lose a citation.
    """
    type_by_evidence = {e.evidence_id: e.stakeholder_type for e in evidence}
    ids = list(dict.fromkeys(i for n in originals for i in n.source_evidence_ids))
    original_ids = {n.need_id for n in originals}
    corpus = scoring_corpus_for(
        [i for n in all_active if n.need_id not in original_ids for i in n.source_evidence_ids]
        + ids,
        type_by_evidence,
    )
    stats = derive_need_stats(ids, type_by_evidence, corpus)
    return Need(
        need_id=str(uuid.uuid4()),
        program_id=program_id,
        statement_th=draft.statement_th,
        rationale_th=draft.rationale_th,
        ksec_categories=[c for n in originals for c in n.ksec_categories],  # model sorts/dedupes
        bloom_level=draft.bloom_level,
        member_skill_ids=[],
        top_skill_ids=[],
        source_evidence_ids=ids,
        stakeholder_coverage=stats.stakeholder_coverage,
        source_stakeholder_types=stats.source_stakeholder_types,
        freq=stats.freq,
        demand_score=stats.demand_score,
        is_optional=stats.is_optional,
        classification_coverage=stats.classification_coverage,
        in_field_skill_count=0,
        graduate_capability_skill_count=0,
        origin="single",
        merged_from=[n.need_id for n in originals],
        merged_by="designer",
        merge_reason_th=reason_th or "",
    )


class MergeNeedHandler:
    """Holds the one merged-Need draft. Implements TaskHandler.

    Notes are accepted (the system prompt asks for one after every evidence read);
    exactly one save is expected and a later save replaces it.
    """

    def __init__(
        self,
        program: ProgramMetadata,
        originals: Sequence[Need],
        all_active: Sequence[Need],
        evidence: Sequence[StakeholderEvidence],
        reason_th: str | None,
    ) -> None:
        self._program = program
        self._originals = list(originals)
        self._all_active = list(all_active)
        self._all_evidence = list(evidence)
        self._reason_th = reason_th
        wanted = {i for n in originals for i in n.source_evidence_ids}
        self._evidence = [e for e in evidence if e.evidence_id in wanted]
        self._notes: dict[str, str] = {}
        self._draft: SaveNeed | None = None
        self.tool_ctx = SingleToolContext(
            evidence_by_id={e.evidence_id: e for e in self._evidence},
            needs_by_id={n.need_id: brief_of(n) for n in originals},
            plos=[],
            part_chars=settings.single_agent_evidence_part_chars,
        )

    def opening_message(self) -> str:
        return build_merge_need_task(
            program_context=program_context_for(self._program),
            needs=[brief_of(n) for n in self._originals],
            reason_th=self._reason_th,
        )

    def note_for(self, evidence_id: str) -> str | None:
        return self._notes.get(evidence_id)

    def finish_refusal(self) -> str | None:
        return None

    def draft(self) -> SaveNeed | None:
        return self._draft

    def handle(self, action: OutputAction) -> str:
        if isinstance(action, Note):
            if action.evidence_id not in self.tool_ctx.evidence_by_id:
                return build_refusal(f"ไม่พบหลักฐานรหัส {action.evidence_id} ใน Need ที่เลือก")
            self._notes[action.evidence_id] = action.points_th
            return f"รับโน้ตของ {action.evidence_id} แล้ว"
        if isinstance(action, SaveNeed):
            try:
                _merged_need(
                    self._program.program_id,
                    action,
                    self._originals,
                    self._all_active,
                    self._all_evidence,
                    reason_th=self._reason_th,
                )
            except ValidationError as exc:
                reason = "; ".join(str(e["msg"]) for e in exc.errors())
                return build_refusal(f"Need นี้ไม่ผ่านการตรวจรูปแบบ: {reason}")
            self._draft = action
            return "บันทึก Need ที่รวมแล้ว"
        return build_refusal(_NOT_A_MERGE_STEP_TH)


def brief_of(need: Need) -> NeedBrief:
    """The one Need-to-NeedBrief mapping every single-agent task uses."""
    return NeedBrief(
        need_id=need.need_id,
        statement_th=need.statement_th,
        ksec_categories=tuple(str(getattr(c, "value", c)) for c in need.ksec_categories),
        bloom_level=str(getattr(need.bloom_level, "value", need.bloom_level)),
        demand_score=need.demand_score,
        stakeholder_types=tuple(t.value for t in need.source_stakeholder_types),
        evidence_ids=tuple(need.source_evidence_ids),
    )


async def merge_single_needs(
    program: ProgramMetadata,
    originals: Sequence[Need],
    all_active: Sequence[Need],
    evidence: Sequence[StakeholderEvidence],
    *,
    reason_th: str | None,
) -> Need:
    """Write one Need in place of `originals` through the single agent; 502 when none is saved."""
    handler = MergeNeedHandler(program, originals, all_active, evidence, reason_th)
    outcome = await run_single_agent(
        handler,
        max_turns=settings.single_agent_oneshot_max_turns,
        timeout_seconds=settings.single_agent_oneshot_timeout_seconds,
    )
    draft = handler.draft()
    if draft is None:
        raise HTTPException(
            status_code=502,
            detail=f"ตัวแทนไม่ได้เขียน Need ที่รวมแล้ว ({outcome.stop_reason}) ลองใหม่อีกครั้ง",
        )
    return _merged_need(
        program.program_id, draft, originals, all_active, evidence, reason_th=reason_th
    )
