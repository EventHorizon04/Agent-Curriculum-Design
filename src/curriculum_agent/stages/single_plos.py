"""Single-agent mode, PLO half: approved Needs in, stored PLOs out.

The agent drafts PLOs from the Needs the designer approved and saves each with its
own soft verdict. Code does the rest: which Needs are offered (the same selection
`plo_synthesis` uses), the numbering, the evidence trail, and the last word on the
hard SMART criteria. `build_single_plo` runs `hard_failures` on the statement that
will ship, so `smart_escalated` is set by code whatever the agent claimed; the
soft verdicts are the agent's own, stored as flags and findings and never blocking.

Failure signalling is the Needs half's: `run_single_plos` raises
`fastapi.HTTPException`, which `api/jobs._run` turns into the job's Thai error.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from fastapi import HTTPException
from loguru import logger
from pydantic import BaseModel, ValidationError

from curriculum_agent.config import settings
from curriculum_agent.data.repositories import (
    EvidenceRepository,
    NeedRepository,
    PLORepository,
    ProgramRepository,
)
from curriculum_agent.models import (
    PLO,
    Need,
    ProgramMetadata,
    SMARTCheck,
    SmartFinding,
    StakeholderEvidence,
)
from curriculum_agent.prompts.single_agent import (
    build_one_plo_task,
    build_plos_task,
    build_refusal,
)
from curriculum_agent.smart_vocabulary import FINDING_LABEL_TH, SmartFindingCode
from curriculum_agent.stages.need_grouping import (
    MAX_CORE_PLOS,
    MIN_NEEDS,
    is_unwritten_need,
)
from curriculum_agent.stages.plo_synthesis import format_plo_id, select_slots, synthesis_order
from curriculum_agent.stages.single_agent_loop import (
    DropNeed,
    DropPLO,
    Note,
    OutputAction,
    SaveNeed,
    SavePLO,
    SoftVerdict,
    StopReason,
    run_single_agent,
)
from curriculum_agent.stages.single_agent_tools import SingleToolContext
from curriculum_agent.stages.single_needs import brief_of, program_context_for
from curriculum_agent.stages.smart_agent import hard_findings_for
from curriculum_agent.stages.smart_agent_tools import SiblingSummary
from curriculum_agent.stages.smart_rules import (
    CRITERION_FIX_HINTS_TH,
    HardCriterion,
    hard_failures,
    strip_outcome_prefix,
)

_NOT_A_NEED_STEP_TH = "ขั้นนี้เป็นขั้นเขียน PLO ไม่ใช่ขั้นเขียน Need"

# soft verdict field -> the finding code it reports under
_SOFT_CODES: tuple[tuple[str, SmartFindingCode], ...] = (
    ("specific_object_ok", SmartFindingCode.S_OBJECT),
    ("measurable_ok", SmartFindingCode.M_ASSESSABLE),
    ("achievable_ok", SmartFindingCode.A_LEVEL),
    ("actor_ok", SmartFindingCode.A_ACTOR),
    ("scope_ok", SmartFindingCode.A_SCOPE),
    ("relevant_needs_ok", SmartFindingCode.R_NEEDS),
    ("time_bound_ok", SmartFindingCode.T_HORIZON),
)


class SinglePlosResult(BaseModel):
    plos: list[PLO]
    stop_reason: StopReason
    turns: int
    dropped_evidence_count: int  # evidence texts the loop had to drop from context
    opened_evidence_ids: list[str]
    uncited_core_need_ids: list[str]  # core Needs no stored PLO answers


def select_single_input(needs: Sequence[Need]) -> tuple[list[Need], list[Need], list[Need]]:
    """(core, optional, lost the cut) from the stored Needs.

    Only active, written Needs are considered. The cut is `plo_synthesis`'s own: the
    10 highest-demand core Needs are used, the rest are named but not offered.
    """
    eligible = [
        n
        for n in needs
        if n.merged_into is None and n.excluded_at is None and not is_unwritten_need(n)
    ]
    slots = select_slots([[n] for n in synthesis_order(eligible)])
    core = [s.needs[0] for s in slots if not s.is_optional]
    optional = [s.needs[0] for s in slots if s.is_optional]
    chosen = {n.need_id for n in core}
    unused = [n for n in synthesis_order(eligible) if not n.is_optional and n.need_id not in chosen]
    return core, optional, unused


def _is_optional(cited: Sequence[Need]) -> bool:
    """Optional only when every cited Need is: a mixed PLO counts as core."""
    return all(n.is_optional for n in cited)


def build_single_plo(
    program_id: str,
    plo_id: str,
    draft: SavePLO,
    needs_by_id: Mapping[str, Need],
    *,
    is_optional: bool,
    designer_edited_at: datetime | None = None,
    version: int = 1,
) -> PLO:
    """One `PLO` from a draft. Pure; the hard check on the shipped statement decides escalation.

    The subject prefix ("บัณฑิตสามารถ...") is stripped like `plo_synthesis._adopt` does,
    except on a designer's own sentence, which is kept as written.
    """
    statement = (
        draft.statement_th
        if designer_edited_at is not None
        else strip_outcome_prefix(draft.statement_th)
    )
    cited = [needs_by_id[i] for i in draft.source_need_ids]
    fails = hard_failures(
        statement, draft.action_verb_th, list(draft.source_need_ids), set(needs_by_id)
    )
    soft: SoftVerdict = draft.soft
    verdicts = soft.model_dump()

    soft_findings: list[SmartFinding] = []
    for key, code in _SOFT_CODES:
        if verdicts[key]:
            continue
        note = (soft.findings_th.get(code.value) or "").strip() or FINDING_LABEL_TH[code]
        soft_findings.append(SmartFinding(criterion=code, severity="soft", note_th=note))

    smart_check = SMARTCheck(
        specific=HardCriterion.S_VERB not in fails
        and HardCriterion.S_MULTI_VERB not in fails
        and soft.specific_object_ok,
        measurable=HardCriterion.M_FORBIDDEN not in fails and soft.measurable_ok,
        achievable=soft.achievable_ok and soft.actor_ok and soft.scope_ok,
        relevant=HardCriterion.R_EVIDENCE not in fails and soft.relevant_needs_ok,
        timely=soft.time_bound_ok,
        findings=hard_findings_for(fails, [CRITERION_FIX_HINTS_TH[f] for f in fails])
        + soft_findings,
    )
    evidence_ids = sorted({e for n in cited for e in n.source_evidence_ids})
    return PLO(
        plo_id=plo_id,
        program_id=program_id,
        statement_th=statement,
        statement_en=draft.statement_en,
        bloom_level=draft.bloom_level,
        action_verb_th=draft.action_verb_th,
        smart_check=smart_check,
        source_need_ids=list(draft.source_need_ids),
        source_evidence_ids=evidence_ids,
        rationale_th=draft.rationale_th,
        version=version,
        smart_retry_count=0,
        smart_escalated=bool(fails),
        soft_flags=[f.criterion.value for f in soft_findings],
        smart_validated_by="single_agent",
        is_optional=is_optional,
        designer_edited_at=designer_edited_at,
    )


class PlosHandler:
    """Holds the PLO drafts and keeps the tool context current. Implements TaskHandler."""

    def __init__(
        self,
        program: ProgramMetadata,
        core: list[Need],
        optional: list[Need],
        unused: list[Need],
        evidence: list[StakeholderEvidence],
        note_th: str | None,
    ) -> None:
        self._program = program
        self._core = list(core)
        self._optional = list(optional)
        self._unused = list(unused)
        self._note_th = note_th
        self._usable = {n.need_id: n for n in (*core, *optional)}
        self._drafts: dict[str, SavePLO] = {}
        self._minted = 0
        briefs = {n.need_id: brief_of(n) for n in (*core, *optional, *unused)}
        self.tool_ctx = SingleToolContext(
            evidence_by_id={e.evidence_id: e for e in evidence},
            needs_by_id=briefs,
            plos=[],
            part_chars=settings.single_agent_evidence_part_chars,
        )

    def opening_message(self) -> str:
        return build_plos_task(
            program_context=program_context_for(self._program),
            scope_th=self._program.scope_th or None,
            core_needs=[brief_of(n) for n in self._core],
            optional_needs=[brief_of(n) for n in self._optional],
            unused_needs=[brief_of(n) for n in self._unused],
            note_th=self._note_th,
        )

    def note_for(self, evidence_id: str) -> str | None:
        return None

    def finish_refusal(self) -> str | None:
        return None

    def drafts(self) -> list[SavePLO]:
        return list(self._drafts.values())

    def handle(self, action: OutputAction) -> str:
        if isinstance(action, Note):
            return "รับโน้ตแล้ว"
        if isinstance(action, (SaveNeed, DropNeed)):
            return build_refusal(_NOT_A_NEED_STEP_TH)
        if isinstance(action, DropPLO):
            if action.plo_ref not in self._drafts:
                return build_refusal(f"ไม่พบ PLO รหัส {action.plo_ref}")
            del self._drafts[action.plo_ref]
            self._refresh_siblings()
            return f"ลบ PLO {action.plo_ref} แล้ว"
        if isinstance(action, SavePLO):
            return self._save(action)
        return build_refusal("ไม่รู้จักคำสั่งนี้")

    def _mint_ref(self) -> str:
        while True:
            self._minted += 1
            ref = f"d{self._minted}"
            if ref not in self._drafts:
                return ref

    def _save(self, action: SavePLO) -> str:
        unknown = [i for i in action.source_need_ids if i not in self._usable]
        if unknown:
            return build_refusal(
                f"Need {', '.join(unknown)} ไม่อยู่ในรายการที่ใช้เขียน PLO ในรอบนี้ "
                "(อ้างได้เฉพาะ Need หลักและ Need เสริมที่ข้อความแรกให้มา)"
            )
        if action.plo_ref is None:
            ref = self._mint_ref()
        elif action.plo_ref in self._drafts:
            ref = action.plo_ref
        else:
            return build_refusal(
                f"ไม่พบ PLO รหัส {action.plo_ref} ให้แก้ (ใช้ plo_ref: null เพื่อบันทึกข้อใหม่)"
            )
        taken = {i for r, d in self._drafts.items() if r != ref for i in d.source_need_ids}
        clash = [i for i in dict.fromkeys(action.source_need_ids) if i in taken]
        if clash:
            return build_refusal(f"Need {', '.join(clash)} อยู่เบื้องหลัง PLO อื่นแล้ว")
        draft = action.model_copy(
            update={"plo_ref": ref, "source_need_ids": list(dict.fromkeys(action.source_need_ids))}
        )
        cited = [self._usable[i] for i in draft.source_need_ids]
        try:
            built = build_single_plo(
                self._program.program_id,
                ref,
                draft,
                self._usable,
                is_optional=_is_optional(cited),
            )
        except ValidationError as exc:
            # A draft the PLO model rejects is refused; the earlier drafts stay.
            reason = "; ".join(str(e["msg"]) for e in exc.errors())
            return build_refusal(f"PLO นี้ไม่ผ่านการตรวจรูปแบบ: {reason}")
        self._drafts = {**self._drafts, ref: draft}
        self._refresh_siblings()
        # The built PLO already ran the hard check; read its findings, do not rerun it.
        hard = built.smart_check.hard_findings
        if hard:
            detail = "; ".join(f"{f.criterion.value}: {f.note_th}" for f in hard)
            checked = f"hard check ไม่ผ่าน {detail}"
        else:
            checked = "ผ่าน hard check"
        return f"บันทึก PLO แล้ว plo_ref: {ref} · {checked}"

    def _refresh_siblings(self) -> None:
        self.tool_ctx.plos = [
            SiblingSummary(
                plo_id=ref,
                statement_th=strip_outcome_prefix(d.statement_th),
                bloom_level=d.bloom_level,
                is_optional=_is_optional([self._usable[i] for i in d.source_need_ids]),
                source_need_ids=list(d.source_need_ids),
            )
            for ref, d in self._drafts.items()
        ]


def _number_drafts(
    drafts: Sequence[SavePLO], usable: Mapping[str, Need]
) -> list[tuple[str, SavePLO, bool]]:
    """(plo_id, draft, is_optional): PLO1.. and OPT1.. by the demand of each draft's top Need."""

    def top_key(draft: SavePLO) -> tuple[float, str]:
        top = synthesis_order([usable[i] for i in draft.source_need_ids])[0]
        return (-top.demand_score, top.need_id)

    out: list[tuple[str, SavePLO, bool]] = []
    for is_optional in (False, True):
        series = sorted(
            (
                d
                for d in drafts
                if _is_optional([usable[i] for i in d.source_need_ids]) is is_optional
            ),
            key=top_key,
        )
        out += [
            (format_plo_id(index, is_optional=is_optional), d, is_optional)
            for index, d in enumerate(series, start=1)
        ]
    return out


