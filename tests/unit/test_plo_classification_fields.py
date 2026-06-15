from __future__ import annotations

import pytest
from pydantic import ValidationError

from curriculum_agent.models import PLO, BloomLevel, Domain, SMARTCheck

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)


def _make_plo(**overrides) -> PLO:
    base = dict(
        plo_id="PLO1",
        program_id="cs-test",
        statement_th="ออกแบบและพัฒนาซอฟต์แวร์ที่มีคุณภาพได้",
        domain=Domain.COGNITIVE,
        bloom_level=BloomLevel.CREATE,
        is_subject_specific=True,
        action_verb_th="ออกแบบ",
        smart_check=_SMART,
        source_cluster_ids=["C1"],
        source_evidence_ids=["E1"],
        rationale_th="ทักษะหลักที่นายจ้างต้องการ",
    )
    base.update(overrides)
    return PLO(**base)


def test_classification_fields_default_none():
    plo = _make_plo()
    assert plo.classification is None
    assert plo.classification_method is None
    assert plo.classification_rationale_th is None


def test_classification_fields_accept_valid_values():
    plo = _make_plo(
        classification="generic",
        classification_method="llm",
        classification_rationale_th="เป็นทักษะที่ถ่ายโอนข้ามสาขาได้",
    )
    assert plo.classification == "generic"
    assert plo.classification_method == "llm"


def test_classification_rejects_invalid_literal():
    with pytest.raises(ValidationError):
        _make_plo(classification="cross-cutting")


def test_classification_method_rejects_invalid_literal():
    with pytest.raises(ValidationError):
        _make_plo(classification_method="guess")
