from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from curriculum_agent.api.deps import require_api_key
from curriculum_agent.data.repositories import (
    EvidenceRepository,
    NeedRepository,
    PLORepository,
    ProgramRepository,
)
from curriculum_agent.graph import AgentState
from curriculum_agent.models import PLO, Need, StakeholderEvidence

router = APIRouter()
_repo = PLORepository()


class PLOTrace(BaseModel):
    plo: PLO
    clusters: list[Need]
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

    need_ids = set(plo.source_need_ids)
    evidence_ids = set(plo.source_evidence_ids)

    all_needs = await NeedRepository().list_by_program(program_id)
    all_evidence = await EvidenceRepository().list_by_program(program_id)

    return PLOTrace(
        plo=plo,
        clusters=[n for n in all_needs if n.need_id in need_ids],
        evidence=[e for e in all_evidence if e.evidence_id in evidence_ids],
    )


@router.post("/run", response_model=list[PLO])
async def run_plo_synthesis(program_id: str) -> list[PLO]:
    from curriculum_agent.stages.plo_synthesis import run  # noqa: PLC0415

    metadata = await ProgramRepository().get(program_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="Program not found")

    needs = await NeedRepository().list_by_program(program_id)
    if not needs:
        raise HTTPException(
            status_code=422,
            detail="ไม่มี Needs สำหรับโปรแกรมนี้ กรุณารัน Need Combination ก่อน",
        )

    state: AgentState = {
        "program_id": program_id,
        "metadata": metadata.model_dump(mode="json"),
        "needs": [n.model_dump(mode="json") for n in needs],
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


class MergeNeedsRequest(BaseModel):
    need_ids: list[str] = Field(min_length=2)


@router.post("/from-needs", response_model=PLO)
async def create_plo_from_needs(program_id: str, body: MergeNeedsRequest) -> PLO:
    """Synthesize one PLO covering several designer-selected Needs.

    Program is looked up first: a missing program is a 404, not a 422 blaming
    the Needs. Need ids are validated only after the program exists.
    """
    from curriculum_agent.stages.plo_synthesis import synthesize_from_needs  # noqa: PLC0415

    program = await ProgramRepository().get(program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="ไม่พบหลักสูตรนี้")

    all_needs = await NeedRepository().list_by_program(program_id)
    by_id = {n.need_id: n for n in all_needs}
    missing = [nid for nid in body.need_ids if nid not in by_id]
    if missing:
        raise HTTPException(status_code=422, detail=f"ไม่พบ Need: {', '.join(missing)}")

    selected = [by_id[nid] for nid in body.need_ids]
    plo = await synthesize_from_needs(program, selected, program_id, {n.need_id for n in all_needs})
    if plo is None:
        raise HTTPException(status_code=502, detail="สร้าง PLO ไม่สำเร็จ กรุณาลองใหม่")

    await PLORepository().bulk_insert([plo])
    return plo


@router.put("/{plo_id}", response_model=PLO, dependencies=[Depends(require_api_key)])
async def update_plo(program_id: str, plo_id: str, plo: PLO) -> PLO:
    existing = await _repo.list_by_program(program_id)
    match = next((p for p in existing if p.plo_id == plo_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="PLO not found")

    update_fields: dict[str, object] = {"version": match.version + 1, "program_id": program_id}
    if plo.classification is not None:
        # Human edit is the source of truth: mark manual and force the flag to match.
        update_fields["classification_method"] = "manual"
        update_fields["is_subject_specific"] = plo.classification == "specific"
    updated = plo.model_copy(update=update_fields)
    await _repo.bulk_insert([updated])
    return updated
