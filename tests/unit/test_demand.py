from __future__ import annotations

import pytest

from curriculum_agent.models import (
    REQUIREMENT_TYPES,
    STAKEHOLDER_GROUP,
    StakeholderGroup,
    StakeholderType,
)
from curriculum_agent.stages import demand
from curriculum_agent.stages.demand import (
    MANDATE_WEIGHT,
    OTHER_VOICE_WEIGHT,
    PRACTITIONER_WEIGHT,
    classification_coverage,
    compute_demand_score,
    is_optional_group,
    is_practitioner_voice,
)


def test_the_three_blocks_are_twenty_fiftyfive_twentyfive():
    """The split is policy, not a tuning knob — pin it so a change is deliberate."""
    assert (MANDATE_WEIGHT, PRACTITIONER_WEIGHT, OTHER_VOICE_WEIGHT) == (0.20, 0.55, 0.25)


def test_the_blocks_sum_to_one():
    """A capability every voice named, mandate included, scores exactly 1.0 — so
    the weights have to close. A set that summed to less would make the top of
    the range depend on which blocks a program happens to have."""
    assert pytest.approx(1.0) == MANDATE_WEIGHT + PRACTITIONER_WEIGHT + OTHER_VOICE_WEIGHT


def test_only_the_professional_council_buys_the_mandate_block():
    """Deliberately narrower than models.REQUIREMENT_TYPES.

    That set decides what counts as a mandate for evidence and skill
    classification and still holds INSTITUTIONAL_DIRECTION. The score privileges
    only สภาวิชาชีพ: the institution's direction binds the program but is the
    program's own voice, and letting it buy the same block would let a faculty
    lift any Need's rank by restating its vision. This test pins the divergence
    so nobody "fixes" it back into agreement.
    """
    assert demand._MANDATING_TYPE is StakeholderType.PROFESSIONAL_COUNCIL
    assert StakeholderType.INSTITUTIONAL_DIRECTION in REQUIREMENT_TYPES
    assert demand._MANDATING_TYPE != StakeholderType.INSTITUTIONAL_DIRECTION


def test_a_council_named_capability_starts_a_mandate_block_ahead():
    types = {"E1": "professional_council", "E2": "employer"}

    council = compute_demand_score(["E1"], types)
    employer = compute_demand_score(["E2"], types)

    # Both are practitioner voices naming 1 of 2, so the frequency blocks are
    # equal and the whole gap is the mandate.
    assert council - employer == pytest.approx(MANDATE_WEIGHT)


def test_an_employer_outranks_a_community_voice_at_the_same_frequency():
    """The reason this scoring exists.

    One evidence item each, so a single pooled frequency block scored these the
    same — and on the real corpus that is what buried every translation
    competency an employer had named alone beneath generic capabilities that
    applicants and the community could also name. Whether the speaker has done
    the work is the question; how many of them there are is not.
    """
    types = {"E1": "employer", "E2": "community"}

    assert compute_demand_score(["E1"], types) > compute_demand_score(["E2"], types)


def test_the_practitioner_split_is_not_the_external_internal_one():
    """STAKEHOLDER_GROUP was the obvious lever and it does not work.

    APPLICANT and COMMUNITY sit outside the institution, so an external/internal
    denominator puts them in the same block as the employer and changes nothing
    about the ranking that matters. Reusing STAKEHOLDER_GROUP here would be a
    plausible simplification that silently undoes this whole change.
    """
    for outsider in (StakeholderType.APPLICANT, StakeholderType.COMMUNITY):
        assert STAKEHOLDER_GROUP[outsider] is StakeholderGroup.EXTERNAL
        assert not is_practitioner_voice(outsider.value)

    assert is_practitioner_voice(StakeholderType.EMPLOYER.value)


def test_the_institutions_own_direction_scores_like_the_other_non_practitioners():
    """It is not privileged, and it is not penalised beyond the block it sits in:
    the faculty's own voice and a prospective student's are both voices that have
    not done the work."""
    types = {"E1": "institutional_direction", "E2": "applicant"}

    assert compute_demand_score(["E1"], types) == compute_demand_score(["E2"], types)


def test_practitioner_frequency_can_outrank_a_thinly_supported_mandate():
    """The mandate is a head start, not a verdict — broad practitioner demand
    still beats a capability the council named once in a wide corpus."""
    types = {f"E{i}": "employer" for i in range(1, 11)}
    types["E1"] = "professional_council"

    council_once = compute_demand_score(["E1"], types)  # 0.20 + 0.55 * 0.1
    named_widely = compute_demand_score([f"E{i}" for i in range(2, 9)], types)  # 0.55 * 0.7

    assert named_widely > council_once


def test_a_capability_named_by_the_council_and_every_source_scores_one():
    types = {"E1": "professional_council", "E2": "employer", "E3": "student"}

    assert compute_demand_score(["E1", "E2", "E3"], types) == 1.0


