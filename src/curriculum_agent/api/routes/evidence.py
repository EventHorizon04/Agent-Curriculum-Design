from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError

from curriculum_agent.api.deps import require_api_key
from curriculum_agent.data.repositories import EvidenceRepository
from curriculum_agent.models import StakeholderEvidence
from curriculum_agent.stages.stakeholder_needs import classify_single

router = APIRouter()
_repo = EvidenceRepository()


@router.get("/", response_model=list[StakeholderEvidence])
async def list_evidence(program_id: str) -> list[StakeholderEvidence]:
    return await _repo.list_by_program(program_id)


@router.post("/", response_model=StakeholderEvidence, dependencies=[Depends(require_api_key)])
async def upload_evidence(program_id: str, evidence: StakeholderEvidence) -> StakeholderEvidence:
    await _repo.bulk_insert([evidence])
    return evidence


@router.get("/classify-stream", dependencies=[Depends(require_api_key)])
async def classify_evidence_stream(program_id: str) -> StreamingResponse:
    """SSE endpoint: classify unclassified evidence items one-by-one, streaming progress."""

    async def _generate() -> AsyncGenerator[str, None]:
        repo = EvidenceRepository()
        items = await repo.list_by_program(program_id)
        to_classify = items
        total = len(to_classify)

        yield f"data: {json.dumps({'status': 'started', 'total': total})}\n\n"

        for i, evidence in enumerate(to_classify, 1):
            updated = await classify_single(evidence)
            await repo.bulk_insert([updated])
            event = json.dumps(
                {
                    "status": "progress",
                    "index": i,
                    "total": total,
                    "evidence_id": updated.evidence_id,
                    "source_name": updated.source_name,
                    "classification": updated.classification,
                }
            )
            yield f"data: {event}\n\n"

        yield f"data: {json.dumps({'status': 'done', 'total': total})}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


@router.delete("/{evidence_id}", status_code=204, dependencies=[Depends(require_api_key)])
async def delete_evidence(program_id: str, evidence_id: str) -> None:
    try:
        deleted = await _repo.delete(program_id, evidence_id)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="ลบไม่ได้ — หลักฐานนี้ถูกใช้ในการสกัดทักษะแล้ว",
        ) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="ไม่พบหลักฐานนี้")
