from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import Literal

import numpy as np
from loguru import logger
from pydantic import BaseModel, Field
from qdrant_client.models import Distance, PointStruct, VectorParams
from sklearn.cluster import KMeans

from curriculum_agent.config import settings
from curriculum_agent.data.qdrant import SKILL_COLLECTION, get_qdrant
from curriculum_agent.data.repositories import (
    ClusterRepository,
    LLMCacheRepository,
    SkillRepository,
)
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_light
from curriculum_agent.models import (
    ExtractedSkill,
    SkillCluster,
    SkillType,
    StakeholderEvidence,
    StakeholderType,
)
from curriculum_agent.nlp.embedding import embed
from curriculum_agent.nlp.extraction import extract_keywords
from curriculum_agent.prompts.name_cluster import build_name_cluster_prompt

_EMBED_DIM = 1024


class _SkillItem(BaseModel):
    skill_name_th: str
    skill_name_en: str | None = None
    skill_type: Literal["knowledge", "psychomotor", "affective", "mixed"]
    is_subject_specific: bool
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)


class _ExtractedSkillsResponse(BaseModel):
    skills: list[_SkillItem]


class _ClusterNameResult(BaseModel):
    canonical_name_th: str
    canonical_name_en: str
    description_th: str
    skill_type: Literal["knowledge", "psychomotor", "affective", "mixed"]
    is_subject_specific: bool
    sample_quotes_th: list[str] = Field(default_factory=list)


_EXTRACT_SYSTEM = (
    "คุณเป็นผู้เชี่ยวชาญวิเคราะห์ทักษะจากข้อความ\n"
    "จากข้อความ evidence จงระบุทักษะที่ตลาดแรงงานต้องการ\n"
    "ตอบเป็น JSON object: { skills: [ { skill_name_th, skill_name_en, "
    "skill_type (knowledge|psychomotor|affective|mixed), "
    "is_subject_specific, confidence } ] }\n"
    "สกัดไม่เกิน 8 ทักษะต่อข้อความ เน้นทักษะที่วัดได้จริง"
)


async def _ensure_skill_collection() -> None:
    client = get_qdrant()
    existing = await client.get_collections()
    names = {c.name for c in existing.collections}
    if SKILL_COLLECTION not in names:
        await client.create_collection(
            collection_name=SKILL_COLLECTION,
            vectors_config=VectorParams(size=_EMBED_DIM, distance=Distance.COSINE),
        )


def _compute_demand_score(
    source_evidence_ids: list[str],
    stakeholder_coverage: dict,
    total_evidence: int,
) -> float:
    freq = len(set(source_evidence_ids)) / max(total_evidence, 1)
    breadth = len(stakeholder_coverage) / max(len(StakeholderType), 1)
    return round(min(freq * 0.6 + breadth * 0.4, 1.0), 4)