def test_the_ceiling_needs_the_mandate_too():
    """Without สภาวิชาชีพ in the corpus the top of the range is the two frequency
    blocks, which is the point of keeping the mandate a separate block."""
    types = {"E1": "employer", "E2": "student"}

    assert compute_demand_score(["E1", "E2"], types) == pytest.approx(
        PRACTITIONER_WEIGHT + OTHER_VOICE_WEIGHT
    )


def test_each_block_is_a_share_of_its_own_audience():
    """Adding voices to one block must not dilute the other.

    A capability both employers named scores the full practitioner block whether
    the corpus holds two applicants or twenty — which is what a pooled
    denominator could not do, and why a well-surveyed program used to rank its
    specialist capabilities lower than a thinly-surveyed one.
    """
    small = {"E1": "employer", "E2": "employer", "E3": "applicant"}
    large = {**small, **{f"A{i}": "applicant" for i in range(1, 18)}}

    both_employers = ["E1", "E2"]
    assert compute_demand_score(both_employers, small) == compute_demand_score(
        both_employers, large
    )
    assert compute_demand_score(both_employers, small) == pytest.approx(PRACTITIONER_WEIGHT)


def test_a_corpus_with_no_practitioner_voice_still_scores_and_orders():
    """A block whose audience is absent contributes zero rather than having its
    weight redistributed: the absolute numbers are smaller, the ordering is the
    one the remaining block gives, and there is no branch to get wrong."""
    types = {"E1": "faculty", "E2": "community", "E3": "applicant"}

    one = compute_demand_score(["E1"], types)
    two = compute_demand_score(["E1", "E2"], types)

    # abs= because the score is rounded to 4 dp and a third does not land on one.
    assert one == pytest.approx(OTHER_VOICE_WEIGHT / 3, abs=5e-5)
    assert two > one


def test_a_corpus_of_practitioners_alone_does_not_divide_by_zero():
    types = {"E1": "employer", "E2": "industry"}

    assert compute_demand_score(["E1", "E2"], types) == pytest.approx(PRACTITIONER_WEIGHT)


def test_repeated_evidence_ids_count_once():
    types = {"E1": "employer", "E2": "employer"}

    assert compute_demand_score(["E1", "E1", "E1"], types) == pytest.approx(PRACTITIONER_WEIGHT / 2)


def test_an_evidence_id_outside_the_corpus_contributes_nothing():
    """The map is the corpus. An id absent from it is a stale reference, not a
    source — counting it would push a frequency block above its own denominator."""
    types = {"E1": "employer", "E2": "employer"}

    assert compute_demand_score(["E1", "E9"], types) == compute_demand_score(["E1"], types)


def test_an_unknown_stakeholder_type_falls_to_the_smaller_block():
    """A value the enum does not know is not a practitioner. That direction is
    the safe one: a typo in stored data cannot hand a Need the larger block."""
    types = {"E1": "not_a_real_type", "E2": "employer"}

    assert not is_practitioner_voice("not_a_real_type")
    assert compute_demand_score(["E1"], types) == pytest.approx(OTHER_VOICE_WEIGHT)
    assert compute_demand_score(["E2"], types) == pytest.approx(PRACTITIONER_WEIGHT)


def test_empty_program_scores_zero_rather_than_dividing_by_zero():
    assert compute_demand_score(["E1"], {}) == 0.0


def test_a_group_only_one_evidence_item_asked_for_is_optional():
    assert is_optional_group({"want": 3}, 1) is True


def test_a_second_evidence_item_makes_a_group_core():
    """Two stakeholders asking is what core means, whatever the members are called."""
    assert is_optional_group({"want": 3}, 2) is False


def test_a_mandate_makes_a_group_core_however_few_asked():
    """A mandate is not a matter of how many people repeated it."""
    assert is_optional_group({"requirement": 1}, 1) is False


def test_member_classification_alone_cannot_decide_the_group():
    """The bug this rule replaced, pinned.

    Every one of these groups was drawn from several evidence items and every
    member came back `want`, because `classify_skills` matches normalised name
    strings and the extraction model never writes the same name twice. Under
    `want > requirement + need` all three were optional; the old rule is one
    edit away from returning, and it returns as a set of `want` counts.
    """
    for members in ({"want": 18}, {"want": 14, "requirement": 0}, {"want": 3}):
        assert is_optional_group(members, 7) is False


def test_unclassified_members_do_not_make_a_group_optional():
    """Unclassified means the extractor was unsure, which decides nothing."""
    assert is_optional_group({"unclassified": 5}, 3) is False
    assert is_optional_group({"unclassified": 5}, 1) is True


def test_classification_coverage_counts_each_class():
    assert classification_coverage(["need", "need", "want"]) == {"need": 2, "want": 1}
