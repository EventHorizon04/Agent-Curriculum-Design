from __future__ import annotations

from curriculum_agent.models import STAKEHOLDER_GROUP, StakeholderGroup, StakeholderType

# What a source's word is worth. สภาวิชาชีพ speaks with legal force; the
# institution's own direction binds the program it governs; other outside voices
# describe the market the graduate enters; inside voices describe the program
# from within, where the incentive to reflect the market is weakest.
_REQUIREMENT_WEIGHT = {
    StakeholderType.PROFESSIONAL_COUNCIL: 1.0,
    StakeholderType.INSTITUTIONAL_DIRECTION: 0.8,
}
_EXTERNAL_WEIGHT = 0.6
_INTERNAL_WEIGHT = 0.4


def evidence_weight(stakeholder_type: StakeholderType) -> float:
    """Weight of one evidence item, from who produced it.

    Resolution goes through STAKEHOLDER_GROUP, so a type added to the enum later
    picks up the external or internal tier without an edit here.
    """
    explicit = _REQUIREMENT_WEIGHT.get(stakeholder_type)
    if explicit is not None:
        return explicit
    group = STAKEHOLDER_GROUP.get(stakeholder_type, StakeholderGroup.INTERNAL)
    return _EXTERNAL_WEIGHT if group is StakeholderGroup.EXTERNAL else _INTERNAL_WEIGHT


def _weight_of(raw_type: str) -> float:
    """Weight for a stored type string, tolerating a value not in the enum.

    An unrecognised value scores the internal tier rather than raising: a stale
    row must not take down the whole scoring pass.
    """
    try:
        return evidence_weight(StakeholderType(raw_type))
    except ValueError:
        return _INTERNAL_WEIGHT


def total_evidence_weight(stakeholder_type_by_evidence: dict[str, str]) -> float:
    """Denominator for every score in one program: the weight of all its evidence."""
    return sum(_weight_of(t) for t in stakeholder_type_by_evidence.values())


def compute_demand_score(
    source_evidence_ids: list[str],
    stakeholder_type_by_evidence: dict[str, str],
    total_weight: float,
) -> float:
    """Share of the program's total evidence weight that named this capability.

    Pure weighted frequency. The previous formula added a breadth term divided by
    len(StakeholderType) — the count of enum members, not of the groups the
    program actually collected from — so a well-supported skill in a 3-source
    program scored 0.33 on breadth and every stored score moved whenever the enum
    grew. Frequency alone is both honest and stable.
    """
    if total_weight <= 0:
        return 0.0
    named = sum(
        _weight_of(stakeholder_type_by_evidence.get(eid, ""))
        for eid in set(source_evidence_ids)
        if eid in stakeholder_type_by_evidence
    )
    return round(min(named / total_weight, 1.0), 4)


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
