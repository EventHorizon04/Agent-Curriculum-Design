from __future__ import annotations

from collections.abc import Iterable

from curriculum_agent.models import StakeholderType

# The score is three blocks, not a table of per-type weights:
#
#   demand_score = 0.20 × (สภาวิชาชีพ named it? 1 : 0)
#                + 0.55 × share of the *practitioner* voices that named it
#                + 0.25 × share of everyone else that named it
#
# 20% asks a yes/no question with a defensible answer — สภาวิชาชีพ sets legally
# binding practice requirements, so a capability it names is mandated whatever the
# rest of the corpus says. The other two blocks ask how much of the corpus named
# it, but they ask it of two audiences separately rather than of one pooled
# denominator, because a pooled one measures the wrong thing. See below.
#
# These three are mirrored in `frontend/src/constants/demand.ts`, which is what
# every page's tooltip reads. No test spans the two languages, so change them
# together — the tooltip there described the pooled block for as long as it took
# someone to notice, and a wrong explanation beside a right number is worse than
# none: the designer reads the ranking as "how many people said it".
MANDATE_WEIGHT = 0.20
PRACTITIONER_WEIGHT = 0.55
OTHER_VOICE_WEIGHT = 0.25

# Deliberately narrower than models.REQUIREMENT_TYPES, which also holds
# INSTITUTIONAL_DIRECTION. That set decides what counts as a mandate for evidence
# and skill classification and is unchanged; this one decides who gets the
# mandate block. The institution's own direction binds the program, but it is the
# program's own voice — letting it buy the same block as สภาวิชาชีพ would let a
# faculty raise any Need's rank by restating its vision. Do not collapse the two.
_MANDATING_TYPE = StakeholderType.PROFESSIONAL_COUNCIL

# Who speaks from having done, or paid for, the work the graduate will do.
#
# This exists because the mandate block is dead for most Thai programs and a
# single pooled frequency block is not a safe thing to leave holding the score on
# its own. สภาวิชาชีพ covers a handful of regulated professions; มคอ.1 was
# repealed wholesale by กฎกระทรวง 2565, and the "มาตรฐานคุณวุฒิในสาขาวิชา" series
# กมอ. issued in its place (แพทยศาสตร์ 2566, เทคนิคการแพทย์/กายภาพบำบัด/เภสัชศาสตร์
# 2567) covers those same council-backed fields. A translation program, a
# humanities program, most business programs: there is no external document that
# can buy the mandate block, ever.
#
# Pooled frequency then decides everything, and it inverts the ranking. A generic
# capability is one everybody can name; a specialist one is named only by the
# people who employ the graduate. Measured on the stored TCISM corpus (14 items),
# the top-ranked Need was "การเรียนรู้ตลอดชีวิต" — named by applicant, community,
# faculty and the faculty's own vision — while every actual translation
# competency (ประเมินความถูกต้องตามกฎหมายของเอกสารที่แปล, ปรับสำนวนงานแปล,
# ตรวจสอบข้อกฎหมายในเอกสารจีน) sat at the bottom on one employer each and was cut.
#
# Splitting the denominator by StakeholderGroup (external/internal) does NOT fix
# that, and it was tried first: APPLICANT and COMMUNITY are external too, so an
# employer naming something alone scored exactly what a community voice naming
# something alone scored, and not one of those Needs moved. The line that matters
# is not where the speaker sits relative to the institution — it is whether they
# have done the work. That is why this set exists instead of reusing
# STAKEHOLDER_GROUP, which stays what it is: a display label.
#
# This is a table mapping types to classes, which `CLAUDE.md` warns against, and
# the warning is worth reading before editing it. What it forbids is the old
# 1.0/0.8/0.6/0.4 *gradation* — per-type multipliers whose individual values
# nobody could defend and which moved every stored score when one was retuned.
# Two categorical classes with one stated question between them ("has this voice
# done the work?") is a different object: a type's class follows from the
# question rather than from a number someone picked. Keep it that way — if a new
# StakeholderType needs a *third* weight, the answer is a better question, not a
# third tier.
_PRACTITIONER_TYPES = frozenset(
    {
        StakeholderType.PROFESSIONAL_COUNCIL,
        StakeholderType.EMPLOYER,
        StakeholderType.INDUSTRY,
        StakeholderType.ALUMNI,
        StakeholderType.EXPERT,
    }
)


def build_scoring_corpus(evidence_types: Iterable[tuple[str, str]]) -> dict[str, str]:
    """The corpus a demand score is a share of, from (evidence_id, type) pairs.

    Built from the *extracted skills*, never from the evidence table, so the
    denominator is the evidence that yielded at least one skill. An evidence item
    nobody extracted anything from expresses no demand, and counting it would
    make every score a share of a corpus part of which said nothing.

    It exists as a function because two stages score the same data and drifted
    apart: skill_extraction built this from every evidence item while
    need_combination built it from the skills, so one capability was scored
    0.35 as a skill and 0.49 as the Need it formed — same weights, same evidence,
    different denominators, and both numbers shown to the designer side by side.
    Duplicate ids collapse, which is what makes "how many items named it" a count
    of items rather than of mentions.
    """
    return dict(evidence_types)


