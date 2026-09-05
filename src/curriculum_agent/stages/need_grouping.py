from __future__ import annotations

import re
from collections.abc import Iterable

from loguru import logger

from curriculum_agent.models import BLOOM_ORDER, BloomLevel, ExtractedSkill, KSECCategory, Need

# Project policy: 6-10 main Needs, which become main PLOs one-to-one. Both bounds
# live here because they are one policy and the clustering that has to respect
# them is in this module. MIN_NEEDS is a floor no stage can manufacture — too few
# Needs simply means too few PLOs, and the designer adds more at the checkpoint.
#
# MAX_CORE_PLOS is a ceiling plo_synthesis enforces by choosing which Needs to
# use rather than by merging them down to a quota: every Need keeps its own
# sentence and its own evidence trail, and the ones that lose the cut stay in the
# Need list where a designer can promote one by editing its rivals. Optional
# (want-based) PLOs are outside this count, as they are outside the 6 floor.
MIN_NEEDS = 6
MAX_CORE_PLOS = 10


def is_in_scope(need: Need) -> bool:
    """Is this Need eligible to become a PLO of this program at all?

    The third policy deciding which Needs become PLOs, which is why it lives here
    beside the other two rather than at its point of use. Both axes are judged per
    skill by the extraction model and rolled up into counters at need_combination
    under an any rule — one qualifying member per axis is enough.

    Returns a bare bool. "Which axis did it fail?" is already readable off the
    Need's own counters ("0 of 8"), which is finer than an enum could be and
    cannot drift out of step with them.

    `and` rather than `or`: the two axes were measured to overlap completely on
    the evidence available, so the data cannot choose between them and policy has
    to. Failing either one disqualifies a Need, because one that is not a graduate
    capability cannot be written as a PLO at all, not merely written about the
    wrong field. The permissive side is already spent on the any rule a level
    down.

    `classification` is not consulted, and a `requirement` gets no exemption —
    that is a decision, not an oversight. "requirement wins" settles whether a
    skill is a mandate, which is a different question from whether the capability
    belongs to this programme: a professional council can require something this
    programme is the wrong place to teach. A Need filtered while carrying a
    mandate is flagged on the report so a designer sees it before approving the
    set, and the merge route will still take it if they decide otherwise. Neither
    of those is this function's business. Do not add a `classification` check
    here on the assumption that one was forgotten.

    This is also the whole fallback switch: if the eval says the flags are not
    trustworthy enough to filter on, the retreat is to stop calling this in one
    place and leave the flags on display at the checkpoint instead.
    """
    return need.is_field_relevant and need.is_graduate_capability


_WS_RE = re.compile(r"\s+")
_BLOOM_RANK = {level: i for i, level in enumerate(BLOOM_ORDER)}

# Shapes that no Thai curriculum sentence produces but a code-trained model
# leaks: `หน.getDefault` reached a stored Need this way. Deliberately narrow —
# a guard that also rejected JavaScript, IoT, or Power BI would retry good
# sentences and end up falling back to a comma-joined skill list, which is
# worse than the leak it was meant to catch. General camelCase is therefore NOT
# matched; only these five shapes are.
_CODE_TOKEN_RES: tuple[re.Pattern[str], ...] = (
    # snake_case — no natural-language word carries an underscore
    re.compile(r"[A-Za-z]\w*_\w+"),
    # a call's empty parens: calculate()
    re.compile(r"[A-Za-z]\w*\(\s*\)"),
    # Thai fused to Latin across a dot: หน.getDefault
    re.compile(r"[฀-๿]\.[A-Za-z]\w*"),
    # attribute access on a lowercase receiver: obj.getValue, df.head
    re.compile(r"\b[a-z]\w*\.[a-z]\w*"),
    # Thai running straight into Latin with no space, in either direction:
    # "กลยุทธ์chant", "ผู้LEANที่มี". Correct Thai typography puts a space
    # around an embedded English term, so requiring one costs nothing and
    # catches leaks that carry no punctuation at all. Digits are excluded on
    # purpose — "พ.ศ.2566" and "ฉบับที่ 13" are ordinary.
    re.compile(r"[฀-๿][A-Za-z]|[A-Za-z][฀-๿]"),
)


