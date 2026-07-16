from __future__ import annotations

import asyncio
import os
import re
import tempfile

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from loguru import logger

from curriculum_agent.api.deps import require_api_key
from curriculum_agent.data.repositories import ProgramRepository
from curriculum_agent.models import ExtractedMetadata, ProgramCreateRequest, ProgramMetadata
from curriculum_agent.stages.intake import extract_metadata_from_text

router = APIRouter()

_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}
_MAX_FILE_BYTES = 10 * 1024 * 1024
_MIN_TEXT_CHARS = 50


def _slugify(text: str) -> str:
    """Lowercase ASCII slug; non-alphanumeric runs become '-'. Empty -> 'program'."""
    s = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "program"


async def _generate_program_id(name_en: str, repo: ProgramRepository) -> str:
    """Slug from name_en, with -2, -3, ... suffix on collision."""
    base = _slugify(name_en)
    candidate = base
    n = 2
    while await repo.exists(candidate):
        candidate = f"{base}-{n}"
        n += 1
    return candidate


@router.post("/", response_model=ProgramMetadata, dependencies=[Depends(require_api_key)])
async def create_program(req: ProgramCreateRequest, request: Request) -> ProgramMetadata:
    repo = ProgramRepository()
    program_id = await _generate_program_id(req.name_en, repo)
    metadata = ProgramMetadata(program_id=program_id, **req.model_dump())
    await repo.upsert(metadata)
    graph = request.app.state.graph
    await graph.ainvoke(
        {"program_id": metadata.program_id, "metadata": metadata.model_dump(mode="json")},
        config={"configurable": {"thread_id": metadata.program_id}},
    )
    return metadata


@router.post(
    "/extract-metadata",
    response_model=ExtractedMetadata,
    dependencies=[Depends(require_api_key)],
)
async def extract_metadata(file: UploadFile) -> ExtractedMetadata:
    """Parse an uploaded university document and LLM-extract intake prefill fields.

    Stateless: the file is parsed in a temp location and discarded — nothing
    is persisted. Runs before any program exists, so no program_id involved.
    """
    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail="รองรับเฉพาะไฟล์ PDF, DOCX, TXT")

    # Reject oversize uploads BEFORE buffering the body into memory, using the
    # size Starlette's multipart parser already tracked. Belt-and-braces: still
    # re-check len(content) below in case `file.size` is absent.
    if file.size and file.size > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="ไฟล์ต้องไม่เกิน 10 MB")

    content = await file.read()
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="ไฟล์ต้องไม่เกิน 10 MB")

    # Lazy import: unstructured is heavy and only needed on this endpoint —
    # keep it out of API startup and test collection.
    from curriculum_agent.parsers.tika_parser import parse_file

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            text = await asyncio.to_thread(parse_file, tmp_path)
        except Exception as exc:
            logger.warning(f"Document parse failed ({file.filename}): {exc}")
            raise HTTPException(status_code=422, detail="อ่านเนื้อหาจากไฟล์ไม่ได้") from exc
        if len(text.strip()) < _MIN_TEXT_CHARS:
            raise HTTPException(status_code=422, detail="อ่านเนื้อหาจากไฟล์ไม่ได้")
        try:
            return await extract_metadata_from_text(text)
        except Exception as exc:
            logger.error(f"Metadata extraction failed: {exc}")
            raise HTTPException(
                status_code=502, detail="สกัดข้อมูลไม่สำเร็จ กรุณาลองใหม่หรือกรอกเอง"
            ) from exc
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError as exc:
                logger.warning(f"Temp file cleanup failed ({tmp_path}): {exc}")


@router.get("/{program_id}", response_model=ProgramMetadata)
async def get_program(program_id: str) -> ProgramMetadata:
    repo = ProgramRepository()
    result = await repo.get(program_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Program not found")
    return result
