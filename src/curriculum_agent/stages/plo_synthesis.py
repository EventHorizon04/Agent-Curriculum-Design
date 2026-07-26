from __future__ import annotations

import uuid

from loguru import logger
from pydantic import BaseModel, Field, model_validator

from curriculum_agent.data.repositories import PLORepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_heavy, complete_light
from curriculum_agent.models import (
    PLO,
    BloomLevel,
    KSECCategory,
    Need,
    ProgramMetadata,
    SMARTCheck,
)
from curriculum_agent.prompts.smart_validator import build_smart_soft_judge_prompt
from curriculum_agent.prompts.stage_3_plo import build_plo_from_need_prompt
from curriculum_agent.stages.need_grouping import MAX_NEEDS, MIN_NEEDS
from curriculum_agent.stages.smart_rules import (
    CRITERION_FIX_HINTS_TH,
    HardCriterion,
    hard_failures,
)

_MAX_RETRIES = 3


class _PLODraft(BaseModel):
    """Intermediate schema for LLM output before SMART check is added."""

    plo_id: str
    statement_th: str
    statement_en: str | None = None
    bloom_level: BloomLevel
    is_subject_specific: bool = True
    action_verb_th: str
    source_need_ids: list[str]
    source_evidence_ids: list[str] = Field(default_factory=list)
    rationale_th: str
    distinctive_feature_th: str | None = None

    @model_validator(mode="after")
    def _check_needs(self) -> _PLODraft:
        if not self.source_need_ids:
            raise ValueError("source_need_ids must not be empty")
        return self


class _SingleDraftResponse(BaseModel):
    plo: _PLODraft


class _SmartSoftJudge(BaseModel):
    specific_object_ok: bool
    achievable_ok: bool
    relevant_alignment_ok: bool
    notes_th: str | None = None


class _SmartOutcome(BaseModel):
    draft: _PLODraft
    smart_check: SMARTCheck
    retry_count: int
    escalated: bool
    soft_flags: list[str]


def _build_fix_prompt(draft: _PLODraft, violated: list[HardCriterion]) -> list[dict[str, str]]:
    hints = "\n".join(f"- {CRITERION_FIX_HINTS_TH[c]}" for c in violated)
    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้เชี่ยวชาญ OBE ปรับปรุง PLO ที่ไม่ผ่านเกณฑ์ SMART ข้อที่ระบุ "
                "โดยคงสาระสำคัญเดิม ตอบเป็น JSON object field เหมือน PLO เดิม"
            ),
        },
        {
            "role": "user",
            "content": (
                f"PLO เดิม:\n{draft.statement_th}\n\n"
                f"เกณฑ์ที่ไม่ผ่าน:\n{hints}\n\n"
                f"Bloom level: {draft.bloom_level.value}, action_verb_th: {draft.action_verb_th}\n"
                "เขียน PLO ใหม่ให้ผ่านเกณฑ์ข้างต้นทุกข้อ"
            ),
        },
    ]


async def _ensure_smart(
    draft: _PLODraft, known_need_ids: set[str], metadata: ProgramMetadata
) -> _SmartOutcome:
    """Hard fails → per-PLO retry (max _MAX_RETRIES) naming the criterion; soft fails → flags."""
    fails = hard_failures(
        draft.statement_th, draft.action_verb_th, draft.source_need_ids, known_need_ids
    )
    retries = 0
    while fails and retries < _MAX_RETRIES:
        retries += 1
        logger.debug(f"  SMART retry {retries} for PLO {draft.plo_id}: {[f.value for f in fails]}")
        try:
            fix = await complete_heavy(
                _SingleDraftResponse, _build_fix_prompt(draft, fails), max_retries=2
            )
            draft = fix.plo
        except Exception as exc:
            logger.warning(f"  SMART fix attempt {retries} failed: {exc}")
        fails = hard_failures(
            draft.statement_th, draft.action_verb_th, draft.source_need_ids, known_need_ids
        )

    escalated = bool(fails)
    if escalated:
        logger.warning(
            f"  PLO {draft.plo_id} escalated after {retries} retries: {[f.value for f in fails]}"
        )

    soft_flags: list[str] = []
    notes: str | None = None
    try:
        judge = await complete_light(
            _SmartSoftJudge,
            build_smart_soft_judge_prompt(
                draft.statement_th, metadata.vision_th, metadata.degree_level
            ),
        )
        notes = judge.notes_th
        if not judge.specific_object_ok:
            soft_flags.append("S_object")
        if not judge.achievable_ok:
            soft_flags.append("A_level")
        if not judge.relevant_alignment_ok:
            soft_flags.append("R_alignment")
    except Exception as exc:
        logger.warning(f"  Soft judge failed for PLO {draft.plo_id}: {exc}")

    smart = SMARTCheck(
        specific=HardCriterion.S_VERB not in fails,
        measurable=HardCriterion.M_FORBIDDEN not in fails,
        achievable=True,
        relevant=HardCriterion.R_EVIDENCE not in fails,
        timely=True,
        notes_th=notes,
    )
    return _SmartOutcome(
        draft=draft,
        smart_check=smart,
        retry_count=retries,
        escalated=escalated,
        soft_flags=soft_flags,
    )


