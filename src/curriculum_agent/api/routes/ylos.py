from __future__ import annotations

from fastapi import APIRouter, HTTPException

from curriculum_agent.data.repositories import YLORepository
from curriculum_agent.models import YLOMatrix

router = APIRouter()
_repo = YLORepository()


@router.get("/matrix", response_model=YLOMatrix)
async def get_ylo_matrix(program_id: str) -> YLOMatrix:
    matrix = await _repo.get_matrix(program_id)
    if matrix is None:
        raise HTTPException(status_code=404, detail="YLO matrix not found")
    return matrix