def find_code_identifier(statement: str) -> str | None:
    """The first code-shaped token in `statement`, or None.

    Returns the token itself rather than a bool because the retry prompt names
    it — telling a model "your sentence contained getDefault" corrects it far
    more reliably than "your sentence was invalid".
    """
    for pattern in _CODE_TOKEN_RES:
        match = pattern.search(statement)
        if match:
            return match.group(0)
    return None


# A Need is drafted straight into one PLO, so a sentence that names no capability
# is not a weaker Need — it is an unusable one. These two guards are the pure-code
# half of "PLO-ready": the prompt asks for a concrete capability, and these reject
# the two shapes a light model falls back to when it cannot produce one.

# A generic head noun plus an empty modifier: "ทักษะที่จำเป็น", "ความรู้ที่เกี่ยวข้อง",
# "ด้านต่างๆ". Matching the pair rather than the modifier alone is deliberate —
# "ข้อมูลที่จำเป็นต่อการตัดสินใจ" names a real object and must pass.
_VAGUE_HEAD_RE = re.compile(
    r"(ความรู้|ทักษะ|สมรรถนะ|ความสามารถ|คุณลักษณะ|สิ่ง|เรื่อง|ด้าน|งาน)\s*"
    r"(ที่จำเป็น|ที่เกี่ยวข้อง|ที่หลากหลาย|ต่าง\s*ๆ)"
)

# Restating the question instead of answering it: "ต้องการบัณฑิตที่มีทักษะตามที่
# ตลาดต้องการ". Circular by construction, so plain substrings are enough — and
# independent of how the sentence opens, which is why this list survived the
# opening becoming free (see build_summarize_need_prompt). A Need may now begin
# "ต้องการ...", "ต้องการหลักสูตรที่..." or "บัณฑิตต้องมี..."; none of that makes a
# trailing "ตามที่ตลาดต้องการ" say anything.
_CIRCULAR_PHRASES_TH: tuple[str, ...] = (
    "ตามที่ตลาดต้องการ",
    "ตามความต้องการของตลาด",
    "ที่ตลาดต้องการ",
    "ตามที่สถานประกอบการต้องการ",
)

# Three or more commas is a list wearing a sentence's clothes. Two is still prose
# ("ออกแบบ, พัฒนา และดูแลระบบ"), which is why the floor is not lower.
_MAX_COMMAS = 2


def find_vague_phrase(statement: str) -> str | None:
    """The first content-free phrase in `statement`, or None.

    Returns the phrase because the retry prompt names it: a model told that
    "ทักษะที่จำเป็น" was rejected replaces it with the capability it meant, while
    one told the sentence was invalid usually rewrites the wrong half.
    """
    match = _VAGUE_HEAD_RE.search(statement)
    if match:
        return match.group(0)
    for phrase in _CIRCULAR_PHRASES_TH:
        if phrase in statement:
            return phrase
    return None


def looks_like_a_skill_list(statement: str) -> bool:
    """True when the sentence is skill names joined by commas rather than a demand."""
    return statement.count(",") + statement.count("，") > _MAX_COMMAS


def normalize_need_name(name: str) -> str:
    """Trim, collapse internal whitespace, lowercase.

    The canonical normaliser for "is this the same skill name" grouping —
    dedupe_with_bloom_max uses it to collapse duplicate skill names within a
    KSEC bucket, and skill_extraction._compute_skill_importance reuses it so
    per-skill-name importance scores are computed over the same buckets that
    later collapse into one Need. Do not diverge the two.
    """
    return _WS_RE.sub(" ", name.strip()).lower()


# E and C skills are clustered together: a Need about professional conduct is
# routinely both, and forcing the split at grouping time produces two thin Needs
# that a designer immediately merges by hand. The raw tags survive on the member
# skills, so resolve_need_ksec can still hand back a standalone E or C.
_EC_MEMBERS = {KSECCategory.E, KSECCategory.C}


