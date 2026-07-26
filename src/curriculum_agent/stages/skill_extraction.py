from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field, field_validator

from curriculum_agent.config import settings
from curriculum_agent.data.repositories import (
    ClusterRepository,
    LLMCacheRepository,
    SkillRepository,
)
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_light
from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    SkillCluster,
    SkillType,
    StakeholderEvidence,
    StakeholderType,
)
from curriculum_agent.prompts.classify_cluster_bloom import build_cluster_bloom_prompt
from curriculum_agent.prompts.extract_skills import build_extract_skills_prompt
from curriculum_agent.prompts.name_cluster import build_name_cluster_prompt
from curriculum_agent.stages.demand import WEIGHTED_CLASSES, compute_demand_score
from curriculum_agent.stages.llm_clustering import cluster_skill_names, dedupe_names

_WS_RE = re.compile(r"\s+")

# Minimum length for a quote to count as evidence. Thai has no inter-word
# spaces, so character count is the available proxy for "this is a phrase, not
# a stray glyph". Below this, a span is so likely to appear in any Thai text by
# chance that matching it proves nothing about whether the skill was invented.
# Tunable: watch the logged drop rate and raise or lower it against real data.
_MIN_SPAN_CHARS = 12


def normalize_for_match(text: str) -> str:
    """Collapse whitespace, trim, lowercase — for substring comparison only."""
    return _WS_RE.sub(" ", text).strip().lower()


def is_grounded(span_th: str, evidence_text: str) -> bool:
    """True when `span_th` really occurs in `evidence_text` and is long enough
    to prove it, not merely disprove nothing.

    Verifies the model quoted rather than invented. Whitespace-insensitive so a
    re-spaced but genuine quote still passes; anything the evidence does not
    contain fails, and the skill is dropped by the caller. Spans shorter than
    `_MIN_SPAN_CHARS` (after normalisation) are rejected outright, since a
    single character or punctuation mark occurs in almost any real evidence
    text by chance and would otherwise pass without proving the quote is real.
    """
    span = normalize_for_match(span_th)
    if len(span) < _MIN_SPAN_CHARS:
        return False
    return span in normalize_for_match(evidence_text)


class _SkillItem(BaseModel):
    skill_name_th: str = Field(min_length=1)
    skill_name_en: str | None = None
    ksec_category: Literal["K", "GS", "SS", "C", "E"]
    bloom_level: Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]
    evidence_span_th: str = Field(min_length=_MIN_SPAN_CHARS)
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)

    @field_validator("skill_name_th", "evidence_span_th", mode="before")
    @classmethod
    def _strip_text(cls, v: object) -> object:
        """Strip before min_length runs, so a whitespace-only value fails
        validation (Instructor reasks) instead of passing as a non-empty string."""
        return v.strip() if isinstance(v, str) else v


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


def _compute_skill_importance(
    raw_skills: list[dict[str, Any]],
    classified: list[dict[str, Any]],
    classification_by_evidence: dict[str, str],
    total_req_need_evidence: int,
) -> dict[str, float]:
    """Per-skill-name demand, computed before clustering.

    Same weighting as SkillCluster.demand_score (compute_demand_score from
    curriculum_agent.stages.demand), grouped by skill_name_th instead of
    cluster membership — every ExtractedSkill mention of the same name gets
    the same importance_score.
    """
    eids_by_name: dict[str, set[str]] = {}
    for s in raw_skills:
        eids_by_name.setdefault(s["skill_name_th"], set()).add(s["evidence_id"])

    scores: dict[str, float] = {}
    for name, eids in eids_by_name.items():
        stk_coverage: dict[str, int] = {}
        for item_dict in classified:
            if item_dict.get("evidence_id") in eids:
                stype = item_dict.get("stakeholder_type", "employer")
                stk_coverage[stype] = stk_coverage.get(stype, 0) + 1
        score, _, _ = compute_demand_score(
            list(eids), stk_coverage, total_req_need_evidence, classification_by_evidence
        )
        scores[name] = score
    return scores


