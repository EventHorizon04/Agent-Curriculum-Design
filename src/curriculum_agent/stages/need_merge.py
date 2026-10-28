"""Agent 2's merge step: fold Needs that ask for one capability into one Need.

The duplicate check used to run inside `plo_synthesis`, which drafted one PLO
from each fold. It now runs here, right after the Needs are written, so the
designer reviews merged Needs at the Need checkpoint and `plo_synthesis` never
sees a duplicate. `need_dedup` still decides *which* Needs are one capability;
this module builds what they become.

A merged Need is a new row. Its originals are stored with `merged_into` pointing
at it, never deleted, so the designer can split a merge back (spec section 4) and
every evidence trail survives: the merged Need's `member_skill_ids` and
`source_evidence_ids` are the union of its originals', not just of the skills its
sentence was written from. Those are the **top skills** — the highest
`importance_score` ones, at most `TOP_SKILL_CAP` — because a sentence cannot
carry thirty names, and they are what the designer sees as the Need's skill tags.

Everything else about the merged Need is recomputed from the pooled member
skills by the functions that score a stored skill group (`score_members`,
`group_bloom`), not taken as the max of the originals: a capability asked for by
more voices should rank higher.

The step can only fold. When the sentence for a group cannot be written the
group stays unmerged and its originals stay active — a failure never costs a
Need and never ships a `[ต้องทบทวน]` merged one.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from functools import partial

from loguru import logger

from curriculum_agent.concurrency import gather_bounded
from curriculum_agent.config import settings
from curriculum_agent.llm import complete_need_combination
from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    Need,
    ProgramMetadata,
)
from curriculum_agent.prompts.merged_need import build_merged_need_prompt
from curriculum_agent.prompts.program_context import build_program_context_th
from curriculum_agent.stages.need_dedup import FoldGroup, find_duplicate_groups
from curriculum_agent.stages.need_grouping import (
    MAX_CORE_PLOS,
    MIN_CORE_AFTER_MERGE,
    group_bloom,
    is_in_scope,
    is_unwritten_need,
    merge_bloom,
    normalize_need_name,
)
from curriculum_agent.stages.need_statement import (
    STATEMENT_MAX_TOKENS,
    STATEMENT_REASONING_MAX_TOKENS,
    NeedStatement,
)
from curriculum_agent.stages.skill_grouping import score_members

# How many of a merged Need's pooled skills its sentence is written from and its
# `top_skill_ids` keep. The designer asked for 5-7; seven is the cap.
TOP_SKILL_CAP = 7

# Instructor attempts in total, as for any other Need sentence.
_ATTEMPTS = 3

_TAG_ORDER = (
    KSECCategory.K,
    KSECCategory.S,
    KSECCategory.E,
    KSECCategory.C,
    KSECCategory.EC,
)


def rank_top_skills(skills: list[ExtractedSkill]) -> list[ExtractedSkill]:
    """The pooled skills a merged Need is written from, best first, at most `TOP_SKILL_CAP`.

    Rows sharing a normalised name collapse to the one with the highest
    `importance_score`. Today such rows always carry the same score
    (`_compute_skill_importance` works per normalised name across the program), so
    keeping the higher is a guard, not a branch that fires. Ties are broken by
    the normalised name so the order is reproducible.
    """
    best: dict[str, ExtractedSkill] = {}
    for skill in skills:
        key = normalize_need_name(skill.skill_name_th)
        if not key:
            continue
        kept = best.get(key)
        if kept is None or skill.importance_score > kept.importance_score:
            best[key] = skill
    ranked = sorted(best.items(), key=lambda item: (-item[1].importance_score, item[0]))
    return [skill for _, skill in ranked[:TOP_SKILL_CAP]]


def pooled_frequencies(pooled: list[ExtractedSkill], top: list[ExtractedSkill]) -> list[int]:
    """How many pooled member rows collapsed into each top skill, in `top` order.

    The same figure `SkillGroup.skill_frequencies` carries for a stored group, so
    the merged-Need prompt can weigh by frequency the way the per-group one does.
    """
    counts: dict[str, int] = {}
    for skill in pooled:
        key = normalize_need_name(skill.skill_name_th)
        counts[key] = counts.get(key, 0) + 1
    return [counts[normalize_need_name(s.skill_name_th)] for s in top]


def _demand_order(needs: Sequence[Need]) -> list[Need]:
    """Most-demanded first, `need_id` breaking ties so the order is reproducible."""
    return sorted(needs, key=lambda n: (-n.demand_score, n.need_id))


def build_units(needs: list[Need], folds: Sequence[FoldGroup]) -> list[list[Need]]:
    """What the core count is taken over: each fold as one unit, every other Need alone."""
    folded = {n.need_id for fold in folds for n in fold.needs}
    units = [_demand_order(fold.needs) for fold in folds]
    units += [[n] for n in needs if n.need_id not in folded]
    return units


def _core_members(fold: FoldGroup) -> int:
    return sum(1 for n in fold.needs if not n.is_optional)


def core_slot_count(units: list[list[Need]]) -> int:
    """Core outcomes these units would become, after the ceiling.

    A unit is optional only when every member is — the rule `validate_and_build`
    applies to the PLO the unit becomes.
    """
    return min(sum(1 for u in units if not all(n.is_optional for n in u)), MAX_CORE_PLOS)


def enforce_merge_floor(needs: list[Need], folds: Sequence[FoldGroup]) -> list[FoldGroup]:
    """Unfold groups until the core count reaches the merge floor.

    A set that starts below the floor is not blocked: every fold that would shrink
    it is unfolded, the loop runs out of candidates, and the set stays as it was.
    Lowest top-member demand goes first, because the most-demanded outcomes are
    the ones the numbering and the report lead with. Only a fold with two or more
    core members lowers the count, so only those are ever unfolded.
    """
    kept = list(folds)
    while core_slot_count(build_units(needs, kept)) < MIN_CORE_AFTER_MERGE:
        lowering = [f for f in kept if _core_members(f) >= 2]
        if not lowering:
            break
        victim = min(
            lowering,
            key=lambda f: (
                _demand_order(f.needs)[0].demand_score,
                _demand_order(f.needs)[0].need_id,
            ),
        )
        kept.remove(victim)
        logger.warning(
            f"need_merge: unfolded {', '.join(n.need_id for n in victim.needs)} — "
            f"folding it would leave fewer than {MIN_CORE_AFTER_MERGE} core Needs (floor)"
        )
    return kept


def _pooled_bloom(members: list[ExtractedSkill]) -> BloomLevel:
    """`group_bloom` over the pooled skills, one entry per normalised name.

    A name's level is the highest over its rows (`merge_bloom`, the one place that
    rule still holds: rows of one skill) and its weight the row count — the same
    inputs `build_skill_groups` hands `group_bloom` for a stored group.
    """
    by_name: dict[str, list[ExtractedSkill]] = {}
    for m in members:
        by_name.setdefault(normalize_need_name(m.skill_name_th), []).append(m)
    levels = [merge_bloom(m.bloom_level for m in rows) for rows in by_name.values()]
    return group_bloom(levels, [len(rows) for rows in by_name.values()])


async def _write_merged(
    program_id: str,
    fold: FoldGroup,
    skills_by_id: dict[str, ExtractedSkill],
    stakeholder_type_by_evidence: dict[str, str],
    program_context: str | None,
) -> Need | None:
    """The merged Need for one fold, or None when it cannot be written."""
    originals = _demand_order(fold.needs)
    member_ids = list(dict.fromkeys(sid for n in originals for sid in n.member_skill_ids))
    pooled = [skills_by_id[sid] for sid in member_ids if sid in skills_by_id]
    if not pooled:
        logger.warning(
            f"need_merge: no member skills on record for {[n.need_id for n in originals]} — "
            "left unmerged"
        )
        return None
    top = rank_top_skills(pooled)
    if not top:
        # Every pooled name normalised to "", so there is nothing to write a
        # sentence from; the same outcome as having no pooled skills.
        logger.warning(
            f"need_merge: no usable skill names for {[n.need_id for n in originals]} — "
            "left unmerged"
        )
        return None
    tags = [t for t in _TAG_ORDER if any(t in n.ksec_categories for n in originals)]
    bloom = _pooled_bloom(pooled)
    try:
        written = await complete_need_combination(
            NeedStatement,
            build_merged_need_prompt(
                [s.skill_name_th for s in top],
                [t.value for t in tags],
                bloom.value,
                fold.reason_th,
                program_context=program_context,
                skill_frequencies=pooled_frequencies(pooled, top),
            ),
            max_retries=_ATTEMPTS,
            max_tokens=STATEMENT_MAX_TOKENS,
            reasoning_max_tokens=STATEMENT_REASONING_MAX_TOKENS,
        )
    except Exception as exc:
        logger.warning(
            f"need_merge: sentence for {[n.need_id for n in originals]} failed, "
            f"left unmerged: {exc}"
        )
        return None
    stats = score_members(pooled, stakeholder_type_by_evidence)
    return Need(
        need_id=str(uuid.uuid4()),
        program_id=program_id,
        statement_th=written.statement_th,
        statement_en=written.statement_en,
        rationale_th=written.rationale_th,
        ksec_categories=tags,
        bloom_level=bloom,
        member_skill_ids=member_ids,
        source_evidence_ids=sorted({e for n in originals for e in n.source_evidence_ids}),
        stakeholder_coverage=stats.stakeholder_coverage,
        source_stakeholder_types=stats.stakeholder_types,
        freq=len(member_ids),
        demand_score=stats.demand_score,
        is_optional=stats.is_optional,
        classification_coverage=stats.classification_coverage,
        in_field_skill_count=stats.in_field_skill_count,
        graduate_capability_skill_count=stats.graduate_capability_skill_count,
        top_skill_ids=[s.skill_id for s in top],
        merged_from=[n.need_id for n in originals],
        merge_reason_th=fold.reason_th,
    )


def _core_count(needs: Sequence[Need]) -> int:
    """Active, non-optional Needs: what a PLO set's 6-10 band is counted over."""
    return sum(1 for n in needs if n.merged_into is None and not n.is_optional)


