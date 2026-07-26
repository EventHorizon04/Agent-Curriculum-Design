from __future__ import annotations

import re
from collections.abc import Iterable

from loguru import logger

from curriculum_agent.models import BLOOM_ORDER, BloomLevel, ExtractedSkill, KSECCategory

# Project policy: 6-10 main Needs, which become 6-10 main PLOs one-to-one.
MIN_NEEDS = 6
MAX_NEEDS = 10

_WS_RE = re.compile(r"\s+")
_BLOOM_RANK = {level: i for i, level in enumerate(BLOOM_ORDER)}


def _normalize(name: str) -> str:
    return _WS_RE.sub(" ", name.strip()).lower()


def bucket_by_ksec(skills: list[ExtractedSkill]) -> dict[KSECCategory, list[ExtractedSkill]]:
    """Split skills into one bucket per KSEC tag, omitting empty buckets.

    Clustering runs inside a bucket and merging never crosses buckets, so a Need
    can never contain two different tags. This is what makes "tags must not mix"
    a structural guarantee instead of a rule someone has to remember.
    """
    buckets: dict[KSECCategory, list[ExtractedSkill]] = {}
    for skill in skills:
        buckets.setdefault(skill.ksec_category, []).append(skill)
    return buckets


def merge_bloom(levels: Iterable[BloomLevel]) -> BloomLevel:
    """Return the highest Bloom level present.

    The same capability described by two sources at different cognitive demands
    (remember vs analyze) is taught to the higher one — the lower is implied by it.
    """
    ordered = list(levels)
    if not ordered:
        raise ValueError("merge_bloom requires at least one Bloom level")
    return max(ordered, key=lambda lv: _BLOOM_RANK[lv])


def dedupe_with_bloom_max(
    skills: list[ExtractedSkill],
) -> tuple[list[str], list[list[int]], dict[str, BloomLevel]]:
    """Collapse duplicate skill names within one bucket.

    Returns (display_names, index_groups, bloom_by_display_name). `display_names`
    is sorted by normalized form so prompts and cache keys are deterministic
    regardless of input order; `index_groups[i]` lists the positions in `skills`
    that collapsed into `display_names[i]`.

    Names that normalize to an empty string (blank/whitespace-only) are skipped.
    This is a defence-in-depth guard for the extraction_method="manual" path and
    direct construction; the LLM-facing schema strips before validating and
    ExtractedSkill.skill_name_th carries Field(min_length=1), so blank names are
    not reachable through normal extraction.
    """
    by_norm: dict[str, list[int]] = {}
    display: dict[str, str] = {}
    skipped = 0
    for i, skill in enumerate(skills):
        norm = _normalize(skill.skill_name_th)
        if not norm:
            skipped += 1
            continue
        by_norm.setdefault(norm, []).append(i)
        display.setdefault(norm, skill.skill_name_th.strip())

    if skipped:
        logger.warning(f"dedupe_with_bloom_max: skipped {skipped} blank/whitespace-only name(s)")

    ordered = sorted(by_norm)
    names = [display[k] for k in ordered]
    groups = [by_norm[k] for k in ordered]
    blooms = {display[k]: merge_bloom([skills[i].bloom_level for i in by_norm[k]]) for k in ordered}
    return names, groups, blooms


def allocate_quota(
    group_counts: dict[KSECCategory, int],
    bucket_demand: dict[KSECCategory, float],
    cap: int = MAX_NEEDS,
) -> dict[KSECCategory, int]:
    """Decide how many Needs each KSEC bucket may keep, totalling at most `cap`.

    Shares are allocated by group count rather than demand so a bucket holding
    many distinct capabilities is not squeezed out by one bucket holding a single
    very high-demand capability; demand only breaks ties. Every non-empty bucket
    keeps at least one Need. That is always satisfiable here: there are at most
    five buckets and `cap` is 10.
    """
    active = {b: n for b, n in group_counts.items() if n > 0}
    if not active:
        return {}
    total = sum(active.values())
    if total <= cap:
        return dict(active)

    if len(active) > cap:  # unreachable with 5 buckets and cap 10; guard anyway
        raise ValueError(f"cannot keep {len(active)} buckets within cap {cap}")

    target = {b: max(1, (cap * n) // total) for b, n in active.items()}

    while sum(target.values()) > cap:
        shrinkable = [b for b in target if target[b] > 1]
        victim = min(shrinkable, key=lambda b: bucket_demand.get(b, 0.0))
        target[victim] -= 1

    while sum(target.values()) < cap:
        growable = [b for b in target if target[b] < active[b]]
        if not growable:
            break
        winner = max(growable, key=lambda b: bucket_demand.get(b, 0.0))
        target[winner] += 1

    logger.debug(f"Need quota: {total} groups → {target} (cap {cap})")
    return target
