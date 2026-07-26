from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from curriculum_agent.data.repositories import (
    EvidenceRepository,
    NeedRepository,
    SkillRepository,
)
from curriculum_agent.graph import AgentState
from curriculum_agent.models import (
    ExtractedSkill,
    Need,
    StakeholderEvidence,
    StakeholderType,
)
from curriculum_agent.stages.demand import BREADTH_WEIGHT, FREQ_WEIGHT

router = APIRouter()
_repo = NeedRepository()

_MAX_STAKEHOLDER_TYPES = len(StakeholderType)


class DemandSignal(BaseModel):
    total_program_evidence: int
    unique_evidence_count: int
    freq_score: float  # unique_evidence / total  (weight 0.6)
    stakeholder_type_count: int
    max_stakeholder_types: int  # = len(StakeholderType)
    breadth_score: float  # types_covered / max      (weight 0.4)
    demand_score: float  # freq*0.6 + breadth*0.4
    stakeholder_breakdown: dict[str, int]  # type → evidence count


class NeedTrace(BaseModel):
    need: Need
    skills: list[ExtractedSkill]
    evidence: list[StakeholderEvidence]
    demand_signal: DemandSignal


@router.get("/", response_model=list[Need])
async def list_clusters(program_id: str) -> list[Need]:
    return await _repo.list_by_program(program_id)


@router.get("/{cluster_id}/trace", response_model=NeedTrace)
async def get_cluster_trace(program_id: str, cluster_id: str) -> NeedTrace:
    needs = await _repo.list_by_program(program_id)
    need = next((n for n in needs if n.need_id == cluster_id), None)
    if need is None:
        raise HTTPException(status_code=404, detail="Cluster not found")

    all_evidence, need_skills = await asyncio.gather(
        EvidenceRepository().list_by_program(program_id),
        SkillRepository().list_by_ids(need.member_skill_ids),
    )
    total = len(all_evidence)

    evidence_ids = set(need.source_evidence_ids)
    need_evidence = [e for e in all_evidence if e.evidence_id in evidence_ids]

    unique = len(evidence_ids)
    freq = unique / max(total, 1)
    stk_count = len(need.stakeholder_coverage)
    breadth = stk_count / max(_MAX_STAKEHOLDER_TYPES, 1)

    demand_signal = DemandSignal(
        total_program_evidence=total,
        unique_evidence_count=unique,
        freq_score=round(freq, 4),
        stakeholder_type_count=stk_count,
        max_stakeholder_types=_MAX_STAKEHOLDER_TYPES,
        breadth_score=round(breadth, 4),
        demand_score=round(min(freq * FREQ_WEIGHT + breadth * BREADTH_WEIGHT, 1.0), 4),
        stakeholder_breakdown={
            k.value if hasattr(k, "value") else k: v for k, v in need.stakeholder_coverage.items()
        },
    )

    return NeedTrace(
        need=need,
        skills=need_skills,
        evidence=need_evidence,
        demand_signal=demand_signal,
    )


@router.post("/run", response_model=list[Need])
async def run_skill_extraction(program_id: str) -> list[Need]:
    from curriculum_agent.stages.need_combination import (
        run as run_need_combination,  # noqa: PLC0415
    )
    from curriculum_agent.stages.skill_extraction import (
        run as run_skill_extraction,  # noqa: PLC0415
    )

    evidence_repo = EvidenceRepository()
    evidence_items = await evidence_repo.list_by_program(program_id)

    if not evidence_items:
        raise HTTPException(
            status_code=422,
            detail="ไม่มี evidence สำหรับโปรแกรมนี้ กรุณาเพิ่ม evidence ก่อน",
        )

    state: AgentState = {
        "program_id": program_id,
        "classified_evidence": [e.model_dump(mode="json") for e in evidence_items],
    }

    state = await asyncio.wait_for(run_skill_extraction(state), timeout=300)
    result_state = await asyncio.wait_for(run_need_combination(state), timeout=300)
    needs = [Need.model_validate(n) for n in result_state.get("needs", [])]
    return needs