async def merge_duplicates(
    program_id: str,
    needs: list[Need],
    skills: list[ExtractedSkill],
    metadata: ProgramMetadata,
    stakeholder_type_by_evidence: dict[str, str],
) -> list[Need]:
    """The full list of Needs to store after folding duplicates.

    Originals in their existing order, with `merged_into` set on those that were
    merged, followed by the new merged Needs in fold order. Only in-scope, written
    Needs are offered to the duplicate check: `plo_synthesis` drops the others
    anyway, and merging one into an in-scope Need would smuggle it past the scope
    filter.
    """
    eligible = _demand_order([n for n in needs if is_in_scope(n) and not is_unwritten_need(n)])
    folds = await find_duplicate_groups(eligible, metadata)
    # A plain list (a test double) carries neither attribute: it is an answer.
    proposed = getattr(folds, "proposed", len(folds))
    dedup_call = getattr(folds, "call", "ok")
    accepted = len(folds)
    # Before any sentence is written, so an unfolded group costs no call.
    kept = enforce_merge_floor(eligible, folds) if folds else []
    merged: list[Need] = []
    if kept:
        program_context = build_program_context_th(metadata.model_dump())
        skills_by_id = {s.skill_id: s for s in skills}
        results = await gather_bounded(
            settings.llm_max_concurrency,
            [
                partial(
                    _write_merged,
                    program_id,
                    fold,
                    skills_by_id,
                    stakeholder_type_by_evidence,
                    program_context,
                )
                for fold in kept
            ],
        )
        merged = [m for m in results if m is not None]

    stored = list(needs)
    if merged:
        parent_of = {oid: m.need_id for m in merged for oid in m.merged_from}
        stored = [
            n.model_copy(update={"merged_into": parent_of[n.need_id]})
            if n.need_id in parent_of
            else n
            for n in needs
        ]
        stored += merged
    # One line per run, so the step's effect can be read off the log alone:
    # without it a run that proposed three groups and merged none looks the same
    # as one the model found nothing in, and `dedup_call` separates both from a
    # call that failed or was switched off (proposed=0 in all three).
    logger.info(
        f"need_merge: groups proposed={proposed} accepted={accepted} "
        f"unfolded_for_floor={accepted - len(kept)} "
        f"sentence_failed={len(kept) - len(merged)} merged={len(merged)} "
        f"multi_tag_merged={sum(1 for m in merged if len(m.ksec_categories) > 1)} "
        f"core_needs={_core_count(needs)}->{_core_count(stored)} dedup_call={dedup_call}"
    )
    return stored
