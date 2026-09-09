"""What a stored SMART verdict must keep meaning.

The costly failure here is not a wrong verdict — it is an unreadable row. Both
`SMARTCheck` and `PLO` are deserialised straight from a JSONB column with no
coercion layer (`PLORepository.list_by_program` calls `PLO.model_validate` on
`_row_to_dict(row)`), so a shape change that a pre-migration row cannot satisfy
takes out a whole program's PLO list on GET rather than one field.
"""

from __future__ import annotations

import pytest

from curriculum_agent.models import PLO, SMARTCheck, SmartFinding
from curriculum_agent.smart_vocabulary import (
    FINDING_LABEL_TH,
    HARD_CODES,
    SmartFindingCode,
)
from curriculum_agent.stages.smart_rules import HardCriterion

# A row as it existed before this change: six keys in smart_check, and none of
# the new PLO fields present at all.
_PRE_MIGRATION_ROW = {
    "plo_id": "PLO1",
    "program_id": "cs-test",
    "statement_th": "ออกแบบและพัฒนาซอฟต์แวร์ที่มีคุณภาพได้",
    "statement_en": None,
    "bloom_level": "create",
    "action_verb_th": "ออกแบบ",
    "smart_check": {
        "specific": True,
        "measurable": True,
        "achievable": True,
        "relevant": True,
        "timely": True,
        "notes_th": None,
    },
    "source_need_ids": ["N1"],
    "source_evidence_ids": ["E1"],
    "rationale_th": "ทักษะหลักที่นายจ้างต้องการ",
    "distinctive_feature_th": None,
    "version": 1,
    "smart_retry_count": 0,
    "smart_escalated": False,
    "soft_flags": [],
    "is_optional": False,
}


def test_a_pre_migration_row_still_validates() -> None:
    plo = PLO.model_validate(_PRE_MIGRATION_ROW)

    assert plo.smart_check.findings == []
    assert plo.smart_validated_by == "legacy"
    assert plo.smart_diagnosis_th is None


def test_a_pre_migration_row_with_soft_flags_but_no_findings_validates() -> None:
    """The flags-and-findings agreement check must not fire on a row written
    before findings existed — that is exactly what `legacy` means."""
    row = _PRE_MIGRATION_ROW | {"soft_flags": ["A_level", "R_needs"]}
    plo = PLO.model_validate(row)

    assert plo.soft_flags == ["A_level", "R_needs"]
    assert plo.smart_check.findings == []


def test_a_row_carrying_a_retired_soft_flag_code_still_validates() -> None:
    """ "R_alignment" was emitted for months and is still in two stale docs.
    `soft_flags` stays list[str] so one obsolete string cannot make a program's
    whole PLO list unreadable."""
    row = _PRE_MIGRATION_ROW | {"soft_flags": ["R_alignment"]}

    assert PLO.model_validate(row).soft_flags == ["R_alignment"]


# ------------------------- the two vocabularies -------------------------


def test_the_hard_codes_mirror_the_hard_criteria() -> None:
    """SmartFindingCode and HardCriterion name the same three things. This is
    the extraction-cache failure class: two names for one thing that agree
    until the day they do not."""
    assert {c.value for c in HARD_CODES} == {c.value for c in HardCriterion}


def test_every_finding_code_has_a_thai_label() -> None:
    """The labels reach an Excel workbook a designer sends to MHESI. A missing
    one used to fall through as a raw English code."""
    assert set(FINDING_LABEL_TH) == set(SmartFindingCode)
    assert all(label.strip() for label in FINDING_LABEL_TH.values())


# ------------------------- finding integrity -------------------------


def test_a_hard_code_cannot_be_recorded_as_soft() -> None:
    """A hard code carried as soft would read as non-blocking in the UI while
    pure code was escalating the PLO for exactly that reason."""
    with pytest.raises(ValueError, match="hard criterion"):
        SmartFinding(
            criterion=SmartFindingCode.M_FORBIDDEN, severity="soft", note_th="ใช้คำว่า เข้าใจ"
        )


def test_a_soft_code_cannot_be_recorded_as_hard() -> None:
    with pytest.raises(ValueError, match="soft criterion"):
        SmartFinding(criterion=SmartFindingCode.A_LEVEL, severity="hard", note_th="ระดับสูงเกิน")


def test_hard_findings_are_separable_from_soft_ones() -> None:
    check = SMARTCheck(
        specific=False,
        measurable=True,
        achievable=False,
        relevant=True,
        timely=True,
        findings=[
            SmartFinding(
                criterion=SmartFindingCode.S_VERB, severity="hard", note_th="กริยาไม่อยู่ในประโยค"
            ),
            SmartFinding(
                criterion=SmartFindingCode.A_LEVEL, severity="soft", note_th="ระดับสูงเกินปริญญาตรี"
            ),
        ],
    )

    assert [f.criterion for f in check.hard_findings] == [SmartFindingCode.S_VERB]
    assert check.passed is False


def test_soft_flags_that_contradict_the_findings_are_rejected() -> None:
    """Stored twice because five readers want the flat list, so the two can
    drift — say so here rather than letting the UI and the export disagree."""
    row = _PRE_MIGRATION_ROW | {
        "smart_check": _PRE_MIGRATION_ROW["smart_check"]
        | {
            "achievable": False,
            "findings": [{"criterion": "A_level", "severity": "soft", "note_th": "ระดับสูงเกิน"}],
        },
        "soft_flags": ["R_needs"],
    }

    with pytest.raises(ValueError, match="disagree with"):
        PLO.model_validate(row)


def test_soft_flags_agreeing_with_the_findings_are_accepted() -> None:
    row = _PRE_MIGRATION_ROW | {
        "smart_check": _PRE_MIGRATION_ROW["smart_check"]
        | {
            "achievable": False,
            "findings": [{"criterion": "A_level", "severity": "soft", "note_th": "ระดับสูงเกิน"}],
        },
        "soft_flags": ["A_level"],
        "smart_validated_by": "agent",
        "smart_diagnosis_th": "ระดับ Bloom สูงเกินระดับปริญญาตรี ควรลดเป็น วิเคราะห์",
    }
    plo = PLO.model_validate(row)

    assert plo.smart_validated_by == "agent"
    assert plo.smart_diagnosis_th is not None


def test_a_hard_finding_does_not_have_to_appear_in_soft_flags() -> None:
    """soft_flags is the *soft* half. A hard finding lives in findings only —
    putting it in the flat list would make it look non-blocking."""
    row = _PRE_MIGRATION_ROW | {
        "smart_check": _PRE_MIGRATION_ROW["smart_check"]
        | {
            "specific": False,
            "findings": [
                {"criterion": "S_verb", "severity": "hard", "note_th": "กริยาไม่อยู่ในประโยค"}
            ],
        },
        "soft_flags": [],
        "smart_escalated": True,
    }
    plo = PLO.model_validate(row)

    assert plo.soft_flags == []
    assert len(plo.smart_check.hard_findings) == 1