async def run_single_plos(program_id: str, *, note_th: str | None = None) -> SinglePlosResult:
    program = await ProgramRepository().get(program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="ไม่พบหลักสูตร")
    stored = await NeedRepository().list_active_by_program(program_id)
    core, optional, unused = select_single_input(stored)
    if not core and not optional:
        raise HTTPException(
            status_code=422,
            detail="ยังไม่มี Need ที่ใช้เขียน PLO ได้ กรุณาสร้างหรือกู้คืน Need ก่อน",
        )
    if unused:
        logger.warning(
            f"single plos: {len(unused)} Need(s) lost the {MAX_CORE_PLOS}-PLO cut: "
            f"{', '.join(n.need_id for n in unused)}"
        )
    evidence = await EvidenceRepository().list_by_program(program_id)

    handler = PlosHandler(program, core, optional, unused, evidence, note_th)
    outcome = await run_single_agent(handler)

    drafts = handler.drafts()
    if not drafts:
        # Nothing is replaced: a previous run's PLOs survive a run that wrote none.
        raise HTTPException(
            status_code=502, detail=f"ตัวแทนไม่ได้เขียน PLO เลย ({outcome.stop_reason})"
        )
    usable = {n.need_id: n for n in (*core, *optional)}
    plos = [
        build_single_plo(program_id, plo_id, d, usable, is_optional=is_optional)
        for plo_id, d, is_optional in _number_drafts(drafts, usable)
    ]

    core_count = sum(1 for p in plos if not p.is_optional)
    if not MIN_NEEDS <= core_count <= MAX_CORE_PLOS:
        logger.warning(
            f"single plos produced {core_count} core PLOs (policy is {MIN_NEEDS}-{MAX_CORE_PLOS}) "
            "— review at the checkpoint"
        )

    # One session, one commit: a failed insert must not leave the program without PLOs.
    removed = await PLORepository().replace_by_program(program_id, plos)
    if removed:
        logger.info(f"Replaced {removed} PLO row(s) from a previous run")

    cited = {i for p in plos for i in p.source_need_ids}
    return SinglePlosResult(
        plos=plos,
        stop_reason=outcome.stop_reason,
        turns=outcome.turns,
        dropped_evidence_count=outcome.dropped_evidence_count,
        opened_evidence_ids=outcome.opened_evidence_ids,
        uncited_core_need_ids=[n.need_id for n in core if n.need_id not in cited],
    )


