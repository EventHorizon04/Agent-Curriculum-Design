from __future__ import annotations

import pytest

from curriculum_agent.models import REQUIREMENT_TYPES, StakeholderType
from curriculum_agent.stages import demand
from curriculum_agent.stages.demand import (
    classification_coverage,
    compute_demand_score,
    evidence_weight,
    is_optional_group,
    total_evidence_weight,
)


def test_the_four_weight_tiers():
    assert evidence_weight(StakeholderType.PROFESSIONAL_COUNCIL) == 1.0
    assert evidence_weight(StakeholderType.INSTITUTIONAL_DIRECTION) == 0.8
    assert evidence_weight(StakeholderType.EMPLOYER) == 0.6
    assert evidence_weight(StakeholderType.FACULTY) == 0.4


def test_every_stakeholder_type_has_a_weight():
    assert all(evidence_weight(t) > 0 for t in StakeholderType)


def test_the_requirement_tier_matches_models_requirement_types():
    """_REQUIREMENT_WEIGHT's key set must track models.REQUIREMENT_TYPES exactly.

    Nothing else ties the two together: a third requirement type added there
    without a matching entry here would silently score the 0.6/0.4 opinion tier
    instead of the mandate tier, with no import error or test failure to catch
    it — this assertion is that guard.
    """
    assert set(demand._REQUIREMENT_WEIGHT.keys()) == REQUIREMENT_TYPES


def test_the_professional_council_outweighs_a_single_employer():
    types = {"E1": "professional_council", "E2": "employer"}
    total = total_evidence_weight(types)

    council = compute_demand_score(["E1"], types, total)
    employer = compute_demand_score(["E2"], types, total)

    assert council > employer


def test_a_skill_named_by_every_source_scores_one():
    types = {"E1": "professional_council", "E2": "employer", "E3": "student"}
    total = total_evidence_weight(types)

    assert compute_demand_score(["E1", "E2", "E3"], types, total) == 1.0


def test_repeated_evidence_ids_count_once():
    types = {"E1": "employer", "E2": "employer"}
    total = total_evidence_weight(types)

    assert compute_demand_score(["E1", "E1", "E1"], types, total) == pytest.approx(0.5)


def test_score_does_not_move_when_the_enum_grows():
    """The old formula divided breadth by len(StakeholderType), so adding a type
    silently rescaled every stored score. Frequency-only scoring is immune."""
    types = {"E1": "employer", "E2": "alumni"}
    total = total_evidence_weight(types)

    assert compute_demand_score(["E1"], types, total) == pytest.approx(0.5)


def test_an_unknown_stakeholder_type_falls_back_to_the_internal_tier():
    types = {"E1": "not_a_real_type"}

    assert total_evidence_weight(types) == pytest.approx(0.4)


def test_empty_program_scores_zero_rather_than_dividing_by_zero():
    assert compute_demand_score(["E1"], {}, 0.0) == 0.0


def test_a_want_heavy_group_is_optional():
    assert is_optional_group({"want": 3, "need": 1, "requirement": 1}) is True


def test_a_requirement_backed_group_is_not_optional():
    assert is_optional_group({"want": 2, "requirement": 1, "need": 2}) is False


def test_unclassified_members_do_not_make_a_group_optional():
    assert is_optional_group({"unclassified": 5}) is False


def test_classification_coverage_counts_each_class():
    assert classification_coverage(["need", "need", "want"]) == {"need": 2, "want": 1}
