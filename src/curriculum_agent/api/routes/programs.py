from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request

from curriculum_agent.api.deps import require_api_key
from curriculum_agent.data.repositories import ProgramRepository
from curriculum_agent.models import ProgramCreateRequest, ProgramMetadata

router = APIRouter()


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


@router.get("/{program_id}", response_model=ProgramMetadata)
async def get_program(program_id: str) -> ProgramMetadata:
    repo = ProgramRepository()
    result = await repo.get(program_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Program not found")
    return result