def is_practitioner_voice(stakeholder_type: str) -> bool:
    """Whether this voice speaks from having done or commissioned the work.

    A type the enum does not know answers False. That is the safe direction: an
    unrecognised voice falls into the smaller block rather than being handed the
    larger one, so a typo in stored data cannot inflate a Need's rank.
    """
    return stakeholder_type in {t.value for t in _PRACTITIONER_TYPES}


def compute_demand_score(
    source_evidence_ids: list[str],
    stakeholder_type_by_evidence: dict[str, str],
) -> float:
    """How strongly the corpus asks for this capability, in [0, 1].

    `stakeholder_type_by_evidence` is both the type lookup and the corpus: its
    size is the denominator, and an evidence id absent from it contributes
    nothing. Callers build it from the extracted skills, so the corpus is the
    evidence that yielded at least one skill.

    Duplicate ids collapse — a capability named three times in one evidence item
    is one item's worth of demand, not three.

    Each frequency block is a share of *its own* audience, so the two are
    independent of how the corpus happens to be composed: adding five more
    applicant interviews cannot dilute what the employers said. A block whose
    audience is absent from the corpus contributes zero rather than having its
    weight redistributed. That leaves the absolute numbers smaller for such a
    program but the ordering identical either way, and no redistribution branch
    whose behaviour changes with corpus composition.

    Those same two guards are what answers an empty corpus, so there is no
    separate early return for it: with nothing in the map nothing is `named`, the
    mandate is False and both audiences are empty, and the score is 0.0. The
    version that opened with `if corpus == 0` kept a branch no test could tell
    from its absence — which is how it was found.
    """
    corpus = len(stakeholder_type_by_evidence)
    named = {eid for eid in source_evidence_ids if eid in stakeholder_type_by_evidence}
    mandated = any(stakeholder_type_by_evidence[eid] == _MANDATING_TYPE.value for eid in named)

    practitioner_total = sum(
        1 for value in stakeholder_type_by_evidence.values() if is_practitioner_voice(value)
    )
    other_total = corpus - practitioner_total
    practitioner_named = sum(
        1 for eid in named if is_practitioner_voice(stakeholder_type_by_evidence[eid])
    )
    other_named = len(named) - practitioner_named

    score = MANDATE_WEIGHT * float(mandated)
    if practitioner_total:
        score += PRACTITIONER_WEIGHT * practitioner_named / practitioner_total
    if other_total:
        score += OTHER_VOICE_WEIGHT * other_named / other_total
    return round(score, 4)


def classification_coverage(member_classes: list[str]) -> dict[str, int]:
    """Count of each SkillClassification among a group's member skills."""
    coverage: dict[str, int] = {}
    for value in member_classes:
        coverage[value] = coverage.get(value, 0) + 1
    return coverage


def is_optional_group(class_coverage: dict[str, int], evidence_count: int) -> bool:
    """True when nothing mandates this group and only one evidence item asked for it.

    The question is "did more than one stakeholder ask for this capability, or does
    someone require it?" — and it is asked of the *group*, which is where a
    capability exists. It used to be asked of the members' `classification`
    instead: `want > requirement + need`, where a member is `need` when its own
    skill *name* was extracted from more than one evidence item.

    That proxy never fired. On the stored run, all 91 normalised names came from
    exactly one evidence item each, so `need` was zero and the only way to be core
    was to carry a `requirement` — which comes from `INSTITUTIONAL_DIRECTION` alone
    for any programme without a professional council, and which the scope guard
    then drops for not being a graduate capability. Core ended at 1 against a floor
    of 6. Meanwhile the groups those members formed drew on 7, 9 and 10 evidence
    items: the clustering step knows two phrasings are one capability, and matching
    normalised name strings cannot. Counting phrasings answers a question nobody
    asked.

    This is the second half of the bug `POST /evidence/` fixed the first half of —
    see that route, which records how a missing `requirement` made almost every
    group optional, and note that `MAX_CORE_PLOS` only bounds the core series, so a
    programme whose Needs are all optional has no ceiling at all.

    `need` is subsumed rather than dropped: a member classified `need` had its name
    in several evidence items, so its group has several too, and `evidence_count`
    already says so. `classification` keeps its meaning everywhere else; this
    function simply stops reading the group's answer out of it.

    `requirement` still wins outright, and deliberately so — one mandated member
    makes the group core however small it is, because a mandate is not a matter of
    how many people repeated it.
    """
    if class_coverage.get("requirement", 0):
        return False
    return evidence_count <= 1
