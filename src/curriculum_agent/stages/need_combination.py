from __future__ import annotations

import uuid

from loguru import logger
from pydantic import BaseModel, Field, field_validator

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
from curriculum_agent.prompts.summarize_need import (
    MIN_STATEMENT_CHARS,
    build_summarize_need_prompt,
)
from curriculum_agent.stages.demand import (
    classification_coverage,
    compute_demand_score,
    is_optional_group,
)
from curriculum_agent.stages.llm_clustering import cluster_skill_names, validate_assignments
from curriculum_agent.stages.need_grouping import (
    MIN_NEEDS,
    bucket_by_ksec,
    dedupe_with_bloom_max,
    find_code_identifier,
    find_vague_phrase,
    looks_like_a_skill_list,
    merge_bloom,
    resolve_need_ksec,
)

# Instructor re-asks the model when _NeedStatement's validator raises, quoting
# the error back. Three attempts: the leak is sporadic, so a retry almost always
# clears it, and a group that still fails falls back to its skill names.
_STATEMENT_ATTEMPTS = 3

# Prefix on a Need whose sentence every attempt failed to write. Visible in the
# UI's Need list, which is where the designer decides what to fix.
_REVIEW_MARKER_TH = "[ต้องทบทวน]"


class _NeedStatement(BaseModel):
    statement_th: str = Field(min_length=1)
    statement_en: str | None = None

    @field_validator("statement_th")
    @classmethod
    def _reject_code_tokens(cls, statement: str) -> str:
        """Bounce a sentence carrying a code identifier back to the model.

        A light model tokenising Thai byte-by-byte occasionally emits a token
        from its code training instead of the Thai it was asked for — one stored
        Need read "...เป็นผู้ประกอบการ หน.getDefault รับฟังผู้บริหาร...", built
        from two clean skill names. Raising here is what makes Instructor retry
        with the failure quoted back, the same shape as the SMART retry loop.
        """
        found = find_code_identifier(statement)
        if found:
            raise ValueError(
                f"statement_th ต้องเป็นภาษาไทยล้วน พบข้อความที่เป็นโค้ด: '{found}' "
                "ห้ามใส่ชื่อฟังก์ชัน ชื่อตัวแปร หรือโค้ดในประโยค"
            )
        return statement

    @field_validator("statement_th")
    @classmethod
    def _require_plo_ready(cls, statement: str) -> str:
        """Reject the two shapes a Need cannot become a PLO from.

        plo_synthesis drafts exactly one PLO per Need and is handed nothing but
        this sentence. A placeholder ("ทักษะที่จำเป็นต่อการทำงาน") or a
        comma-joined skill list therefore does not merely weaken the PLO — it
        makes the synthesis model invent the capability, with no evidence behind
        what it invents. Raising here sends the group back through Instructor
        with the reason quoted, the same shape as the code-token guard above.
        """
        trimmed = statement.strip()
        if len(trimmed) < MIN_STATEMENT_CHARS:
            raise ValueError(
                f"statement_th สั้นเกินไป ({len(trimmed)} ตัวอักษร) ต้องยาวอย่างน้อย "
                f"{MIN_STATEMENT_CHARS} ตัวอักษร และระบุความสามารถ วัตถุของงาน "
                "และบริบทการทำงานให้ครบ"
            )
        if looks_like_a_skill_list(trimmed):
            raise ValueError(
                "statement_th เป็นการนำชื่อทักษะมาต่อกันด้วยจุลภาค "
                "ให้เขียนเป็นประโยคความต้องการของตลาดหนึ่งประโยค"
            )
        vague = find_vague_phrase(trimmed)
        if vague:
            raise ValueError(
                f"statement_th มีคำกว้างที่ไม่บอกเนื้อหา: '{vague}' ให้ระบุความสามารถและวัตถุของงานที่เจาะจงแทน"
            )
        return statement


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
    stakeholder_coverage: dict[StakeholderType, int]
    stakeholder_types: list[StakeholderType]


async def _build_groups(
    skills: list[ExtractedSkill],
    stakeholder_type_by_evidence: dict[str, str],
) -> list[_Group]:
    """Cluster within each KSEC bucket and score every resulting group.

    Bucketing before clustering is what guarantees a group never mixes tags; E and
    C share the EC bucket, and resolve_need_ksec hands back E or C when a group
    turns out to be purely one of them.

    `stakeholder_type_by_evidence` is built from the skills by the caller, so
    scoring stays inside what extraction produced.
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
            cls_coverage = classification_coverage([m.classification for m in members])
            stk_coverage: dict[StakeholderType, int] = {}
            for m in members:
                key = m.source_stakeholder_type
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
                    demand_score=compute_demand_score(evidence_ids, stakeholder_type_by_evidence),
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

    # Read off the skills, not off the evidence rows: this stage sees only what
    # extraction produced. That also moves the demand denominator to the weight of
    # the evidence that yielded at least one skill, which is the honest base for
    # "what share of the demand named this?" — an evidence item nobody extracted a
    # skill from expresses no demand for a Need to be a share of.
    stakeholder_type_by_evidence = {
        s.source_evidence_id: s.source_stakeholder_type.value for s in skills
    }

    groups = await _build_groups(skills, stakeholder_type_by_evidence)

    needs: list[Need] = []
    for group in groups:
        try:
            written = await complete_light(
                _NeedStatement,
                build_summarize_need_prompt(
                    group.skill_names,
                    group.ksec.value,
                    group.bloom_level.value,
                    note_th=note_th,
                ),
                max_retries=_STATEMENT_ATTEMPTS,
            )
        except Exception as exc:
            logger.warning(f"Need summarize failed for {group.ksec.value} group: {exc}")
            # Skill names the extractor already validated, minus any that a
            # manual entry could still have carried a code token into.
            names = [n for n in group.skill_names[:5] if not find_code_identifier(n)]
            if len(names) < len(group.skill_names[:5]):
                logger.warning("Dropped skill name(s) carrying a code token from the fallback")
            # A joined list is exactly what _require_plo_ready rejects, so the
            # fallback cannot pretend to be a usable Need. Marking it is what puts
            # it in front of the designer at the checkpoint instead of letting
            # plo_synthesis invent a PLO from a list of words.
            written = _NeedStatement.model_construct(
                statement_th=f"{_REVIEW_MARKER_TH} {', '.join(names) or group.ksec.value}"
            )

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
                stakeholder_coverage=group.stakeholder_coverage,
                source_stakeholder_types=group.stakeholder_types,
                freq=len(group.skill_ids),
                demand_score=group.demand_score,
                is_optional=group.is_optional,
                classification_coverage=group.classification_coverage,
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