async def synthesize_from_needs(
    metadata: ProgramMetadata,
    needs: list[Need],
    program_id: str,
    known_need_ids: set[str],
) -> PLO | None:
    """Draft one PLO from one or more Needs, then run it through the SMART gate.

    Shared by the 1:1 stage loop and the designer-driven N:1 endpoint, so both
    paths get the same SMART enforcement and evidence fallback. Returns None when
    the model call fails outright — the caller decides whether that is fatal.
    """
    if not needs:
        raise ValueError("synthesize_from_needs requires at least one Need")

    try:
        response = await complete_heavy(
            _SingleDraftResponse,
            build_plo_from_need_prompt(metadata, needs),
            max_retries=_MAX_RETRIES,
        )
    except Exception as exc:
        ids = ", ".join(n.need_id for n in needs)
        logger.warning(f"PLO synthesis failed for Need(s) {ids}: {exc}")
        return None

    outcome = await _ensure_smart(response.plo, known_need_ids, metadata)
    draft = outcome.draft

    # The Needs already carry a verified evidence trail; fall back to it rather
    # than trusting the model to echo evidence ids correctly.
    evidence_ids = draft.source_evidence_ids or sorted(
        {eid for n in needs for eid in n.source_evidence_ids}
    )

    return PLO(
        plo_id=draft.plo_id or f"PLO-{uuid.uuid4().hex[:6]}",
        program_id=program_id,
        statement_th=draft.statement_th,
        statement_en=draft.statement_en,
        bloom_level=draft.bloom_level,
        # Specific when any contributing Need is subject-specific: a PLO covering
        # a domain capability stays domain-specific even if merged with a generic one.
        is_subject_specific=any(n.ksec_category is KSECCategory.SS for n in needs),
        action_verb_th=draft.action_verb_th,
        smart_check=outcome.smart_check,
        source_need_ids=[n.need_id for n in needs],
        source_evidence_ids=evidence_ids,
        rationale_th=draft.rationale_th,
        distinctive_feature_th=draft.distinctive_feature_th,
        version=1,
        smart_retry_count=outcome.retry_count,
        smart_escalated=outcome.escalated,
        soft_flags=outcome.soft_flags,
        # Optional only when every contributing Need is optional.
        is_optional=all(n.is_optional for n in needs),
    )


async def run(state: AgentState) -> AgentState:
    """Stage 4: one PLO per Need."""
    program_id = state.get("program_id", "unknown")
    metadata_dict = state.get("metadata")
    if not metadata_dict:
        raise ValueError("AgentState missing 'metadata' — cannot run PLO synthesis stage")
    metadata = ProgramMetadata.model_validate(metadata_dict)

    needs = [Need.model_validate(d) for d in state.get("needs", [])]
    if not needs:
        raise ValueError(
            f"Stage 4: no Needs for program '{program_id}' — "
            "run need_combination successfully before PLO synthesis"
        )

    known_need_ids = {n.need_id for n in needs}
    logger.info(f"Stage 4: synthesizing one PLO per Need ({len(needs)} Needs)")

    plos: list[PLO] = []
    for need in needs:
        plo = await synthesize_from_needs(metadata, [need], program_id, known_need_ids)
        if plo is not None:
            plos.append(plo)

    core = sum(1 for p in plos if not p.is_optional)
    if not MIN_NEEDS <= core <= MAX_NEEDS:
        logger.warning(
            f"Stage 4 produced {core} core PLOs, outside the {MIN_NEEDS}-{MAX_NEEDS} policy — "
            "need_combination should have enforced this; review at the checkpoint"
        )

    await PLORepository().bulk_insert(plos)
    state["plos"] = [p.model_dump(mode="json") for p in plos]
    state["current_stage"] = "plo_synthesis"
    return state