_NOT_A_ONE_PLO_STEP_TH = "ขั้นนี้คือเขียนหรือประเมิน PLO หนึ่งข้อ: ใช้ save_plo หนึ่งครั้งเท่านั้น"


class OnePloHandler:
    """Holds the one PLO draft of a redraft or revalidate. Implements TaskHandler.

    Notes are accepted; exactly one save is expected and a later save replaces it.
    """

    def __init__(
        self,
        program: ProgramMetadata,
        needs: Sequence[Need],
        evidence: Sequence[StakeholderEvidence],
        siblings: Sequence[SiblingSummary],
        note_th: str | None,
        current: PLO | None,
    ) -> None:
        self._program = program
        self._needs = list(needs)
        self._note_th = note_th
        self._current = current
        self._needs_by_id = {n.need_id: n for n in needs}
        self.is_optional = current.is_optional if current else _is_optional(self._needs)
        self._notes: dict[str, str] = {}
        self._draft: SavePLO | None = None
        self.tool_ctx = SingleToolContext(
            evidence_by_id={e.evidence_id: e for e in evidence},
            needs_by_id={n.need_id: brief_of(n) for n in needs},
            plos=list(siblings),
            part_chars=settings.single_agent_evidence_part_chars,
        )

    @property
    def keep_wording(self) -> bool:
        return self._current is not None and self._current.designer_edited_at is not None

    def opening_message(self) -> str:
        return build_one_plo_task(
            program_context=program_context_for(self._program),
            scope_th=self._program.scope_th or None,
            needs=[brief_of(n) for n in self._needs],
            current_statement_th=self._current.statement_th if self._current else None,
            note_th=self._note_th,
            keep_wording=self.keep_wording,
        )

    def note_for(self, evidence_id: str) -> str | None:
        return self._notes.get(evidence_id)

    def finish_refusal(self) -> str | None:
        return None

    def draft(self) -> SavePLO | None:
        return self._draft

    def handle(self, action: OutputAction) -> str:
        if isinstance(action, Note):
            if action.evidence_id not in self.tool_ctx.evidence_by_id:
                return build_refusal(f"ไม่พบหลักฐานรหัส {action.evidence_id} ในหลักสูตรนี้")
            self._notes[action.evidence_id] = action.points_th
            return f"รับโน้ตของ {action.evidence_id} แล้ว"
        if isinstance(action, SavePLO):
            # The cited Needs are the ones this task was given, whatever the agent listed.
            draft = action.model_copy(update={"source_need_ids": list(self._needs_by_id)})
            try:
                built = build_single_plo(
                    self._program.program_id,
                    "draft",
                    draft,
                    self._needs_by_id,
                    is_optional=self.is_optional,
                )
            except ValidationError as exc:
                reason = "; ".join(str(e["msg"]) for e in exc.errors())
                return build_refusal(f"PLO นี้ไม่ผ่านการตรวจรูปแบบ: {reason}")
            self._draft = draft
            hard = built.smart_check.hard_findings
            if hard:
                detail = "; ".join(f"{f.criterion.value}: {f.note_th}" for f in hard)
                return f"บันทึก PLO แล้ว · hard check ไม่ผ่าน {detail}"
            return "บันทึก PLO แล้ว · ผ่าน hard check"
        return build_refusal(_NOT_A_ONE_PLO_STEP_TH)


