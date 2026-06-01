from __future__ import annotations

from typing import Literal

from loguru import logger
from pydantic import BaseModel
from qdrant_client.models import Distance, PointStruct, VectorParams

from curriculum_agent.data.qdrant import EVIDENCE_COLLECTION, get_qdrant
from curriculum_agent.data.repositories import EvidenceRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_light
from curriculum_agent.models import StakeholderEvidence
from curriculum_agent.nlp.embedding import embed
from curriculum_agent.prompts.classify_evidence import build_classify_evidence_prompt

_EMBED_DIM = 1024  # BGE-M3 output dimension


class _ClassifyResult(BaseModel):
    classification: Literal["need", "requirement", "want", "unclassified"]
    classification_rationale_th: str


async def _ensure_collection() -> None:
    client = get_qdrant()
    existing = await client.get_collections()
    names = {c.name for c in existing.collections}
    if EVIDENCE_COLLECTION not in names:
        await client.create_collection(
            collection_name=EVIDENCE_COLLECTION,
            vectors_config=VectorParams(size=_EMBED_DIM, distance=Distance.COSINE),
        )


async def classify_single(evidence: StakeholderEvidence) -> StakeholderEvidence:
    """Classify one evidence item via LLM. Used by both the stage and the SSE endpoint."""
    messages = build_classify_evidence_prompt(evidence)
    result = await complete_light(_ClassifyResult, messages)
    return evidence.model_copy(
        update={
            "classification": result.classification,
            "classification_rationale_th": result.classification_rationale_th,
        }
    )


async def _embed_and_upsert(evidence_models: list[StakeholderEvidence]) -> None:
    await _ensure_collection()
    texts = [e.raw_text_th for e in evidence_models]
    vectors = embed(texts)
    client = get_qdrant()
    points = [
        PointStruct(
            id=abs(hash(e.evidence_id)) % (2**63),
            vector=vec,
            payload={
                "evidence_id": e.evidence_id,
                "program_id": e.program_id,
                "stakeholder_type": e.stakeholder_type.value,
                "classification": e.classification,
            },
        )
        for e, vec in zip(evidence_models, vectors)
    ]
    await client.upsert(collection_name=EVIDENCE_COLLECTION, points=points)


async def run(state: AgentState) -> AgentState:
    """Stage 1: classify unclassified evidence, persist to Postgres + Qdrant."""
    raw = state.get("raw_evidence", [])
    all_items = [StakeholderEvidence.model_validate(d) for d in raw]

    to_classify = [e for e in all_items if e.classification == "unclassified"]
    already_done = [e for e in all_items if e.classification != "unclassified"]
    logger.info(
        f"Stage 1: {len(to_classify)} to classify, {len(already_done)} already classified"
    )

    newly_classified: list[StakeholderEvidence] = []
    for evidence in to_classify:
        updated = await classify_single(evidence)
        newly_classified.append(updated)
        logger.debug(f"  {updated.evidence_id}: {updated.source_name} → {updated.classification}")

    if newly_classified:
        repo = EvidenceRepository()
        await repo.bulk_insert(newly_classified)
        await _embed_and_upsert(newly_classified)

    all_classified = already_done + newly_classified
    state["classified_evidence"] = [e.model_dump(mode="json") for e in all_classified]
    state["current_stage"] = "stakeholder_needs"
    return state
