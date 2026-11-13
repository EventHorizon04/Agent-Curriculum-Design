"""Agent 1: cluster the extracted skills into groups and store them.

Moved out of `need_combination`, which now only writes each stored group's
Need sentence. Bucketing, the graduate/institutional split, dedupe, cluster
targets, `validate_assignments` and scoring are unchanged; the result is a
`SkillGroup` list persisted for the next agent instead of an in-memory one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import uuid4

from loguru import logger

from curriculum_agent.concurrency import gather_bounded
from curriculum_agent.config import settings
from curriculum_agent.data.repositories import SkillGroupRepository, SkillRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.models import ExtractedSkill, KSECCategory, SkillGroup, StakeholderType
from curriculum_agent.prompts.program_context import build_program_context_th
from curriculum_agent.stages.demand import (
    build_scoring_corpus,
    classification_coverage,
    compute_demand_score,
    is_optional_group,
)
from curriculum_agent.stages.llm_clustering import cluster_skill_names, validate_assignments
from curriculum_agent.stages.need_grouping import (
    allocate_cluster_targets,
    bucket_by_ksec,
    dedupe_with_bloom_max,
    group_bloom,
    normalize_need_name,
    resolve_need_ksec,
)


@dataclass(frozen=True)
class MemberStats:
    """What a group of member skills adds up to, for a `SkillGroup` or a merged Need."""

    evidence_ids: list[str]
    demand_score: float
    is_optional: bool
    classification_coverage: dict[str, int]
    stakeholder_coverage: dict[StakeholderType, int]
    stakeholder_types: list[StakeholderType]
    in_field_skill_count: int
    graduate_capability_skill_count: int


def score_members(
    members: list[ExtractedSkill], stakeholder_type_by_evidence: dict[str, str]
) -> MemberStats:
    """Score one group of member skills.

    The one place these figures are computed: `build_skill_groups` calls it for
    every cluster and `need_merge` calls it for the pooled members of a merged
    Need, so a merged Need is scored by exactly the rules a stored group is.
    """
    evidence_ids = sorted({m.source_evidence_id for m in members})
    cls_coverage = classification_coverage([m.classification for m in members])
    stk_coverage: dict[StakeholderType, int] = {}
    for m in members:
        key = m.source_stakeholder_type
        stk_coverage[key] = stk_coverage.get(key, 0) + 1
    # Enum declaration order puts external groups before internal ones,
    # which is the order the report shows them in.
    present = {m.source_stakeholder_type for m in members}
    return MemberStats(
        evidence_ids=evidence_ids,
        demand_score=compute_demand_score(evidence_ids, stakeholder_type_by_evidence),
        # Distinct evidence items, not member rows: "how many stakeholders asked
        # for this" is a count of documents, and one document naming a
        # capability three ways is one stakeholder asking once.
        is_optional=is_optional_group(cls_coverage, len(evidence_ids)),
        classification_coverage=cls_coverage,
        stakeholder_coverage=stk_coverage,
        # Member rows, not distinct names. classify_skills already ORs the field
        # flag across every row sharing a name, and counting that way here would
        # push the number to the total whenever a name recurs, leaving the
        # designer a ratio that is always 8/8. The any rule these feed reads the
        # same either way; only the fraction shown at the checkpoint differs.
        in_field_skill_count=sum(1 for m in members if m.is_field_relevant),
        graduate_capability_skill_count=sum(1 for m in members if m.is_graduate_capability),
        stakeholder_types=[t for t in StakeholderType if t in present],
    )


async def build_skill_groups(
    program_id: str,
    skills: list[ExtractedSkill],
    stakeholder_type_by_evidence: dict[str, str],
    program_context: str | None = None,
) -> list[SkillGroup]:
    """Cluster within each KSEC bucket and score every resulting group.

    Bucketing before clustering is what guarantees a group never mixes tags; E and
    C share the EC bucket, and resolve_need_ksec hands back E or C when a group
    turns out to be purely one of them.

    `stakeholder_type_by_evidence` is built from the skills by the caller, so
    scoring stays inside what extraction produced.

    `program_context` is the program's field and degree level. It settles what an
    ambiguous skill name means before the names are grouped by it — it is intake
    metadata, not evidence, so nothing about a Need's evidence trail changes.

    Each bucket is clustered as **two populations**, split by whether the name is
    a graduate capability. Measured cause, not a guess: on the stored corpus the
    S bucket returned 17-21 groups against a target of 8, and the extra ones were
    not the model's judgement — it covered only part of the index list and
    `validate_assignments` filled the rest with one singleton per unassigned
    name, twelve and thirteen of them. Holding out the eleven rows extraction
    flagged `is_graduate_capability=False` dropped the mean group count from 15.7
    to 9.3 across three runs; a control of the same *length* that kept those
    eleven stayed at 15.0, so it is the content and not the list length. All
    eleven were administrator, faculty or institutional_direction rows, and
    extraction had judged every one correctly: designing the curriculum and
    raising the graduate employment rate are not things a graduate does. They do
    not belong to any competency the other names form, the model cannot place
    them, and the groups around them fragment. Ticket 16 has the numbers.

    **Nothing is dropped, and that distinction is the whole point.** Both
    populations are clustered and both become Needs, traceable as before; the
    scope guard still decides at `plo_synthesis` which ones can be drafted from.
    This is not the rule `cluster_skills` states against setting a skill aside —
    that one is about `is_field_relevant`, where off-field means market demand
    the program did not expect, which is real demand and must stay in the pool.
    `is_graduate_capability` is the other axis and says something different: not
    a thing a graduate does at all. Don't collapse the two axes here.

    The graduate flag is OR-ed across rows sharing a normalised name before the
    split, the same direction `classify_skills` reads `is_field_relevant`: one
    extraction call calling a name institutional does not outvote another that
    did not, and a name must land in exactly one population or dedupe would emit
    it twice.
    """
    groups: list[SkillGroup] = []
    if not settings.llm_cache_enabled:
        logger.info(
            "skill_grouping: LLM cache disabled (LLM_CACHE_ENABLED=false), "
            "every clustering call goes to the model"
        )
    buckets = bucket_by_ksec(skills)

    graduate_names = {
        normalize_need_name(s.skill_name_th) for s in skills if s.is_graduate_capability
    }

    def _split(bucket: list[ExtractedSkill]) -> tuple[list[ExtractedSkill], list[ExtractedSkill]]:
        grad = [s for s in bucket if normalize_need_name(s.skill_name_th) in graduate_names]
        return grad, [
            s for s in bucket if normalize_need_name(s.skill_name_th) not in graduate_names
        ]

    populations = {ksec: _split(bucket) for ksec, bucket in buckets.items()}
    deduped = {
        (ksec, is_grad): dedupe_with_bloom_max(pop)
        for ksec, pair in populations.items()
        for is_grad, pop in ((True, pair[0]), (False, pair[1]))
    }

    # Two allocations, and only the first is a budget. `MAX_CORE_PLOS` is a
    # ceiling on outcomes, and only a graduate capability can become one, so the
    # institutional side must not spend it — that is what let eleven names eat
    # the S bucket's eight slots.
    graduate_sizes = {ksec: len(deduped[(ksec, True)][0]) for ksec in buckets}
    institutional_sizes = {ksec: len(deduped[(ksec, False)][0]) for ksec in buckets}
    graduate_targets = allocate_cluster_targets(graduate_sizes)

    # The institutional side needs a number — without one the prompt falls back
    # to "typically 4-12 groups" — but it must not be a budget, and the first
    # version made it one by handing it `MAX_CORE_PLOS` too. Fourteen
    # institutional names were then asked for nine groups: no PLO slot was
    # spent, but the prompt was told to fragment, which is the very thing this
    # split exists to stop, just moved to the other population.
    #
    # Nothing downstream counts these groups, so the only thing their number has
    # to serve is the designer reading them at the checkpoint — and three themes
    # read better than nine near-singletons. So they are clustered to the same
    # GRANULARITY the graduate side is being asked for: names per group, carried
    # across. With no graduate names to take a ratio from there is nothing to
    # match, and the old behaviour is the honest fallback.
    granularity = (
        sum(graduate_sizes.values()) / sum(graduate_targets.values())
        if sum(graduate_targets.values())
        else 0.0
    )
    institutional_total = (
        max(1, round(sum(institutional_sizes.values()) / granularity)) if granularity else None
    )
    targets = {
        True: graduate_targets,
        False: allocate_cluster_targets(institutional_sizes, total=institutional_total)
        if institutional_total
        else allocate_cluster_targets(institutional_sizes),
    }
    if targets[True]:
        logger.info(
            "Need budget by competency domain: "
            + ", ".join(
                f"{k.value}={n}"
                for k, n in sorted(targets[True].items(), key=lambda kv: kv[0].value)
            )
        )

    # Every bucket's clustering call is independent of the others (each reads its
    # own names and target), so they run together under the shared ceiling and the
    # groups are then built in exactly the order the sequential loop used:
    # `gather_bounded` returns results in input order. `cluster_skill_names` takes
    # no semaphore of its own, so there is no nested acquisition to deadlock on.
    jobs: list[tuple[KSECCategory, bool, list[ExtractedSkill]]] = [
        (ksec, is_grad, bucket)
        for ksec, pair in populations.items()
        for is_grad, bucket in ((True, pair[0]), (False, pair[1]))
        if deduped[(ksec, is_grad)][0]
    ]

    def _cluster_factory(
        ksec: KSECCategory, is_grad: bool
    ) -> Callable[[], Awaitable[list[list[int]]]]:
        names = deduped[(ksec, is_grad)][0]
        target = targets[is_grad].get(ksec)
        side = "graduate" if is_grad else "institutional"

        async def _call() -> list[list[int]]:
            logger.info(
                f"Clustering {len(names)} unique {ksec.value} {side} skills into about {target}"
            )
            # The EC rule ("where the graduate shows it") was measured on
            # graduate-side skills only, so the institutional side gets no bucket.
            return await cluster_skill_names(
                names, target, program_context, ksec if is_grad else None
            )

        return _call

    raw_clusters = await gather_bounded(
        settings.llm_max_concurrency,
        [_cluster_factory(ksec, is_grad) for ksec, is_grad, _ in jobs],
        cancel_on_error=True,
    )

    for (ksec, is_grad, bucket), raw in zip(jobs, raw_clusters, strict=True):
        names, index_groups, bloom_by_name = deduped[(ksec, is_grad)]
        name_clusters = validate_assignments([("", g) for g in raw], names)
        for _, name_indices in name_clusters:
            member_positions = sorted({p for ni in name_indices for p in index_groups[ni]})
            members = [bucket[p] for p in member_positions]
            stats = score_members(members, stakeholder_type_by_evidence)
            # Stable, so names mentioned equally often keep clustering's order.
            ranked = sorted(name_indices, key=lambda ni: -len(index_groups[ni]))
            groups.append(
                SkillGroup(
                    group_id=str(uuid4()),
                    program_id=program_id,
                    is_graduate=is_grad,
                    ksec=resolve_need_ksec(members),
                    skill_ids=[m.skill_id for m in members],
                    evidence_ids=stats.evidence_ids,
                    skill_names=[names[ni] for ni in ranked],
                    skill_frequencies=[len(index_groups[ni]) for ni in ranked],
                    # What most of the group asks for, not its top member —
                    # see group_bloom for how the maximum inflated five PLOs.
                    bloom_level=group_bloom(
                        [bloom_by_name[names[ni]] for ni in ranked],
                        [len(index_groups[ni]) for ni in ranked],
                    ),
                    demand_score=stats.demand_score,
                    is_optional=stats.is_optional,
                    classification_coverage=stats.classification_coverage,
                    stakeholder_coverage=stats.stakeholder_coverage,
                    in_field_skill_count=stats.in_field_skill_count,
                    graduate_capability_skill_count=stats.graduate_capability_skill_count,
                    stakeholder_types=stats.stakeholder_types,
                )
            )
    return groups


async def run(state: AgentState) -> AgentState:
    """Stage 3a: cluster extracted skills into stored groups."""
    program_id = state.get("program_id", "unknown")
    program_context = build_program_context_th(state.get("metadata") or {})
    skill_dicts = state.get("extracted_skills")
    if skill_dicts is None:
        # Entered directly (a re-run, or a graph session after hand-run stages):
        # group the skills already on record rather than re-extracting.
        stored = await SkillRepository().list_by_program(program_id)
        skill_dicts = [sk.model_dump(mode="json") for sk in stored]
        logger.info(f"Stage 3a: loaded {len(skill_dicts)} skills from storage")
    skills = [ExtractedSkill.model_validate(d) for d in skill_dicts]
    logger.info(f"Stage 3a: skill_grouping from {len(skills)} skills")

    if not skills:
        # Raised before the delete so the previous run's groups survive; an empty
        # list is never answered by loading older rows.
        raise ValueError(
            "ยังไม่มีทักษะที่สกัดไว้สำหรับโปรแกรมนี้ กรุณารัน skill_extraction "
            "ให้ได้ทักษะก่อนจัดกลุ่มทักษะ (กลุ่มทักษะที่บันทึกไว้เดิมยังอยู่)"
        )

    # Same corpus skill_extraction scored importance against; see build_scoring_corpus.
    scoring_corpus = build_scoring_corpus(
        (s.source_evidence_id, s.source_stakeholder_type.value) for s in skills
    )
    groups = await build_skill_groups(program_id, skills, scoring_corpus, program_context)

    repo = SkillGroupRepository()
    removed = await repo.delete_by_program(program_id)
    if removed:
        logger.info(f"Replaced {removed} skill group row(s) from a previous run")
    await repo.bulk_insert(groups)
    state["skill_groups"] = [g.model_dump(mode="json") for g in groups]
    state["current_stage"] = "skill_grouping"
    return state
