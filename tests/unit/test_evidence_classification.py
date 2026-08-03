from __future__ import annotations

from curriculum_agent.models import StakeholderType
from curriculum_agent.stages.stakeholder_needs import classify_evidence_type


def test_professional_council_is_a_requirement():
    assert classify_evidence_type(StakeholderType.PROFESSIONAL_COUNCIL) == "requirement"


def test_institutional_direction_is_a_requirement():
    assert classify_evidence_type(StakeholderType.INSTITUTIONAL_DIRECTION) == "requirement"


def test_every_other_type_is_general():
    others = [
        t
        for t in StakeholderType
        if t not in {StakeholderType.PROFESSIONAL_COUNCIL, StakeholderType.INSTITUTIONAL_DIRECTION}
    ]
    assert others, "expected non-requirement types to exist"
    assert all(classify_evidence_type(t) == "general" for t in others)
