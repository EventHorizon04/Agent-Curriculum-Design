from __future__ import annotations

from fastapi import APIRouter, Depends

from curriculum_agent.api.deps import require_api_key
from curriculum_agent.data.repositories import EvidenceRepository
from curriculum_agent.models import StakeholderEvidence

router = APIRouter()
_repo = EvidenceRepository()


@router.get("/", response_model=list[StakeholderEvidence])
async def list_evidence(program_id: str) -> list[StakeholderEvidence]:
    return await _repo.list_by_program(program_id)


@router.post("/", response_model=StakeholderEvidence, dependencies=[Depends(require_api_key)])
async def upload_evidence(program_id: str, evidence: StakeholderEvidence) -> StakeholderEvidence:
    await _repo.bulk_insert([evidence])
    return evidence
