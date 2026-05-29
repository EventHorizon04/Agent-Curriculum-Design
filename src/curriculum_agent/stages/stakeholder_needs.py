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


async def run(state: AgentState) -> AgentState:
    """Stage 1: classify stakeholder evidence with LLM, persist to Postgres + Qdrant."""
    raw = state.get("raw_evidence", [])
    logger.info(f"Stage 1: classifying {len(raw)} evidence items")

    classified_dicts: list[dict] = []
    evidence_models: list[StakeholderEvidence] = []

    for item_dict in raw:
        evidence = StakeholderEvidence.model_validate(item_dict)
        messages = build_classify_evidence_prompt(evidence)
        result = await complete_light(_ClassifyResult, messages)

        updated = evidence.model_copy(
            update={
                "classification": result.classification,
                "classification_rationale_th": result.classification_rationale_th,
            }
        )
        evidence_models.append(updated)
        classified_dicts.append(updated.model_dump(mode="json"))
        logger.debug(
            f"  {evidence.evidence_id}: {evidence.source_name} → {result.classification}"
        )

    # Persist classified evidence to Postgres
    repo = EvidenceRepository()
    await repo.bulk_insert(evidence_models)

    # Embed and upsert into Qdrant for Stage 3 retrieval
    if evidence_models:
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

    state["classified_evidence"] = classified_dicts
    state["current_stage"] = "stakeholder_needs"
    return state
