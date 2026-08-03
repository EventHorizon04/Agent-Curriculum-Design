from __future__ import annotations

from loguru import logger

from curriculum_agent.data.repositories import EvidenceRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.models import (
    REQUIREMENT_TYPES,
    EvidenceClassification,
    StakeholderEvidence,
    StakeholderType,
)


def classify_evidence_type(stakeholder_type: StakeholderType) -> EvidenceClassification:
    """Whether evidence from this stakeholder carries a mandate.

    Pure lookup, no LLM. The previous design asked a model to judge each item
    need/requirement/want, which was both a cost per item and the wrong question:
    a mandate is a property of who is speaking, not of how they phrased it.
    """
    return "requirement" if stakeholder_type in REQUIREMENT_TYPES else "general"


async def run(state: AgentState) -> AgentState:
    """Stage 1: classify unclassified evidence, persist to Postgres."""
    raw = state.get("raw_evidence", [])
    all_items = [StakeholderEvidence.model_validate(d) for d in raw]

    to_classify = [e for e in all_items if e.classification == "unclassified"]
    already_done = [e for e in all_items if e.classification != "unclassified"]
    logger.info(f"Stage 1: {len(to_classify)} to classify, {len(already_done)} already classified")

    newly_classified: list[StakeholderEvidence] = []
    for evidence in to_classify:
        updated = await classify_single(evidence)
        newly_classified.append(updated)
        logger.debug(f"  {updated.evidence_id}: {updated.source_name} → {updated.classification}")

    if newly_classified:
        repo = EvidenceRepository()
        await repo.bulk_insert(newly_classified)

    all_classified = already_done + newly_classified
    state["classified_evidence"] = [e.model_dump(mode="json") for e in all_classified]
    state["current_stage"] = "stakeholder_needs"
    return state
