from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from curriculum_agent.api.deps import require_api_key
from curriculum_agent.data.repositories import ProgramRepository
from curriculum_agent.graph import build_graph
from curriculum_agent.models import ProgramMetadata

router = APIRouter()


@router.post("/", response_model=ProgramMetadata, dependencies=[Depends(require_api_key)])
async def create_program(metadata: ProgramMetadata) -> ProgramMetadata:
    repo = ProgramRepository()
    await repo.upsert(metadata)
    graph = build_graph()
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
