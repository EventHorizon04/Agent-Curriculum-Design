from __future__ import annotations

from curriculum_agent.models import StakeholderType

# The score is two blocks, not one weighted sum over per-type weights:
#
#   demand_score = 0.30 × (สภาวิชาชีพ named it? 1 : 0) + 0.70 × share of the corpus
#
# 30% asks a yes/no question with a defensible answer — สภาวิชาชีพ sets legally
# binding practice requirements, so a capability it names is mandated whatever the
# rest of the corpus says. 70% asks how much of the corpus named it. Everyone who
# is not the council sits in one class: an employer's ask outranks a student's
# because it was raised more often, not because a table said 0.6 beats 0.4. The
# old per-type weights made every score depend on numbers nobody could defend, and
# a Need's score moved whenever one of them was retuned.
MANDATE_WEIGHT = 0.30
FREQUENCY_WEIGHT = 0.70

# Deliberately narrower than models.REQUIREMENT_TYPES, which also holds
# INSTITUTIONAL_DIRECTION. That set decides what counts as a mandate for evidence
# and skill classification and is unchanged; this one decides who gets the 30%
# block. The institution's own direction binds the program, but it is the
# program's own voice — letting it buy the same 30% as สภาวิชาชีพ would let a
# faculty raise any Need's rank by restating its vision. Do not collapse the two.
_MANDATING_TYPE = StakeholderType.PROFESSIONAL_COUNCIL


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
    """
    corpus = len(stakeholder_type_by_evidence)
    if corpus == 0:
        return 0.0
    named = {eid for eid in source_evidence_ids if eid in stakeholder_type_by_evidence}
    mandated = any(stakeholder_type_by_evidence[eid] == _MANDATING_TYPE.value for eid in named)
    frequency = len(named) / corpus
    return round(MANDATE_WEIGHT * float(mandated) + FREQUENCY_WEIGHT * frequency, 4)


def classification_coverage(member_classes: list[str]) -> dict[str, int]:
    """Count of each SkillClassification among a group's member skills."""
    coverage: dict[str, int] = {}
    for value in member_classes:
        coverage[value] = coverage.get(value, 0) + 1
    return coverage


def is_optional_group(class_coverage: dict[str, int]) -> bool:
    """True when wants outnumber the mandated and demanded skills in a group.

    `unclassified` counts toward neither side: it means "the extractor was unsure",
    which is not evidence that a group is supplementary.
    """
    want = class_coverage.get("want", 0)
    backed = class_coverage.get("requirement", 0) + class_coverage.get("need", 0)
    return want > backed
