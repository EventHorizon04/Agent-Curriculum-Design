from __future__ import annotations

import pytest
from pydantic import ValidationError

from curriculum_agent.models import (
    Domain,
    PLO,
    BloomLevel,
    KrathwohlLevel,
    SMARTCheck,
)

SMART_PASS = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)


def make_plo(**overrides) -> dict:
    base = {
        "plo_id": "PLO1",
        "program_id": "cs-test",
        "statement_th": "ออกแบบระบบซอฟต์แวร์ขนาดใหญ่ได้",
        "domain": Domain.COGNITIVE,
        "bloom_level": BloomLevel.CREATE,
        "is_subject_specific": True,
        "action_verb_th": "ออกแบบ",
        "smart_check": SMART_PASS,
        "source_cluster_ids": ["C1"],
        "source_evidence_ids": ["E1"],
        "rationale_th": "ทดสอบ",
    }
    base.update(overrides)
    return base


# ---- forbidden words ---------------------------------------------------

@pytest.mark.parametrize("word", ["รู้", "จำ", "เข้าใจ", "ซาบซึ้ง", "ตระหนัก", "ศรัทธา", "รัก"])
def test_plo_rejects_forbidden_word(word: str) -> None:
    with pytest.raises(ValidationError, match="forbidden word"):
        PLO(**make_plo(statement_th=f"นักศึกษา{word}หลักการออกแบบ"))


def test_plo_accepts_clean_statement() -> None:
    plo = PLO(**make_plo())
    assert plo.plo_id == "PLO1"


# ---- evidence tracing --------------------------------------------------

def test_plo_rejects_empty_source_clusters() -> None:
    with pytest.raises(ValidationError, match="no source clusters"):
        PLO(**make_plo(source_cluster_ids=[]))


def test_plo_rejects_empty_source_evidence_ids() -> None:
    with pytest.raises(ValidationError, match="source_evidence_ids"):
        PLO(**make_plo(source_evidence_ids=[]))


# ---- domain / level matching -------------------------------------------

def test_cognitive_plo_requires_bloom_level() -> None:
    with pytest.raises(ValidationError, match="missing bloom_level"):
        PLO(**make_plo(bloom_level=None))


def test_affective_plo_requires_krathwohl_level() -> None:
    with pytest.raises(ValidationError, match="missing krathwohl_level"):
        PLO(**make_plo(domain=Domain.AFFECTIVE, bloom_level=None, krathwohl_level=None))


def test_affective_plo_accepts_krathwohl() -> None:
    plo = PLO(**make_plo(
        domain=Domain.AFFECTIVE,
        bloom_level=None,
        krathwohl_level=KrathwohlLevel.VALUING,
    ))
    assert plo.domain == Domain.AFFECTIVE
