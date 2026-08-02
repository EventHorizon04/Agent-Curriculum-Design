from __future__ import annotations

import re
from collections.abc import Iterable

from loguru import logger

from curriculum_agent.models import BLOOM_ORDER, BloomLevel, ExtractedSkill, KSECCategory

# Project policy: at least 6 main Needs, which become main PLOs one-to-one.
# No upper cap — every core group clustering finds becomes its own Need.
MIN_NEEDS = 6

_WS_RE = re.compile(r"\s+")
_BLOOM_RANK = {level: i for i, level in enumerate(BLOOM_ORDER)}


def normalize_need_name(name: str) -> str:
    """Trim, collapse internal whitespace, lowercase.

    The canonical normaliser for "is this the same skill name" grouping —
    dedupe_with_bloom_max uses it to collapse duplicate skill names within a
    KSEC bucket, and skill_extraction._compute_skill_importance reuses it so
    per-skill-name importance scores are computed over the same buckets that
    later collapse into one Need. Do not diverge the two.
    """
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
        norm = normalize_need_name(skill.skill_name_th)
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
