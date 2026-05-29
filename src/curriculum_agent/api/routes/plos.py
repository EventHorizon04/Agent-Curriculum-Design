from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from curriculum_agent.api.deps import require_api_key
from curriculum_agent.data.repositories import PLORepository
from curriculum_agent.models import PLO

router = APIRouter()
_repo = PLORepository()


@router.get("/", response_model=list[PLO])
async def list_plos(program_id: str) -> list[PLO]:
    return await _repo.list_by_program(program_id)


@router.put("/{plo_id}", response_model=PLO, dependencies=[Depends(require_api_key)])
async def update_plo(program_id: str, plo_id: str, plo: PLO) -> PLO:
    existing = await _repo.list_by_program(program_id)
    match = next((p for p in existing if p.plo_id == plo_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="PLO not found")
    updated = plo.model_copy(update={"version": match.version + 1, "program_id": program_id})
    await _repo.bulk_insert([updated])
    return updated
