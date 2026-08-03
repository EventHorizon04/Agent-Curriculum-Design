from __future__ import annotations

from curriculum_agent.prompts.smart_validator import build_smart_soft_judge_prompt

_NEEDS = ["ตลาดต้องการผู้ที่วิเคราะห์ข้อมูลขนาดใหญ่ได้", "ตลาดต้องการผู้ที่สื่อสารผลวิเคราะห์ได้"]


def _built() -> str:
    messages = build_smart_soft_judge_prompt(
        "วิเคราะห์ข้อมูลขนาดใหญ่เพื่อเสนอแนวทางเชิงธุรกิจได้",
        "bachelor",
        4,
        _NEEDS,
    )
    return "\n".join(m["content"] for m in messages)


def test_all_five_verdicts_are_requested() -> None:
    system = build_smart_soft_judge_prompt("PLO", "bachelor", 4, _NEEDS)[0]["content"]

    for key in (
        "specific_object_ok",
        "measurable_ok",
        "achievable_ok",
        "relevant_needs_ok",
        "time_bound_ok",
    ):
        assert key in system


def test_the_needs_reach_the_user_message() -> None:
    """R is judged against the Needs the PLO cites, so they have to be in the
    prompt — this is what replaces the old vision-text comparison."""
    user = build_smart_soft_judge_prompt("PLO", "bachelor", 4, _NEEDS)[1]["content"]

    for need in _NEEDS:
        assert need in user


def test_the_qualification_level_and_duration_reach_the_prompt() -> None:
    """A is about plausibility for the level AND within the time available."""
    built = _built()

    assert "bachelor" in built
    assert "4" in built


def test_vision_appears_nowhere() -> None:
    """The institutional component of R is settled in code from
    Need.source_stakeholder_types, not by asking a model to compare paragraphs."""
    assert "วิสัยทัศน์" not in _built()


def test_measurable_asks_about_real_assessment_not_just_wording() -> None:
    system = build_smart_soft_judge_prompt("PLO", "bachelor", 4, _NEEDS)[0]["content"]

    assert "ประเมิน" in system


def test_time_bound_defaults_to_true_in_the_instruction() -> None:
    """A PLO that says nothing about time is correct by convention; only a
    conflicting horizon is a finding."""
    system = build_smart_soft_judge_prompt("PLO", "bachelor", 4, _NEEDS)[0]["content"]

    assert "สิ้นสุดหลักสูตร" in system
    assert "true" in system.lower()


def test_an_empty_need_list_leaves_no_dangling_header() -> None:
    user = build_smart_soft_judge_prompt("PLO", "bachelor", 4, [])[1]["content"]

    assert "Need ที่อ้างถึง:" not in user