def bucket_by_ksec(skills: list[ExtractedSkill]) -> dict[KSECCategory, list[ExtractedSkill]]:
    """Split skills into one bucket per KSEC tag, omitting empty buckets.

    E and C skills land in a single EC bucket; everything else buckets by its own
    tag. Clustering runs inside a bucket and merging never crosses buckets, so a
    Need can never contain two different tags. This is what makes "tags must not
    mix" a structural guarantee instead of a rule someone has to remember.
    """
    buckets: dict[KSECCategory, list[ExtractedSkill]] = {}
    for skill in skills:
        key = KSECCategory.EC if skill.ksec_category in _EC_MEMBERS else skill.ksec_category
        buckets.setdefault(key, []).append(skill)
    return buckets


def allocate_cluster_targets(
    bucket_sizes: dict[KSECCategory, int],
    total: int = MAX_CORE_PLOS,
) -> dict[KSECCategory, int]:
    """How many groups each KSEC bucket should be clustered into.

    Clustering runs once per bucket, and the prompt used to ask each one for
    "typically 4-12 groups" with no idea how many buckets there were. Three
    buckets therefore produced 12-36 Needs against a ceiling of ten, so a run's
    Need count was set by how splitty the model felt rather than by policy, and
    plo_synthesis routinely dropped two thirds of what this stage wrote. Sizing
    the buckets against the ceiling up front is the difference between a
    deliberate shortlist and an accident.

    Shares are proportional to how many unique skill names each bucket holds,
    apportioned by largest remainder. Every non-empty bucket gets at least one
    group: K, S and EC are different competency domains, and trimming a program's
    whole ethics dimension to hit a count is not a trade the arithmetic gets to
    make. A bucket is never asked for more groups than it has names.

    The result is a target, not a cap — the model is asked for about this many
    and validate_assignments still accepts whatever partition comes back, since a
    skill silently dropped to hit a number would be far worse than a Need over
    budget. plo_synthesis remains the only place the ceiling is enforced.
    """
    sizes = {ksec: n for ksec, n in bucket_sizes.items() if n > 0}
    if not sizes:
        return {}

    # Every bucket gets one before anything gets two.
    total = max(total, len(sizes))
    grand = sum(sizes.values())
    exact = {ksec: total * n / grand for ksec, n in sizes.items()}
    targets = {ksec: max(1, min(int(share), sizes[ksec])) for ksec, share in exact.items()}

    # Largest fractional remainder first, then the biggest bucket, then the tag
    # itself so the outcome does not depend on dict ordering.
    order = sorted(sizes, key=lambda k: (-(exact[k] % 1), -sizes[k], k.value))

    shortfall = total - sum(targets.values())
    while shortfall > 0:
        spendable = [k for k in order if targets[k] < sizes[k]]
        if not spendable:
            break  # every bucket already has one group per name
        for ksec in spendable[:shortfall]:
            targets[ksec] += 1
        shortfall = total - sum(targets.values())

    # The floor of one per bucket can push the total past the ceiling when a
    # tiny bucket rounds up; take it back from the largest targets.
    while shortfall < 0:
        reducible = [k for k in reversed(order) if targets[k] > 1]
        if not reducible:
            break  # one group per bucket is the floor, ceiling or not
        for ksec in reducible[:-shortfall]:
            targets[ksec] -= 1
        shortfall = total - sum(targets.values())

    return targets


def resolve_need_ksec(members: list[ExtractedSkill]) -> KSECCategory:
    """The tag a Need carries, given the skills that formed it.

    An all-ethics group is tagged E and an all-character group C, so a program
    with a distinct ethics outcome can show one in its มคอ.2 table. A mixed group
    keeps the EC umbrella. Non-EC buckets are single-tag by construction.
    """
    if not members:
        raise ValueError("resolve_need_ksec requires at least one member skill")
    tags = {m.ksec_category for m in members}
    if tags <= _EC_MEMBERS:
        return tags.pop() if len(tags) == 1 else KSECCategory.EC
    if len(tags) != 1:
        raise ValueError(
            f"a Need's members must share one KSEC tag, got {sorted(t.value for t in tags)}"
        )
    return tags.pop()


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
