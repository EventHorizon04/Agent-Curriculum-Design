from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from curriculum_agent.api.deps import require_api_key
from curriculum_agent.api.jobs import program_busy, program_lock, sync_writer
from curriculum_agent.data.repositories import (
    EvidenceRepository,
    NeedRepository,
    SkillRepository,
)
from curriculum_agent.models import StakeholderEvidence, StakeholderType
from curriculum_agent.stages.stakeholder_needs import classify_evidence_type, classify_single

router = APIRouter()
_repo = EvidenceRepository()

EVIDENCE_LOCKED_TH = (
    "สกัดทักษะจาก evidence แล้ว แก้ เพิ่ม หรือลบ evidence ไม่ได้ — คัดลอกหลักสูตรแบบเฉพาะข้อมูลนำเข้าหากต้องแก้"
)


class EvidenceUpdate(BaseModel):
    stakeholder_type: StakeholderType
    source_name: str
    raw_text_th: str
    source_url: str | None = None


class EvidenceLock(BaseModel):
    locked: bool
    reason_th: str | None


async def evidence_lock_reason(program_id: str) -> str | None:
    """Why this program's evidence cannot change, in Thai, or None when it can.

    Skills and Needs are derived from the evidence and cite it, so once either
    exists an edit would leave them describing text that is no longer there. A
    running writer locks it too: extraction reads the evidence mid-run.
    """
    if (busy := await program_busy(program_id)) is not None:
        return busy
    if await SkillRepository().has_any(program_id) or await NeedRepository().has_any(program_id):
        return EVIDENCE_LOCKED_TH
    return None


async def _refuse_if_locked(program_id: str) -> None:
    if (reason := await evidence_lock_reason(program_id)) is not None:
        raise HTTPException(status_code=409, detail=reason)


@router.get("/lock", response_model=EvidenceLock)
async def evidence_lock(program_id: str) -> EvidenceLock:
    reason = await evidence_lock_reason(program_id)
    return EvidenceLock(locked=reason is not None, reason_th=reason)


@router.get("/", response_model=list[StakeholderEvidence])
async def list_evidence(program_id: str) -> list[StakeholderEvidence]:
    return await _repo.list_by_program(program_id)


@router.post("/", response_model=StakeholderEvidence, dependencies=[Depends(require_api_key)])
async def upload_evidence(program_id: str, evidence: StakeholderEvidence) -> StakeholderEvidence:
    """Store one evidence item, classified here rather than as the client sent it.

    `classification` is derived from `stakeholder_type` in code — a mandate is a
    property of who is speaking — so it is this route's output, never its input.
    It used to be stored verbatim, and the field defaults to "general" on the
    model, so every item saved through the form landed as `general` however it
    was spoken: on the demo programme all three `institutional_direction` items
    did, and `classify_evidence_type` says every one of them is a `requirement`.

    That default then decided the whole run. No evidence carrying a mandate means
    no skill classified `requirement` (`classify_skills` propagates it), and
    `is_optional_group` then read `want > requirement + need`, which was true of
    almost every group; and `MAX_CORE_PLOS` only bounds the core series, so a
    programme whose Needs are all optional has no ceiling at all. The stored run
    showed exactly that: 13 of 14 Needs optional, 12 optional PLOs, zero core ones.

    That rule has since been replaced — `is_optional_group` now asks how many
    evidence items a group was drawn from — because fixing this route only fixed
    half of it: `need` never fired either, so `requirement` was the only way to be
    core and a programme without a professional council had exactly one source of
    it. This route's job is unchanged, and so is the reason for it.

    Classification did exist, in `GET /classify-stream`, as a separate step the
    designer had to know to run. A field the code owns cannot depend on that.
    """
    # Check and write under one lock, like every other short writer: a job that
    # started between them would read the old text while this commit lands.
    async with program_lock(program_id):
        await _refuse_if_locked(program_id)
        # The lock above is the path program's, but the row is upserted by the
        # body's global id under the body's program. Both have to name the path
        # program, or a POST to an unlocked program could rewrite — or move —
        # a locked program's evidence while its skills still cite it.
        if evidence.program_id != program_id:
            raise HTTPException(status_code=422, detail="program_id ใน body ไม่ตรงกับหลักสูตรที่ระบุ")
        owner = await _repo.program_of(evidence.evidence_id)
        if owner is not None and owner != program_id:
            raise HTTPException(status_code=409, detail="evidence_id นี้เป็นของหลักสูตรอื่น")
        classified = await classify_single(evidence)
        await _repo.bulk_insert([classified])
    return classified


@router.put(
    "/{evidence_id}", response_model=StakeholderEvidence, dependencies=[Depends(require_api_key)]
)
async def update_evidence(
    program_id: str, evidence_id: str, body: EvidenceUpdate
) -> StakeholderEvidence:
    """Edit what the designer typed; the id stays and the class is re-derived."""
    async with program_lock(program_id):
        await _refuse_if_locked(program_id)
        existing = await _repo.get(program_id, evidence_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="ไม่พบหลักฐานนี้")
        # The rationale and the English text described the old text and type, so
        # they go back to their defaults rather than outliving what they explain.
        updated = existing.model_copy(
            update={
                "stakeholder_type": body.stakeholder_type,
                "source_name": body.source_name,
                "raw_text_th": body.raw_text_th,
                "source_url": body.source_url,
                "classification": classify_evidence_type(body.stakeholder_type),
                "classification_rationale_th": None,
                "raw_text_en": None,
            }
        )
        await _repo.bulk_insert([updated])
    return updated


@router.get("/classify-stream", dependencies=[Depends(require_api_key)])
async def classify_evidence_stream(program_id: str) -> StreamingResponse:
    """SSE endpoint: classify unclassified evidence items one-by-one, streaming progress."""
    await _refuse_if_locked(program_id)

    async def _generate() -> AsyncGenerator[str, None]:
        # Registered for the whole stream: it rewrites evidence item by item, and
        # a job starting mid-stream would read a half-rewritten set. The
        # registration is dropped when the stream ends or the client disconnects.
        try:
            async with sync_writer(program_id, "กำลังจัดประเภท evidence — รอให้เสร็จก่อน"):
                repo = EvidenceRepository()
                to_classify = await repo.list_by_program(program_id)
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
        except HTTPException as exc:
            # A writer slipped in after the pre-check; the status line is already sent.
            yield f"data: {json.dumps({'status': 'error', 'detail': exc.detail})}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        # Without these, a proxy in front of this process is free to buffer the
        # whole stream and deliver it on close — the per-item progress the UI
        # renders would arrive as one burst at the end.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/{evidence_id}", status_code=204, dependencies=[Depends(require_api_key)])
async def delete_evidence(program_id: str, evidence_id: str) -> None:
    async with program_lock(program_id):
        await _refuse_if_locked(program_id)
        try:
            deleted = await _repo.delete(program_id, evidence_id)
        except IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail="ลบไม่ได้ — หลักฐานนี้ถูกใช้ในการสกัดทักษะแล้ว",
            ) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="ไม่พบหลักฐานนี้")
