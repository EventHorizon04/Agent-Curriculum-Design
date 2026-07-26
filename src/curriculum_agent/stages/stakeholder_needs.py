from __future__ import annotations

from typing import Literal

from loguru import logger
from pydantic import BaseModel

from curriculum_agent.data.repositories import EvidenceRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_light
from curriculum_agent.models import StakeholderEvidence, StakeholderType
from curriculum_agent.prompts.classify_evidence import build_classify_evidence_prompt


class _ClassifyResult(BaseModel):
    # `want` is deliberately absent: it is reserved for WANT_ONLY_TYPES and
    # assigned in code, so the LLM cannot demote an employer requirement to a wish.
    classification: Literal["need", "requirement", "unclassified"]
    classification_rationale_th: str


# Community and parent input is aspirational by nature — a wish for the
# programme rather than a hiring requirement. The binding is a hard rule in both
# directions: these types are always `want`, and no other type can be `want`.
WANT_ONLY_TYPES = frozenset({StakeholderType.COMMUNITY, StakeholderType.PARENT})

_WANT_RATIONALE_TH = "ผู้มีส่วนได้ส่วนเสียกลุ่มชุมชน/ผู้ปกครอง จัดเป็น want ตามนโยบายหลักสูตร"


async def classify_single(evidence: StakeholderEvidence) -> StakeholderEvidence:
    """Classify one evidence item. Used by both the stage and the SSE endpoint.

    Community and parent evidence is classified in pure code — deterministic and
    free. Everything else goes to the LLM, which chooses requirement vs need.
    """
    if evidence.stakeholder_type in WANT_ONLY_TYPES:
        return evidence.model_copy(
            update={
                "classification": "want",
                "classification_rationale_th": _WANT_RATIONALE_TH,
            }
        )

    messages = build_classify_evidence_prompt(evidence)
    result = await complete_light(_ClassifyResult, messages)
    return evidence.model_copy(
        update={
            "classification": result.classification,
            "classification_rationale_th": result.classification_rationale_th,
        }
    )


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
