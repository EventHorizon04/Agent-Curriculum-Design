from __future__ import annotations

from loguru import logger

from curriculum_agent.data.repositories import EvidenceRepository, ProgramRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_light
from curriculum_agent.models import ExtractedMetadata, ProgramMetadata
from curriculum_agent.prompts.extract_metadata import build_extract_metadata_prompt


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


DOC_TEXT_LIMIT = 8_000  # chars of parsed document text fed to the light model


async def extract_metadata_from_text(text: str) -> ExtractedMetadata:
    """Extract university vision/mission/identity from parsed document text.

    Stateless helper for the intake prefill endpoint — no DB access.
    """
    messages = build_extract_metadata_prompt(text[:DOC_TEXT_LIMIT])
    return await complete_light(ExtractedMetadata, messages)
