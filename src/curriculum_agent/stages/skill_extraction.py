from __future__ import annotations

import hashlib
import uuid
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field

from curriculum_agent.config import settings
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
from curriculum_agent.prompts.classify_cluster_bloom import build_cluster_bloom_prompt
from curriculum_agent.prompts.name_cluster import build_name_cluster_prompt
from curriculum_agent.stages.llm_clustering import cluster_skill_names, dedupe_names


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


class _ClusterBloomResult(BaseModel):
    bloom_level: (
        Literal["remember", "understand", "apply", "analyze", "evaluate", "create"] | None
    ) = None
    psychomotor_level: (
        Literal["imitate", "manipulate", "precise", "articulate", "naturalize"] | None
    ) = None
    krathwohl_level: (
        Literal["receiving", "responding", "valuing", "organization", "characterization"] | None
    ) = None
    is_subject_specific: bool


_EXTRACT_SYSTEM = (
    "คุณเป็นผู้เชี่ยวชาญวิเคราะห์ทักษะจากข้อความ\n"
    "จากข้อความ evidence จงระบุทักษะที่ตลาดแรงงานต้องการ\n"
    "ตอบเป็น JSON object: { skills: [ { "
    "skill_name_th: ชื่อทักษะภาษาไทย, "
    "skill_name_en: ชื่อทักษะภาษาอังกฤษมาตรฐาน "
    "(เช่น 'Python', 'Data Analysis', 'Communication') ห้ามเว้นว่าง, "
    "skill_type (knowledge|psychomotor|affective|mixed), "
    "is_subject_specific, confidence } ] }\n"
    "สกัดไม่เกิน 8 ทักษะต่อข้อความ เน้นทักษะที่วัดได้จริง"
)


_WEIGHTED_CLASSES = {"requirement", "need", "unclassified"}


def _compute_demand_score(
    source_evidence_ids: list[str],
    stakeholder_coverage: dict[str, int],
    total_req_need_evidence: int,
    classification_by_evidence: dict[str, str],
) -> tuple[float, bool, dict[str, int]]:
    """Score from requirement+need evidence only; want evidence carries zero weight.

    Returns (demand_score, is_optional, classification_coverage).
    """
    coverage: dict[str, int] = {}
    weighted = 0
    want = 0
    for eid in set(source_evidence_ids):
        cls = classification_by_evidence.get(eid, "unclassified")
        coverage[cls] = coverage.get(cls, 0) + 1
        if cls in _WEIGHTED_CLASSES:
            weighted += 1
        elif cls == "want":
            want += 1

    freq = weighted / max(total_req_need_evidence, 1)
    breadth = len(stakeholder_coverage) / max(len(StakeholderType), 1)
    score = round(min(freq * 0.6 + breadth * 0.4, 1.0), 4)
    is_optional = want > weighted
    return score, is_optional, coverage


