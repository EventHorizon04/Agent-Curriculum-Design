from __future__ import annotations

from fastapi import APIRouter

from curriculum_agent.data.repositories import ClusterRepository
from curriculum_agent.models import SkillCluster

router = APIRouter()
_repo = ClusterRepository()


@router.get("/", response_model=list[SkillCluster])
async def list_clusters(program_id: str) -> list[SkillCluster]:
    return await _repo.list_by_program(program_id)
