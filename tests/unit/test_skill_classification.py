from __future__ import annotations

from curriculum_agent.stages.skill_extraction import classify_skills


def _raw(name: str, eid: str, *, relevant: bool = True) -> dict[str, object]:
    return {"skill_name_th": name, "evidence_id": eid, "is_field_relevant": relevant}


def test_a_skill_from_requirement_evidence_is_a_requirement():
    result = classify_skills([_raw("จรรยาบรรณวิชาชีพ", "E1")], {"E1": "requirement"})

    assert result["จรรยาบรรณวิชาชีพ"] == "requirement"


def test_two_distinct_evidence_items_make_a_need():
    result = classify_skills(
        [_raw("วิเคราะห์ข้อมูล", "E1"), _raw("วิเคราะห์ข้อมูล", "E2")],
        {"E1": "general", "E2": "general"},
    )

    assert result["วิเคราะห์ข้อมูล"] == "need"


def test_a_single_evidence_item_makes_a_want():
    result = classify_skills([_raw("เล่นดนตรีไทย", "E1")], {"E1": "general"})

    assert result["เล่นดนตรีไทย"] == "want"


def test_off_field_skill_is_unclassified():
    result = classify_skills(
        [_raw("ขับรถยนต์", "E1", relevant=False), _raw("ขับรถยนต์", "E2", relevant=False)],
        {"E1": "general", "E2": "general"},
    )

    assert result["ขับรถยนต์"] == "unclassified"


def test_requirement_beats_a_want_frequency_of_one():
    """A mandate does not become optional because few sources repeated it."""
    result = classify_skills([_raw("จรรยาบรรณวิชาชีพ", "E1")], {"E1": "requirement"})

    assert result["จรรยาบรรณวิชาชีพ"] == "requirement"


def test_requirement_beats_an_off_field_verdict():
    """Legal and institutional mandates stay in the pipeline whatever the model
    thinks of their field fit — the designer removes them, not the extractor."""
    result = classify_skills(
        [_raw("ปฏิบัติตามข้อบังคับสภาวิชาชีพ", "E1", relevant=False)], {"E1": "requirement"}
    )

    assert result["ปฏิบัติตามข้อบังคับสภาวิชาชีพ"] == "requirement"


def test_a_name_matching_a_requirement_skill_is_promoted():
    """Same capability, two sources: one mandates it, one merely mentions it.
    The mandate wins for both."""
    result = classify_skills(
        [_raw("ความปลอดภัยของข้อมูล", "E1"), _raw("  ความปลอดภัยของข้อมูล  ", "E2")],
        {"E1": "requirement", "E2": "general"},
    )

    assert result["ความปลอดภัยของข้อมูล"] == "requirement"


def test_names_are_matched_after_normalisation():
    result = classify_skills(
        [_raw("Data  Analysis", "E1"), _raw("data analysis", "E2")],
        {"E1": "general", "E2": "general"},
    )

    assert len(result) == 1
    assert next(iter(result.values())) == "need"


def test_missing_evidence_class_defaults_to_general():
    result = classify_skills([_raw("ทักษะลึกลับ", "E9")], {})

    assert result["ทักษะลึกลับ"] == "want"