async def run(state: AgentState) -> AgentState:
    """Stage 2: extract skills from evidence, cluster with the heavy LLM, name clusters."""
    classified = state.get("classified_evidence", [])
    program_id = state.get("program_id", "unknown")
    logger.info(f"Stage 2: skill_extraction from {len(classified)} evidence items")

    # --- Step 1: LLM skill extraction per evidence item (cache-first) ---
    raw_skills: list[dict[str, Any]] = []
    evidence_texts: dict[str, str] = {}
    _cache = LLMCacheRepository()

    for item_dict in classified:
        evidence = StakeholderEvidence.model_validate(item_dict)
        evidence_texts[evidence.evidence_id] = evidence.raw_text_th

        text_slice = evidence.raw_text_th[:1200]
        cache_key = hashlib.sha256(
            f"{text_slice}\x00{evidence.classification}\x00{settings.light_model}".encode()
        ).hexdigest()

        result: _ExtractedSkillsResponse | None = None
        cached = await _cache.get(cache_key)
        if cached is not None and cached[0] == settings.light_model:
            result = _ExtractedSkillsResponse.model_validate_json(cached[1])
            logger.debug(f"Cache hit for evidence {evidence.evidence_id}")
        else:
            evidence_context = f"[ประเภทหลักฐาน: {evidence.classification}]\n{text_slice}"
            messages = [
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": evidence_context},
            ]
            try:
                result = await complete_light(_ExtractedSkillsResponse, messages)
                await _cache.set(cache_key, settings.light_model, result.model_dump_json())
            except Exception as exc:
                logger.warning(f"LLM skill extraction failed for {evidence.evidence_id}: {exc}")

        if result is not None:
            for sk in result.skills:
                raw_skills.append(
                    {
                        **sk.model_dump(mode="json"),
                        "evidence_id": evidence.evidence_id,
                        "stakeholder_type": evidence.stakeholder_type.value,
                    }
                )

    if not raw_skills:
        logger.warning("Stage 2: no skills extracted — returning empty clusters")
        state["extracted_skills"] = []
        state["skill_clusters"] = []
        state["current_stage"] = "skill_extraction"
        return state

    # --- Step 2: Build ExtractedSkill objects ---
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

    # --- Step 3: LLM clustering over deduped skill names ---
    unique_names, name_groups = dedupe_names([s.skill_name_th for s in extracted])
    logger.info(f"Clustering {len(unique_names)} unique skills via heavy model")
    unique_clusters = await cluster_skill_names(unique_names)
    member_indices_per_cluster = [
        sorted({orig for u in group for orig in name_groups[u]}) for group in unique_clusters
    ]

    # --- Step 4 & 5: Name clusters via LLM and compute demand_score ---
    clusters: list[SkillCluster] = []
    classification_by_evidence: dict[str, str] = {
        str(d["evidence_id"]): str(d.get("classification", "unclassified"))
        for d in classified
        if d.get("evidence_id")
    }
    total_req_need = sum(1 for c in classification_by_evidence.values() if c in _WEIGHTED_CLASSES)

    for cluster_idx, member_indices in enumerate(member_indices_per_cluster):
        member_skills = [extracted[i] for i in member_indices]
        source_eids = list({s.source_evidence_id for s in member_skills})

        # Build stakeholder_coverage
        stk_coverage: dict[str, int] = {}
        for item_dict in classified:
            if item_dict.get("evidence_id") in source_eids:
                stype = item_dict.get("stakeholder_type", "employer")
                stk_coverage[stype] = stk_coverage.get(stype, 0) + 1

        sample_texts = [evidence_texts.get(eid, "") for eid in source_eids[:3]]
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

        bloom_level: str | None = None
        psychomotor_level: str | None = None
        krathwohl_level: str | None = None
        is_specific = naming.is_subject_specific
        try:
            tag = await complete_light(
                _ClusterBloomResult,
                build_cluster_bloom_prompt(
                    naming.canonical_name_th, naming.description_th, kw_list, naming.skill_type
                ),
            )
            if naming.skill_type == "affective":
                krathwohl_level = tag.krathwohl_level
            elif naming.skill_type == "psychomotor":
                psychomotor_level = tag.psychomotor_level
            else:
                bloom_level = tag.bloom_level
            is_specific = tag.is_subject_specific
        except Exception as exc:
            logger.warning(f"Cluster {cluster_idx} Bloom tagging failed: {exc}")

        demand, is_optional, cls_coverage = _compute_demand_score(
            source_eids, stk_coverage, total_req_need, classification_by_evidence
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
            is_subject_specific=is_specific,
            member_skill_ids=[s.skill_id for s in member_skills],
            source_evidence_ids=source_eids,
            stakeholder_coverage=filtered_coverage,
            demand_score=demand,
            is_common_need=demand > 0.4 and not is_optional,
            is_optional=is_optional,
            classification_coverage=cls_coverage,
            sample_quotes_th=naming.sample_quotes_th[:5],
            bloom_level=bloom_level,
            psychomotor_level=psychomotor_level,
            krathwohl_level=krathwohl_level,
        )
        clusters.append(cluster)

    # Persist skills and clusters to Postgres
    await SkillRepository().bulk_insert(extracted)
    repo = ClusterRepository()
    await repo.bulk_insert(clusters)

    state["extracted_skills"] = [s.model_dump(mode="json") for s in extracted]
    state["skill_clusters"] = [c.model_dump(mode="json") for c in clusters]
    state["current_stage"] = "skill_extraction"
    return state
