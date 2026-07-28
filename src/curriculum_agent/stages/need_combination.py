from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from curriculum_agent.data.repositories import NeedRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_heavy, complete_light
from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    Need,
    StakeholderType,
)
from curriculum_agent.prompts.cluster_skills import build_merge_to_target_prompt
from curriculum_agent.prompts.summarize_need import build_summarize_need_prompt
from curriculum_agent.stages.demand import WEIGHTED_CLASSES, compute_demand_score
from curriculum_agent.stages.llm_clustering import (
    MergeGroupsResponse,
    cluster_skill_names,
    validate_assignments,
)
from curriculum_agent.stages.need_grouping import (
    MIN_NEEDS,
    allocate_quota,
    bucket_by_ksec,
    dedupe_with_bloom_max,
    merge_bloom,
)


class _NeedStatement(BaseModel):
    statement_th: str = Field(min_length=1)
    statement_en: str | None = None


class _Group(BaseModel):
    """A candidate Need before its sentence is written."""

    ksec: KSECCategory
    skill_ids: list[str]
    evidence_ids: list[str]
    skill_names: list[str]
    bloom_level: BloomLevel
    demand_score: float
    is_optional: bool
    classification_coverage: dict[str, int]
    stakeholder_coverage: dict[str, int]


def _stakeholder_coverage(
    evidence_ids: list[str], classified: list[dict[str, Any]]
) -> dict[str, int]:
    coverage: dict[str, int] = {}
    wanted = set(evidence_ids)
    for item in classified:
        if item.get("evidence_id") in wanted:
            stype = str(item.get("stakeholder_type", "employer"))
            coverage[stype] = coverage.get(stype, 0) + 1
    return coverage


async def _build_groups(
    skills: list[ExtractedSkill],
    classified: list[dict[str, Any]],
    classification_by_evidence: dict[str, str],
    total_req_need: int,
) -> list[_Group]:
    """Cluster within each KSEC bucket and score every resulting group.

    Bucketing before clustering is what guarantees a group never mixes tags.
    """
    groups: list[_Group] = []
    for ksec, bucket in bucket_by_ksec(skills).items():
        names, index_groups, bloom_by_name = dedupe_with_bloom_max(bucket)
        if not names:
            continue
        logger.info(f"Clustering {len(names)} unique {ksec.value} skills")
        name_clusters = validate_assignments(
            [("", g) for g in await cluster_skill_names(names)], names
        )
        for _, name_indices in name_clusters:
            member_positions = sorted({p for ni in name_indices for p in index_groups[ni]})
            members = [bucket[p] for p in member_positions]
            evidence_ids = sorted({m.source_evidence_id for m in members})
            stk_coverage = _stakeholder_coverage(evidence_ids, classified)
            demand, is_optional, cls_coverage = compute_demand_score(
                evidence_ids, stk_coverage, total_req_need, classification_by_evidence
            )
            groups.append(
                _Group(
                    ksec=ksec,
                    skill_ids=[m.skill_id for m in members],
                    evidence_ids=evidence_ids,
                    skill_names=[names[ni] for ni in name_indices],
                    bloom_level=merge_bloom([bloom_by_name[names[ni]] for ni in name_indices]),
                    demand_score=demand,
                    is_optional=is_optional,
                    classification_coverage=cls_coverage,
                    stakeholder_coverage=stk_coverage,
                )
            )
    return groups


def _fuse(members: list[_Group]) -> _Group:
    """Combine several groups of the same KSEC bucket into one.

    Union rather than selection: a dropped group would take its evidence out of
    the pipeline, breaking the traceability the programme is assessed on.
    """
    head = members[0]
    skill_ids: list[str] = []
    skill_names: list[str] = []
    evidence: set[str] = set()
    for g in members:
        skill_ids.extend(g.skill_ids)
        skill_names.extend(g.skill_names)
        evidence |= set(g.evidence_ids)
    return head.model_copy(
        update={
            "skill_ids": skill_ids,
            "skill_names": skill_names,
            "evidence_ids": sorted(evidence),
            "bloom_level": merge_bloom([g.bloom_level for g in members]),
            "demand_score": max(g.demand_score for g in members),
            "is_optional": all(g.is_optional for g in members),
        }
    )


def _fuse_by_demand(bucket: list[_Group], limit: int) -> list[_Group]:
    """Fallback merge: fold the lowest-demand groups into the highest-demand ones.

    Used only when the LLM merge fails or returns the wrong group count. Purely
    arithmetic, so it always terminates at exactly `limit` groups.
    """
    ranked = sorted(bucket, key=lambda g: g.demand_score, reverse=True)
    keep, surplus = ranked[:limit], ranked[limit:]
    for i, extra in enumerate(surplus):
        target = i % limit
        keep[target] = _fuse([keep[target], extra])
    return keep


