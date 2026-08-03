from __future__ import annotations

import uuid

from loguru import logger
from pydantic import BaseModel, Field

from curriculum_agent.data.repositories import NeedRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_light
from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    Need,
    StakeholderType,
)
from curriculum_agent.prompts.summarize_need import build_summarize_need_prompt
from curriculum_agent.stages.demand import (
    classification_coverage,
    compute_demand_score,
    is_optional_group,
    total_evidence_weight,
)
from curriculum_agent.stages.llm_clustering import cluster_skill_names, validate_assignments
from curriculum_agent.stages.need_grouping import (
    MIN_NEEDS,
    bucket_by_ksec,
    dedupe_with_bloom_max,
    merge_bloom,
    resolve_need_ksec,
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
    stakeholder_types: list[StakeholderType]


async def _build_groups(
    skills: list[ExtractedSkill],
    stakeholder_type_by_evidence: dict[str, str],
) -> list[_Group]:
    """Cluster within each KSEC bucket and score every resulting group.

    Bucketing before clustering is what guarantees a group never mixes tags; E and
    C share the EC bucket, and resolve_need_ksec hands back E or C when a group
    turns out to be purely one of them.
    """
    total_weight = total_evidence_weight(stakeholder_type_by_evidence)
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
            cls_coverage = classification_coverage([m.classification for m in members])
            stk_coverage: dict[str, int] = {}
            for m in members:
                key = m.source_stakeholder_type.value
                stk_coverage[key] = stk_coverage.get(key, 0) + 1
            # Enum declaration order puts external groups before internal ones,
            # which is the order the report shows them in.
            present = {m.source_stakeholder_type for m in members}
            groups.append(
                _Group(
                    ksec=resolve_need_ksec(members),
                    skill_ids=[m.skill_id for m in members],
                    evidence_ids=evidence_ids,
                    skill_names=[names[ni] for ni in name_indices],
                    bloom_level=merge_bloom([bloom_by_name[names[ni]] for ni in name_indices]),
                    demand_score=compute_demand_score(
                        evidence_ids, stakeholder_type_by_evidence, total_weight
                    ),
                    is_optional=is_optional_group(cls_coverage),
                    classification_coverage=cls_coverage,
                    stakeholder_coverage=stk_coverage,
                    stakeholder_types=[t for t in StakeholderType if t in present],
                )
            )
    return groups


async def run(state: AgentState) -> AgentState:
    """Stage 3b: distil extracted skills into at least 6 market-demand Needs."""
    program_id = state.get("program_id", "unknown")
    classified = state.get("classified_evidence", [])
    # Optional designer guidance for this run; absent on a plain re-run.
    note_th = state.get("designer_note")
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

    stakeholder_type_by_evidence = {
        str(d["evidence_id"]): str(d.get("stakeholder_type", "employer"))
        for d in classified
        if d.get("evidence_id")
    }

    groups = await _build_groups(skills, stakeholder_type_by_evidence)

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
                build_summarize_need_prompt(
                    group.skill_names, samples, group.ksec.value, note_th=note_th
                ),
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
                source_stakeholder_types=group.stakeholder_types,
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
            f"need_combination produced only {core_count} core Needs (policy is at least "
            f"{MIN_NEEDS}) — the designer must add more at the review checkpoint"
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
