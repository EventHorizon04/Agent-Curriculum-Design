from __future__ import annotations

import pytest

from curriculum_agent.models import REQUIREMENT_TYPES, StakeholderType
from curriculum_agent.stages import demand
from curriculum_agent.stages.demand import (
    FREQUENCY_WEIGHT,
    MANDATE_WEIGHT,
    classification_coverage,
    compute_demand_score,
    is_optional_group,
)


def test_the_two_blocks_are_thirty_seventy():
    """The split is policy, not a tuning knob — pin it so a change is deliberate."""
    assert (MANDATE_WEIGHT, FREQUENCY_WEIGHT) == (0.30, 0.70)


def test_only_the_professional_council_buys_the_mandate_block():
    """Deliberately narrower than models.REQUIREMENT_TYPES.

    That set decides what counts as a mandate for evidence and skill
    classification and still holds INSTITUTIONAL_DIRECTION. The score privileges
    only สภาวิชาชีพ: the institution's direction binds the program but is the
    program's own voice, and letting it buy the same 30% would let a faculty lift
    any Need's rank by restating its vision. This test pins the divergence so
    nobody "fixes" it back into agreement.
    """
    assert demand._MANDATING_TYPE is StakeholderType.PROFESSIONAL_COUNCIL
    assert StakeholderType.INSTITUTIONAL_DIRECTION in REQUIREMENT_TYPES
    assert demand._MANDATING_TYPE != StakeholderType.INSTITUTIONAL_DIRECTION


def test_a_council_named_capability_starts_thirty_points_ahead():
    types = {"E1": "professional_council", "E2": "employer"}

    council = compute_demand_score(["E1"], types)
    employer = compute_demand_score(["E2"], types)

    # Same frequency (1 of 2 items); the whole gap is the mandate block.
    assert council - employer == pytest.approx(MANDATE_WEIGHT)


def test_the_institutions_own_direction_scores_like_any_other_voice():
    types = {"E1": "institutional_direction", "E2": "employer"}

    assert compute_demand_score(["E1"], types) == compute_demand_score(["E2"], types)


def test_frequency_alone_can_outrank_a_thinly_supported_mandate():
    """The 70% block is what separates everyone who is not the council — and it is
    large enough that broad demand beats a mandate named once in a wide corpus."""
    types = {f"E{i}": "employer" for i in range(1, 11)}
    types["E1"] = "professional_council"

    council_once = compute_demand_score(["E1"], types)  # 0.30 + 0.70 * 0.1 = 0.37
    named_widely = compute_demand_score([f"E{i}" for i in range(2, 9)], types)  # 0.70 * 0.7 = 0.49

    assert named_widely > council_once


def test_a_capability_named_by_the_council_and_every_source_scores_one():
    types = {"E1": "professional_council", "E2": "employer", "E3": "student"}

    assert compute_demand_score(["E1", "E2", "E3"], types) == 1.0


def test_the_ceiling_needs_the_mandate_too():
    """Without สภาวิชาชีพ in the corpus the top of the range is the frequency block
    alone, which is the point of splitting the score into two."""
    types = {"E1": "employer", "E2": "student"}

    assert compute_demand_score(["E1", "E2"], types) == pytest.approx(FREQUENCY_WEIGHT)


def test_repeated_evidence_ids_count_once():
    types = {"E1": "employer", "E2": "employer"}

    assert compute_demand_score(["E1", "E1", "E1"], types) == pytest.approx(0.35)


def test_an_evidence_id_outside_the_corpus_contributes_nothing():
    """The map is the corpus. An id absent from it is a stale reference, not a
    source — counting it would push the frequency block above its own denominator."""
    types = {"E1": "employer", "E2": "employer"}

    assert compute_demand_score(["E1", "E9"], types) == compute_demand_score(["E1"], types)


def test_an_unknown_stakeholder_type_still_scores_the_shared_class():
    """Everyone who is not the council shares one class, so a value the enum does
    not know needs no special handling — it simply is not the council."""
    types = {"E1": "not_a_real_type", "E2": "employer"}

    assert compute_demand_score(["E1"], types) == pytest.approx(FREQUENCY_WEIGHT * 0.5)


def test_empty_program_scores_zero_rather_than_dividing_by_zero():
    assert compute_demand_score(["E1"], {}) == 0.0


def test_a_want_heavy_group_is_optional():
    assert is_optional_group({"want": 3, "need": 1, "requirement": 1}) is True


def test_a_requirement_backed_group_is_not_optional():
    assert is_optional_group({"want": 2, "requirement": 1, "need": 2}) is False


def test_unclassified_members_do_not_make_a_group_optional():
    assert is_optional_group({"unclassified": 5}) is False


def test_classification_coverage_counts_each_class():
    assert classification_coverage(["need", "need", "want"]) == {"need": 2, "want": 1}
