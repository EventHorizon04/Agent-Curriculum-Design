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


async def classify_single(evidence: StakeholderEvidence) -> StakeholderEvidence:
    """Classify one evidence item. Used by the stage and the SSE endpoint.

    Async only to keep the endpoint's call site unchanged — there is no I/O left
    to await now that the classification is a lookup.
    """
    return evidence.model_copy(
        update={"classification": classify_evidence_type(evidence.stakeholder_type)}
    )


async def run(state: AgentState) -> AgentState:
    """Stage 1: derive every evidence item's class from its stakeholder type.

    Every item is reclassified on every run, not just the previously unclassified
    ones: the class is now derived from the type, so a stored value that disagrees
    is stale data to correct rather than a human judgement to preserve.
    """
    raw = state.get("raw_evidence", [])
    items = [StakeholderEvidence.model_validate(d) for d in raw]
    logger.info(f"Stage 1: classifying {len(items)} evidence items")

    classified = [await classify_single(e) for e in items]
    requirements = sum(1 for e in classified if e.classification == "requirement")
    logger.info(f"Stage 1: {requirements} requirement, {len(classified) - requirements} general")

    if classified:
        await EvidenceRepository().bulk_insert(classified)

    state["classified_evidence"] = [e.model_dump(mode="json") for e in classified]
    state["current_stage"] = "stakeholder_needs"
    return state