async def run(state: AgentState) -> AgentState:
    """Stage 2: extract skills from evidence, cluster with the heavy LLM, name clusters."""
    classified = state.get("classified_evidence", [])
    program_id = state.get("program_id", "unknown")
    logger.info(f"Stage 2: skill_extraction from {len(classified)} evidence items")

    # --- Step 1: LLM skill extraction per evidence item (cache-first) ---
    raw_skills: list[dict[str, Any]] = []
    evidence_texts: dict[str, str] = {}
    dropped_ungrounded = 0
    dropped_too_short = 0
    dropped_not_found = 0
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
            messages = build_extract_skills_prompt(text_slice, evidence.classification)
            try:
                result = await complete_light(_ExtractedSkillsResponse, messages)
                await _cache.set(cache_key, settings.light_model, result.model_dump_json())
            except Exception as exc:
                logger.warning(f"LLM skill extraction failed for {evidence.evidence_id}: {exc}")

        if result is not None:
            for sk in result.skills:
                if not is_grounded(sk.evidence_span_th, evidence.raw_text_th):
                    dropped_ungrounded += 1
                    if len(normalize_for_match(sk.evidence_span_th)) < _MIN_SPAN_CHARS:
                        dropped_too_short += 1
                        reason = "span too short to prove anything"
                    else:
                        dropped_not_found += 1
                        reason = "quoted text not found in evidence"
                    logger.debug(
                        f"  dropped ungrounded skill '{sk.skill_name_th}' "
                        f"from {evidence.evidence_id} ({reason})"
                    )
                    continue
                raw_skills.append(
                    {
                        **sk.model_dump(mode="json"),
                        "evidence_id": evidence.evidence_id,
                        "stakeholder_type": evidence.stakeholder_type.value,
                    }
                )

    if dropped_ungrounded:
        total_seen = len(raw_skills) + dropped_ungrounded
        drop_rate = dropped_ungrounded / total_seen * 100
        logger.warning(
            f"Dropped {dropped_ungrounded}/{total_seen} ({drop_rate:.1f}%) skills failing "
            "the groundedness check: "
            f"{dropped_too_short} too-short (span below {_MIN_SPAN_CHARS} chars, likely "
            f"paraphrase/vague quote), {dropped_not_found} not-found in evidence "
            "(likely fabricated)"
        )
    state["dropped_ungrounded_count"] = dropped_ungrounded

    if not raw_skills:
        logger.warning("Stage 2: no skills extracted — returning empty clusters")
        state["extracted_skills"] = []
        state["skill_clusters"] = []
        state["current_stage"] = "skill_extraction"
        return state

    # --- Step 2: per-skill-name importance, then build ExtractedSkill objects ---
    classification_by_evidence: dict[str, str] = {
        str(d["evidence_id"]): str(d.get("classification", "unclassified"))
        for d in classified
        if d.get("evidence_id")
    }
    total_req_need = sum(1 for c in classification_by_evidence.values() if c in WEIGHTED_CLASSES)
    importance_by_name = _compute_skill_importance(
        raw_skills, classified, classification_by_evidence, total_req_need
    )

    extracted: list[ExtractedSkill] = []
    for s in raw_skills:
        skill_id = str(uuid.uuid4())
        extracted.append(
            ExtractedSkill(
                skill_id=skill_id,
                program_id=program_id,
                skill_name_th=s["skill_name_th"],
                skill_name_en=s.get("skill_name_en"),
                ksec_category=KSECCategory(s["ksec_category"]),
                bloom_level=BloomLevel(s["bloom_level"]),
                evidence_span_th=s["evidence_span_th"],
                source_evidence_id=s["evidence_id"],
                extraction_method="llm",
                confidence=s.get("confidence", 0.8),
                importance_score=importance_by_name.get(s["skill_name_th"], 0.0),
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
    # classification_by_evidence / total_req_need already computed in Step 2.
    clusters: list[SkillCluster] = []

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

        demand, is_optional, cls_coverage = compute_demand_score(
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