async def run(state: AgentState) -> AgentState:
    """Stage 2: extract skills from evidence, cluster with KMeans, name clusters with LLM."""
    classified = state.get("classified_evidence", [])
    program_id = state.get("program_id", "unknown")
    logger.info(f"Stage 2: skill_extraction from {len(classified)} evidence items")

    # --- Step 1: LLM skill extraction per evidence item (cache-first) ---
    raw_skills: list[dict] = []
    evidence_texts: dict[str, str] = {}
    _cache = LLMCacheRepository()

    for item_dict in classified:
        evidence = StakeholderEvidence.model_validate(item_dict)
        evidence_texts[evidence.evidence_id] = evidence.raw_text_th

        text_slice = evidence.raw_text_th[:1200]
        cache_key = hashlib.sha256(
            f"{text_slice}\x00{settings.light_model}".encode()
        ).hexdigest()

        result: _ExtractedSkillsResponse | None = None
        cached = await _cache.get(cache_key)
        if cached is not None and cached[0] == settings.light_model:
            result = _ExtractedSkillsResponse.model_validate_json(cached[1])
            logger.debug(f"Cache hit for evidence {evidence.evidence_id}")
        else:
            messages = [
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": text_slice},
            ]
            try:
                result = await complete_light(_ExtractedSkillsResponse, messages)
                await _cache.set(cache_key, settings.light_model, result.model_dump_json())
            except Exception as exc:
                logger.warning(f"LLM skill extraction failed for {evidence.evidence_id}: {exc}")

        if result is not None:
            for sk in result.skills:
                raw_skills.append({
                    **sk.model_dump(mode="json"),
                    "evidence_id": evidence.evidence_id,
                    "stakeholder_type": evidence.stakeholder_type.value,
                })

    # --- Step 2: KeyBERT backup signal ---
    for eid, text in evidence_texts.items():
        kw_pairs = extract_keywords(text, top_n=5)
        for kw, score in kw_pairs:
            # Find stakeholder type for this evidence
            stk_type = next(
                (
                    d["stakeholder_type"]
                    for d in classified
                    if d.get("evidence_id") == eid
                ),
                "employer",
            )
            raw_skills.append({
                "skill_name_th": kw,
                "skill_name_en": None,
                "skill_type": "knowledge",
                "is_subject_specific": True,
                "confidence": float(score),
                "evidence_id": eid,
                "stakeholder_type": stk_type,
                "extraction_method": "keybert",
            })

    if not raw_skills:
        logger.warning("Stage 2: no skills extracted — returning empty clusters")
        state["extracted_skills"] = []
        state["skill_clusters"] = []
        state["current_stage"] = "skill_extraction"
        return state

    # --- Step 3: Build ExtractedSkill objects and embed ---
    extracted: list[ExtractedSkill] = []
    for s in raw_skills:
        skill_id = str(uuid.uuid4())
        extracted.append(
            ExtractedSkill(
                skill_id=skill_id,
                program_id=program_id,
                skill_name_th=s["skill_name_th"],
                skill_name_en=s.get("skill_name_en"),
                skill_type=SkillType(s.get("skill_type", "knowledge")),
                is_subject_specific=s.get("is_subject_specific", True),
                source_evidence_id=s["evidence_id"],
                extraction_method=s.get("extraction_method", "llm"),
                confidence=s.get("confidence", 0.8),
            )
        )

    skill_texts = [s.skill_name_th for s in extracted]
    vectors = await asyncio.to_thread(embed, skill_texts)

    # --- Step 4: KMeans clustering ---
    n_skills = len(extracted)
    n_clusters = max(1, min(n_skills, max(4, min(12, n_skills // 3))))
    matrix = np.array(vectors, dtype=np.float32)

    # TODO: consider HDBSCAN or density-based clustering
    # to avoid forcing all skills into clusters
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto")
    labels = kmeans.fit_predict(matrix)

    # --- Step 5 & 6: Name clusters via LLM and compute demand_score ---
    clusters: list[SkillCluster] = []
    total_evidence_count = len(classified)

    for cluster_idx in range(n_clusters):
        member_indices = [i for i, lbl in enumerate(labels) if lbl == cluster_idx]
        if not member_indices:
            continue

        member_skills = [extracted[i] for i in member_indices]
        source_eids = list({s.source_evidence_id for s in member_skills})

        # Build stakeholder_coverage
        stk_coverage: dict[str, int] = {}
        for item_dict in classified:
            if item_dict.get("evidence_id") in source_eids:
                stype = item_dict.get("stakeholder_type", "employer")
                stk_coverage[stype] = stk_coverage.get(stype, 0) + 1

        sample_texts = [
            evidence_texts.get(eid, "")
            for eid in source_eids[:3]
        ]
        kw_list = [s.skill_name_th for s in member_skills]

        try:
            naming = await complete_light(
                _ClusterNameResult,
                build_name_cluster_prompt(kw_list, sample_texts),
            )
        except Exception as exc:
            logger.warning(f"Cluster {cluster_idx} naming failed: {exc}")
            naming = _ClusterNameResult(
                canonical_name_th=f"กลุ่มทักษะ {cluster_idx + 1}",
                canonical_name_en=f"Skill Cluster {cluster_idx + 1}",
                description_th=", ".join(kw_list[:5]),
                skill_type="knowledge",
                is_subject_specific=True,
            )

        demand = _compute_demand_score(
            source_eids, stk_coverage, total_evidence_count
        )

        # Filter stakeholder coverage to valid enum values
        filtered_coverage = {
            StakeholderType(k): v
            for k, v in stk_coverage.items()
            if k in StakeholderType._value2member_map_
        }
        cluster = SkillCluster(
            cluster_id=str(uuid.uuid4()),
            program_id=program_id,
            canonical_name_th=naming.canonical_name_th,
            canonical_name_en=naming.canonical_name_en,
            description_th=naming.description_th,
            skill_type=SkillType(naming.skill_type),
            is_subject_specific=naming.is_subject_specific,
            member_skill_ids=[s.skill_id for s in member_skills],
            source_evidence_ids=source_eids,
            stakeholder_coverage=filtered_coverage,
            demand_score=demand,
            is_common_need=demand > 0.4,
            sample_quotes_th=naming.sample_quotes_th[:5],
        )
        clusters.append(cluster)

    # Persist skills and clusters to Postgres
    await SkillRepository().bulk_insert(extracted)
    repo = ClusterRepository()
    await repo.bulk_insert(clusters)

    # Upsert cluster centroids to Qdrant
    await _ensure_skill_collection()
    client = get_qdrant()
    centroid_vecs = kmeans.cluster_centers_.tolist()
    points = [
        PointStruct(
            id=abs(hash(c.cluster_id)) % (2**63),
            vector=centroid_vecs[i],
            payload={
                "cluster_id": c.cluster_id,
                "program_id": c.program_id,
                "canonical_name_th": c.canonical_name_th,
                "demand_score": c.demand_score,
                "is_common_need": c.is_common_need,
            },
        )
        for i, c in enumerate(clusters)
        if i < len(centroid_vecs)
    ]
    if points:
        await client.upsert(collection_name=SKILL_COLLECTION, points=points)

    state["extracted_skills"] = [s.model_dump(mode="json") for s in extracted]
    state["skill_clusters"] = [c.model_dump(mode="json") for c in clusters]
    state["current_stage"] = "skill_extraction"
    return state