async def _merge_bucket(bucket: list[_Group], limit: int, ksec: KSECCategory) -> list[_Group]:
    """Reduce one bucket to `limit` groups, preferring a semantic merge.

    The heavy model decides which groups mean the same thing — that judgement is
    the reason this stage merges instead of truncating. Its output is validated
    for exactly-once coverage and for hitting the target count; anything else
    falls back to demand-ranked fusion so the stage cannot stall.
    """
    if len(bucket) <= limit:
        return bucket

    labels = [g.skill_names[0] for g in bucket]
    try:
        result = await complete_heavy(
            MergeGroupsResponse,
            build_merge_to_target_prompt(labels, limit),
            temperature=0,
        )
        merged = validate_assignments([("", g) for g in result.groups], labels)
        if len(merged) == limit:
            return [_fuse([bucket[i] for i in indices]) for _, indices in merged]
        logger.warning(
            f"{ksec.value} merge returned {len(merged)} groups, expected {limit} — "
            "falling back to demand-ranked fusion"
        )
    except Exception as exc:
        logger.warning(f"{ksec.value} merge call failed ({exc}) — falling back to demand ranking")

    return _fuse_by_demand(bucket, limit)


async def _apply_quota(groups: list[_Group]) -> list[_Group]:
    """Reduce core groups to the 6-10 policy, one bucket at a time.

    Optional (want-dominant) groups are exempt from the count, matching the
    project's optional-PLO rule, so only core groups are merged. Merging never
    crosses buckets, which is what keeps every Need single-tagged.
    """
    core = [g for g in groups if not g.is_optional]
    optional = [g for g in groups if g.is_optional]

    counts: dict[KSECCategory, int] = {}
    demand: dict[KSECCategory, float] = {}
    for g in core:
        counts[g.ksec] = counts.get(g.ksec, 0) + 1
        demand[g.ksec] = demand.get(g.ksec, 0.0) + g.demand_score

    quota = allocate_quota(counts, demand)
    kept: list[_Group] = []
    for ksec, limit in quota.items():
        in_bucket = [g for g in core if g.ksec == ksec]
        kept.extend(await _merge_bucket(in_bucket, limit, ksec))
    return kept + optional


async def run(state: AgentState) -> AgentState:
    """Stage 3b: distil extracted skills into 6-10 market-demand Needs."""
    program_id = state.get("program_id", "unknown")
    classified = state.get("classified_evidence", [])
    skill_dicts = state.get("extracted_skills", [])
    skills = [ExtractedSkill.model_validate(d) for d in skill_dicts]
    logger.info(f"Stage 3b: need_combination from {len(skills)} skills")

    if not skills:
        # Returns before delete_by_program on purpose, same reasoning as the
        # matching guard in skill_extraction: producing nothing must not destroy a
        # previous run's Needs.
        logger.warning("need_combination: no extracted skills — previous Needs left untouched")
        state["needs"] = []
        state["current_stage"] = "need_combination"
        return state

    classification_by_evidence = {
        str(d["evidence_id"]): str(d.get("classification", "unclassified"))
        for d in classified
        if d.get("evidence_id")
    }
    total_req_need = sum(1 for c in classification_by_evidence.values() if c in WEIGHTED_CLASSES)

    groups = await _build_groups(skills, classified, classification_by_evidence, total_req_need)
    groups = await _apply_quota(groups)

    evidence_text_by_id = {
        str(d["evidence_id"]): str(d.get("raw_text_th", ""))
        for d in classified
        if d.get("evidence_id")
    }

    needs: list[Need] = []
    for group in groups:
        samples = [evidence_text_by_id.get(eid, "") for eid in group.evidence_ids[:3]]
        try:
            written = await complete_light(
                _NeedStatement,
                build_summarize_need_prompt(group.skill_names, samples, group.ksec.value),
            )
        except Exception as exc:
            logger.warning(f"Need summarize failed for {group.ksec.value} group: {exc}")
            written = _NeedStatement(statement_th=", ".join(group.skill_names[:5]))

        needs.append(
            Need(
                need_id=str(uuid.uuid4()),
                program_id=program_id,
                statement_th=written.statement_th,
                statement_en=written.statement_en,
                ksec_category=group.ksec,
                bloom_level=group.bloom_level,
                member_skill_ids=group.skill_ids,
                source_evidence_ids=group.evidence_ids,
                stakeholder_coverage={
                    StakeholderType(k): v
                    for k, v in group.stakeholder_coverage.items()
                    if k in StakeholderType._value2member_map_
                },
                freq=len(group.skill_ids),
                demand_score=group.demand_score,
                is_optional=group.is_optional,
                classification_coverage=group.classification_coverage,
                sample_quotes_th=[s[:200] for s in samples if s][:3],
            )
        )

    core_count = sum(1 for n in needs if not n.is_optional)
    if core_count < MIN_NEEDS:
        logger.warning(
            f"need_combination produced only {core_count} core Needs (policy is {MIN_NEEDS}-10) — "
            "the designer must add more at the review checkpoint"
        )

    # Replace, don't accumulate — need_id is a fresh uuid per run and the
    # repository upserts by it. Also keeps member_skill_ids honest: the extraction
    # re-run just replaced the skill rows an old Need would point at.
    need_repo = NeedRepository()
    removed = await need_repo.delete_by_program(program_id)
    if removed:
        logger.info(f"Replaced {removed} Need row(s) from a previous run")
    await need_repo.bulk_insert(needs)
    state["needs"] = [n.model_dump(mode="json") for n in needs]
    state["current_stage"] = "need_combination"
    return state
