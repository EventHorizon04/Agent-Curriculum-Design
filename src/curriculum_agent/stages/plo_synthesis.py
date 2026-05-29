from __future__ import annotations

import uuid

from loguru import logger
from pydantic import BaseModel, Field, model_validator

from curriculum_agent.data.repositories import PLORepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_heavy, complete_light
from curriculum_agent.models import (
    FORBIDDEN_WORDS_TH,
    PLO,
    BloomLevel,
    Domain,
    KrathwohlLevel,
    SMARTCheck,
    SkillCluster,
)
from curriculum_agent.models import ProgramMetadata
from curriculum_agent.prompts.smart_validator import build_smart_validate_prompt
from curriculum_agent.prompts.stage_3_plo import build_plo_synthesis_prompt

_MAX_RETRIES = 3
_MIN_PLOS = 4
_MAX_PLOS = 6


class _PLODraft(BaseModel):
    """Intermediate schema for LLM output before SMART check is added."""
    plo_id: str
    statement_th: str
    statement_en: str | None = None
    domain: Domain
    bloom_level: BloomLevel | None = None
    krathwohl_level: KrathwohlLevel | None = None
    is_subject_specific: bool = True
    action_verb_th: str
    source_cluster_ids: list[str]
    source_evidence_ids: list[str] = Field(default_factory=list)
    rationale_th: str
    distinctive_feature_th: str | None = None

    @model_validator(mode="after")
    def _check_forbidden(self) -> _PLODraft:
        for word in FORBIDDEN_WORDS_TH:
            if word in self.statement_th:
                raise ValueError(f"forbidden word '{word}' — use an observable Bloom verb")
        return self

    @model_validator(mode="after")
    def _check_clusters(self) -> _PLODraft:
        if not self.source_cluster_ids:
            raise ValueError("source_cluster_ids must not be empty")
        return self

    @model_validator(mode="after")
    def _check_level(self) -> _PLODraft:
        if self.domain == Domain.AFFECTIVE:
            if self.krathwohl_level is None:
                raise ValueError("affective domain requires krathwohl_level")
        else:
            if self.bloom_level is None:
                raise ValueError(f"{self.domain} domain requires bloom_level")
        return self


class _PLODraftList(BaseModel):
    plos: list[_PLODraft] = Field(min_length=_MIN_PLOS, max_length=_MAX_PLOS)


def _build_fix_prompt(draft: _PLODraft, smart_notes: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้เชี่ยวชาญ OBE ปรับปรุง PLO ที่ไม่ผ่าน SMART ให้ผ่าน "
                "โดยยังคงสาระสำคัญเดิมไว้ ตอบเป็น JSON object ที่มี field เหมือน PLO เดิม"
            ),
        },
        {
            "role": "user",
            "content": (
                f"PLO ไม่ผ่าน SMART:\n{draft.statement_th}\n\n"
                f"เหตุผล: {smart_notes or 'ไม่ระบุ'}\n\n"
                f"Domain: {draft.domain.value}, action_verb_th: {draft.action_verb_th}\n"
                "กรุณาเขียน PLO ใหม่ให้ Specific, Measurable, Achievable, Relevant, Timely"
            ),
        },
    ]


class _SingleDraftResponse(BaseModel):
    plo: _PLODraft


async def _validate_smart(statement_th: str) -> SMARTCheck:
    return await complete_light(SMARTCheck, build_smart_validate_prompt(statement_th))


async def _ensure_smart(draft: _PLODraft) -> tuple[_PLODraft, SMARTCheck]:
    """Return (draft, smart_check), retrying up to _MAX_RETRIES if SMART fails."""
    smart = await _validate_smart(draft.statement_th)
    if smart.passed:
        return draft, smart

    for attempt in range(_MAX_RETRIES):
        logger.debug(f"  SMART retry {attempt + 1} for PLO {draft.plo_id}")
        try:
            fix_resp = await complete_heavy(
                _SingleDraftResponse,
                _build_fix_prompt(draft, smart.notes_th or ""),
                max_retries=2,
            )
            new_draft = fix_resp.plo
            new_smart = await _validate_smart(new_draft.statement_th)
            if new_smart.passed:
                return new_draft, new_smart
            smart = new_smart
            draft = new_draft
        except Exception as exc:
            logger.warning(f"  SMART fix attempt {attempt + 1} failed: {exc}")

    logger.warning(f"  PLO {draft.plo_id} could not pass SMART after {_MAX_RETRIES} retries")
    return draft, smart


async def run(state: AgentState) -> AgentState:
    """Stage 3: synthesize 4-6 PLOs from approved skill clusters."""
    clusters_dicts = state.get("skill_clusters", [])
    program_id = state.get("program_id", "unknown")
    metadata_dict = state.get("metadata")
    if not metadata_dict:
        raise ValueError("AgentState missing 'metadata' — cannot run PLO synthesis stage")
    metadata = ProgramMetadata.model_validate(metadata_dict)

    clusters = [SkillCluster.model_validate(d) for d in clusters_dicts]
    selected = [c for c in clusters if c.is_common_need]
    if len(selected) < _MIN_PLOS:
        selected = sorted(clusters, key=lambda c: c.demand_score, reverse=True)[:8]

    if not selected:
        raise ValueError(
            f"Stage 3: no skill clusters available for program '{program_id}' — "
            "run Stage 2 successfully before proceeding to PLO synthesis"
        )

    logger.info(f"Stage 3: synthesizing PLOs from {len(selected)} clusters")

    messages = build_plo_synthesis_prompt(metadata, selected)
    draft_list = await complete_heavy(_PLODraftList, messages, max_retries=_MAX_RETRIES)
    drafts = draft_list.plos[:_MAX_PLOS]

    plos: list[PLO] = []
    for draft in drafts:
        validated_draft, smart_check = await _ensure_smart(draft)
        plos.append(
            PLO(
                plo_id=validated_draft.plo_id or str(uuid.uuid4()),
                program_id=program_id,
                statement_th=validated_draft.statement_th,
                statement_en=validated_draft.statement_en,
                domain=validated_draft.domain,
                bloom_level=validated_draft.bloom_level,
                krathwohl_level=validated_draft.krathwohl_level,
                is_subject_specific=validated_draft.is_subject_specific,
                action_verb_th=validated_draft.action_verb_th,
                smart_check=smart_check,
                source_cluster_ids=validated_draft.source_cluster_ids,
                source_evidence_ids=validated_draft.source_evidence_ids,
                rationale_th=validated_draft.rationale_th,
                distinctive_feature_th=validated_draft.distinctive_feature_th,
                version=1,
            )
        )

    if len(plos) < _MIN_PLOS:
        logger.warning(f"Stage 3: only {len(plos)} PLOs generated (expected {_MIN_PLOS}-{_MAX_PLOS})")

    await PLORepository().bulk_insert(plos)

    state["plos"] = [p.model_dump(mode="json") for p in plos]
    state["current_stage"] = "plo_synthesis"
    return state
