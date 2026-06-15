from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from curriculum_agent.api.deps import require_api_key
from curriculum_agent.data.repositories import (
    ClusterRepository,
    EvidenceRepository,
    PLORepository,
    ProgramRepository,
)
from curriculum_agent.graph import AgentState
from curriculum_agent.models import PLO, SkillCluster, StakeholderEvidence

router = APIRouter()
_repo = PLORepository()


class PLOTrace(BaseModel):
    plo: PLO
    clusters: list[SkillCluster]
    evidence: list[StakeholderEvidence]


@router.get("/", response_model=list[PLO])
async def list_plos(program_id: str) -> list[PLO]:
    return await _repo.list_by_program(program_id)


@router.get("/{plo_id}/trace", response_model=PLOTrace)
async def get_plo_trace(program_id: str, plo_id: str) -> PLOTrace:
    plos = await _repo.list_by_program(program_id)
    plo = next((p for p in plos if p.plo_id == plo_id), None)
    if plo is None:
        raise HTTPException(status_code=404, detail="PLO not found")

    cluster_ids = set(plo.source_cluster_ids)
    evidence_ids = set(plo.source_evidence_ids)

    all_clusters = await ClusterRepository().list_by_program(program_id)
    all_evidence = await EvidenceRepository().list_by_program(program_id)

    return PLOTrace(
        plo=plo,
        clusters=[c for c in all_clusters if c.cluster_id in cluster_ids],
        evidence=[e for e in all_evidence if e.evidence_id in evidence_ids],
    )


@router.post("/run", response_model=list[PLO])
async def run_plo_synthesis(program_id: str) -> list[PLO]:
    from curriculum_agent.stages.plo_synthesis import run  # noqa: PLC0415

    metadata = await ProgramRepository().get(program_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="Program not found")

    clusters = await ClusterRepository().list_by_program(program_id)
    if not clusters:
        raise HTTPException(
            status_code=422,
            detail="ไม่มี skill clusters สำหรับโปรแกรมนี้ กรุณารัน Skill Extraction ก่อน",
        )

    state: AgentState = {
        "program_id": program_id,
        "metadata": metadata.model_dump(mode="json"),
        "skill_clusters": [c.model_dump(mode="json") for c in clusters],
    }

    result_state = await run(state)
    return [PLO.model_validate(p) for p in result_state.get("plos", [])]


@router.post("/report/run", response_model=list[PLO])
async def run_plo_report(program_id: str) -> list[PLO]:
    from curriculum_agent.stages.plo_report import run  # noqa: PLC0415

    plos = await _repo.list_by_program(program_id)
    if not plos:
        raise HTTPException(
            status_code=422,
            detail="ยังไม่มี PLO สำหรับโปรแกรมนี้ กรุณารัน PLO Synthesis ก่อน",
        )

    state: AgentState = {
        "program_id": program_id,
        "plos": [p.model_dump(mode="json") for p in plos],
    }
    result_state = await run(state)
    return [PLO.model_validate(p) for p in result_state.get("plos", [])]


@router.put("/{plo_id}", response_model=PLO, dependencies=[Depends(require_api_key)])
async def update_plo(program_id: str, plo_id: str, plo: PLO) -> PLO:
    existing = await _repo.list_by_program(program_id)
    match = next((p for p in existing if p.plo_id == plo_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="PLO not found")

    update_fields: dict = {"version": match.version + 1, "program_id": program_id}
    if plo.classification is not None:
        # Human edit is the source of truth: mark manual and force the flag to match.
        update_fields["classification_method"] = "manual"
        update_fields["is_subject_specific"] = plo.classification == "specific"
    updated = plo.model_copy(update=update_fields)
    await _repo.bulk_insert([updated])
    return updated
