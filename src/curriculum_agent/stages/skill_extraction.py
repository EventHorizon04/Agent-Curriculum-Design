from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

from curriculum_agent.config import settings
from curriculum_agent.data.repositories import LLMCacheRepository, SkillRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_light
from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    StakeholderEvidence,
)
from curriculum_agent.prompts.extract_skills import build_extract_skills_prompt
from curriculum_agent.stages.demand import WEIGHTED_CLASSES, compute_demand_score
from curriculum_agent.stages.need_grouping import merge_bloom, normalize_need_name

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


def _extraction_contract_fingerprint() -> str:
    """Short hash of everything that decides the SHAPE of a cached extraction.

    The LLM cache is keyed on the evidence text and the model, so before this
    existed a change to the response schema or the prompt left old entries
    matching. A stale payload was then replayed into the current schema and blew
    up the stage — which is exactly what happened when `evidence_span_th` was
    introduced and 18 cached rows still carried the pre-change fields.

    Deriving the fingerprint from the schema and the prompt rather than hand-
    maintaining a version integer means a future contributor cannot forget to
    bump it: change either one and the key changes with it.
    """
    schema = json.dumps(_ExtractedSkillsResponse.model_json_schema(), sort_keys=True)
    # The system message carries every instruction; only the user message varies
    # per evidence item, so an empty text is enough to capture the contract.
    system_prompt = build_extract_skills_prompt("", "")[0]["content"]
    return hashlib.sha256(f"{schema}\x00{system_prompt}".encode()).hexdigest()[:16]


_EXTRACTION_CONTRACT = _extraction_contract_fingerprint()


def _compute_skill_importance(
    raw_skills: list[dict[str, Any]],
    classified: list[dict[str, Any]],
    classification_by_evidence: dict[str, str],
    total_req_need_evidence: int,
) -> dict[str, float]:
    """Per-skill-name demand, computed before Need grouping (a later stage).

    Same weighting as Need.demand_score (compute_demand_score from
    curriculum_agent.stages.demand), grouped by the same normalised name
    (normalize_need_name) that need_grouping.dedupe_with_bloom_max later
    collapses duplicates by — so two spellings of one skill that land in the
    same Need also get the same importance_score here. Keyed by normalised
    name; the caller must normalise before looking a score up.
    """
    eids_by_name: dict[str, set[str]] = {}
    for s in raw_skills:
        norm = normalize_need_name(s["skill_name_th"])
        eids_by_name.setdefault(norm, set()).add(s["evidence_id"])

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
    """Stage 2: extract skills from evidence via the light LLM (grounded, cache-first).

    Grouping into Needs is a separate stage (need_combination); this stage only
    extracts and persists ExtractedSkill rows.
    """
    classified = state.get("classified_evidence", [])
    program_id = state.get("program_id", "unknown")
    logger.info(f"Stage 2: skill_extraction from {len(classified)} evidence items")

    # --- Step 1: LLM skill extraction per evidence item (cache-first) ---
    raw_skills: list[dict[str, Any]] = []
    dropped_ungrounded = 0
    dropped_too_short = 0
    dropped_not_found = 0
    collapsed_duplicates = 0
    _cache = LLMCacheRepository()

    for item_dict in classified:
        evidence = StakeholderEvidence.model_validate(item_dict)

        text_slice = evidence.raw_text_th[:1200]
        cache_key = hashlib.sha256(
            f"{text_slice}\x00{evidence.classification}\x00{settings.light_model}"
            f"\x00{_EXTRACTION_CONTRACT}".encode()
        ).hexdigest()

        result: _ExtractedSkillsResponse | None = None
        cached = await _cache.get(cache_key)
        if cached is not None and cached[0] == settings.light_model:
            try:
                result = _ExtractedSkillsResponse.model_validate_json(cached[1])
                logger.debug(f"Cache hit for evidence {evidence.evidence_id}")
            except ValidationError as exc:
                # Belt-and-braces: the contract fingerprint should already have
                # missed on any incompatible entry. Treat a surviving one as a
                # miss and fall through to a fresh extraction rather than failing
                # the stage — or silently losing the item — over a cache artefact.
                logger.warning(f"Unusable cache entry for {evidence.evidence_id}: {exc}")

        if result is None:
            messages = build_extract_skills_prompt(text_slice, evidence.classification)
            try:
                result = await complete_light(_ExtractedSkillsResponse, messages)
                await _cache.set(cache_key, settings.light_model, result.model_dump_json())
            except Exception as exc:
                logger.warning(f"LLM skill extraction failed for {evidence.evidence_id}: {exc}")

        if result is not None:
            # Collapse repeated names within this one evidence item, keeping the
            # highest Bloom level (same rule as merge_bloom — the lower level is
            # implied by the higher). Everything else comes from the first
            # occurrence; the alternatives are equally arbitrary and the span and
            # confidence describe the same quoted phrase either way.
            #
            # Deduping is deliberately per-evidence, never across evidence items:
            # two sources naming the same capability are two mentions, and that is
            # precisely the signal Need.freq and demand_score are built from.
            by_norm: dict[str, dict[str, Any]] = {}
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

                norm = normalize_need_name(sk.skill_name_th)
                row = {
                    **sk.model_dump(mode="json"),
                    "evidence_id": evidence.evidence_id,
                    "stakeholder_type": evidence.stakeholder_type.value,
                }
                kept = by_norm.get(norm)
                if kept is None:
                    by_norm[norm] = row
                    continue
                collapsed_duplicates += 1
                kept["bloom_level"] = merge_bloom(
                    [BloomLevel(kept["bloom_level"]), BloomLevel(row["bloom_level"])]
                ).value
                logger.debug(
                    f"  collapsed duplicate skill '{sk.skill_name_th}' "
                    f"within {evidence.evidence_id}"
                )
            raw_skills.extend(by_norm.values())

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
    if collapsed_duplicates:
        logger.info(
            f"Collapsed {collapsed_duplicates} duplicate skill name(s) named more than "
            "once by a single evidence item"
        )
    state["dropped_ungrounded_count"] = dropped_ungrounded

    if not raw_skills:
        # Returns before delete_by_program on purpose: a run that extracted
        # nothing (every call failed, or everything failed groundedness) must not
        # wipe a previous run's good rows. The stale rows stay visible and a
        # re-run replaces them once it actually produces something.
        logger.warning("Stage 2: no skills extracted — previous rows left untouched")
        state["extracted_skills"] = []
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
                importance_score=importance_by_name.get(
                    normalize_need_name(s["skill_name_th"]), 0.0
                ),
            )
        )

    # Replace, don't accumulate: skill_id is a fresh uuid per run and the
    # repository upserts by it, so without the delete a re-run leaves both sets in
    # the table and the Stage 3 skill table shows every skill twice.
    skill_repo = SkillRepository()
    removed = await skill_repo.delete_by_program(program_id)
    if removed:
        logger.info(f"Replaced {removed} skill row(s) from a previous run")
    await skill_repo.bulk_insert(extracted)

    state["extracted_skills"] = [s.model_dump(mode="json") for s in extracted]
    state["current_stage"] = "skill_extraction"
    return state