async def draft_single_plo(
    program: ProgramMetadata,
    needs: Sequence[Need],
    evidence: Sequence[StakeholderEvidence],
    *,
    plo_id: str,
    known_need_ids: set[str],
    siblings: Sequence[SiblingSummary],
    note_th: str | None,
    current: PLO | None = None,
) -> PLO:
    """One PLO from `needs` through the single agent; 502 when none is saved.

    With `current` it is a revalidation: id, optional flag and edit marker are kept,
    and on a hand-edited PLO the designer's statement, verb and level are kept too —
    only the soft verdicts are the agent's. The hard check decides escalation either way.
    """
    unknown = [n.need_id for n in needs if n.need_id not in known_need_ids]
    if unknown:
        raise HTTPException(status_code=422, detail=f"ไม่พบ Need ที่ใช้งาน: {', '.join(unknown)}")
    handler = OnePloHandler(program, needs, evidence, siblings, note_th, current)
    outcome = await run_single_agent(
        handler,
        max_turns=settings.single_agent_oneshot_max_turns,
        timeout_seconds=settings.single_agent_oneshot_timeout_seconds,
    )
    draft = handler.draft()
    if draft is None:
        raise HTTPException(
            status_code=502, detail=f"ตัวแทนไม่ได้เขียน PLO ({outcome.stop_reason}) ลองใหม่อีกครั้ง"
        )
    edited_at = current.designer_edited_at if current else None
    if current is not None and edited_at is not None:
        draft = draft.model_copy(
            update={
                "statement_th": current.statement_th,
                "statement_en": current.statement_en,
                "action_verb_th": current.action_verb_th,
                "bloom_level": current.bloom_level,
                # The stored rationale, as the multi revalidate carries it.
                "rationale_th": current.rationale_th,
            }
        )
    plo = build_single_plo(
        program.program_id,
        current.plo_id if current else plo_id,
        draft,
        {n.need_id: n for n in needs},
        is_optional=handler.is_optional,
        designer_edited_at=edited_at,
        version=current.version if current else 1,
    )
    if current is not None and current.distinctive_feature_th is not None:
        # The agent's draft has no such field; a revalidation must not drop the stored one.
        plo = plo.model_copy(update={"distinctive_feature_th": current.distinctive_feature_th})
    return plo
