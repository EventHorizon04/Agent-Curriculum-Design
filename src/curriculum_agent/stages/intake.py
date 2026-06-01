from __future__ import annotations

from loguru import logger

from curriculum_agent.data.repositories import EvidenceRepository, ProgramRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.models import ProgramMetadata


async def run(state: AgentState) -> AgentState:
    """Stage 0: validate ProgramMetadata, persist to Postgres, load evidence into state."""
    metadata_dict = state.get("metadata")
    if not metadata_dict:
        raise ValueError("AgentState missing 'metadata' — cannot run intake stage")
    metadata = ProgramMetadata.model_validate(metadata_dict)
    logger.info(f"Intake: program_id={metadata.program_id}, field={metadata.field}")

    program_repo = ProgramRepository()
    await program_repo.upsert(metadata)

    evidence_repo = EvidenceRepository()
    evidence_items = await evidence_repo.list_by_program(metadata.program_id)
    logger.info(f"Intake: loaded {len(evidence_items)} evidence items for classification")

    state["raw_evidence"] = [e.model_dump(mode="json") for e in evidence_items]
    state["current_stage"] = "intake"
    return state
