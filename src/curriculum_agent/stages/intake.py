from __future__ import annotations

from loguru import logger

from curriculum_agent.data.repositories import ProgramRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.models import ProgramMetadata


async def run(state: AgentState) -> AgentState:
    """Stage 0: validate ProgramMetadata and persist to Postgres."""
    metadata_dict = state.get("metadata")
    if not metadata_dict:
        raise ValueError("AgentState missing 'metadata' — cannot run intake stage")
    metadata = ProgramMetadata.model_validate(metadata_dict)
    logger.info(f"Intake: program_id={metadata.program_id}, field={metadata.field}")

    repo = ProgramRepository()
    await repo.upsert(metadata)

    state["current_stage"] = "intake"
    return state
