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
    Domain,
    KrathwohlLevel,
    ProgramMetadata,
    SkillCluster,
    SMARTCheck,
)
from curriculum_agent.prompts.smart_validator import build_smart_soft_judge_prompt
from curriculum_agent.prompts.stage_3_plo import build_plo_synthesis_prompt
from curriculum_agent.stages.smart_rules import (
    CRITERION_FIX_HINTS_TH,
    HardCriterion,
    hard_failures,
)

_MAX_RETRIES = 3
_MIN_PLOS = 6
_MAX_PLOS = 10


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


def _build_fix_prompt(draft: _PLODraft, violated: list[HardCriterion]) -> list[dict]:
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
                f"Domain: {draft.domain.value}, action_verb_th: {draft.action_verb_th}\n"
                "เขียน PLO ใหม่ให้ผ่านเกณฑ์ข้างต้นทุกข้อ"
            ),
        },
    ]


async def _ensure_smart(
    draft: _PLODraft, known_cluster_ids: set[str], metadata: ProgramMetadata
) -> _SmartOutcome:
    """Hard fails → per-PLO retry (max _MAX_RETRIES) naming the criterion; soft fails → flags."""
    fails = hard_failures(
        draft.statement_th, draft.action_verb_th, draft.source_cluster_ids, known_cluster_ids
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
            draft.statement_th, draft.action_verb_th, draft.source_cluster_ids, known_cluster_ids
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
        draft=draft, smart_check=smart, retry_count=retries,
        escalated=escalated, soft_flags=soft_flags,
    )


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
        selected = sorted(clusters, key=lambda c: c.demand_score, reverse=True)[:12]

    if not selected:
        raise ValueError(
            f"Stage 3: no skill clusters available for program '{program_id}' — "
            "run Stage 2 successfully before proceeding to PLO synthesis"
        )

    cluster_evidence_map: dict[str, list[str]] = {
        c.cluster_id: c.source_evidence_ids for c in clusters
    }
    known_cluster_ids = {c.cluster_id for c in clusters}

    logger.info(f"Stage 3: synthesizing PLOs from {len(selected)} clusters")

    messages = build_plo_synthesis_prompt(metadata, selected)
    draft_list = await complete_heavy(_PLODraftList, messages, max_retries=_MAX_RETRIES)
    drafts = draft_list.plos[:_MAX_PLOS]

    plos: list[PLO] = []
    for draft in drafts:
        outcome = await _ensure_smart(draft, known_cluster_ids, metadata)
        validated_draft, smart_check = outcome.draft, outcome.smart_check

        # Derive evidence IDs from referenced clusters when LLM omits them.
        # Fallback chain: draft field → referenced clusters → all clusters.
        evidence_ids = validated_draft.source_evidence_ids
        if not evidence_ids:
            evidence_ids = list({
                eid
                for cid in validated_draft.source_cluster_ids
                for eid in cluster_evidence_map.get(cid, [])
            })
            logger.debug(
                f"  PLO {validated_draft.plo_id}: derived {len(evidence_ids)} "
                "source_evidence_ids from referenced clusters"
            )
        if not evidence_ids:
            # Referenced clusters have no evidence; collect from all clusters in program.
            evidence_ids = list({eid for c in clusters for eid in c.source_evidence_ids})
            logger.warning(
                f"  PLO {validated_draft.plo_id}: source clusters carry no evidence IDs — "
                f"fell back to all-cluster pool ({len(evidence_ids)} IDs)"
            )
        if not evidence_ids:
            raise ValueError(
                f"PLO {validated_draft.plo_id}: cannot trace to any evidence — "
                "run stakeholder needs + skill extraction before PLO synthesis"
            )

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
                source_evidence_ids=evidence_ids,
                rationale_th=validated_draft.rationale_th,
                distinctive_feature_th=validated_draft.distinctive_feature_th,
                version=1,
                smart_retry_count=outcome.retry_count,
                smart_escalated=outcome.escalated,
                soft_flags=outcome.soft_flags,
            )
        )

    if len(plos) < _MIN_PLOS:
        logger.warning(
            f"Stage 3: only {len(plos)} PLOs generated (expected {_MIN_PLOS}-{_MAX_PLOS})"
        )

    await PLORepository().bulk_insert(plos)

    state["plos"] = [p.model_dump(mode="json") for p in plos]
    state["current_stage"] = "plo_synthesis"
    return state
