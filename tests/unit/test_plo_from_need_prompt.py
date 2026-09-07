from __future__ import annotations

from curriculum_agent.models import Need, ProgramMetadata
from curriculum_agent.prompts.stage_3_plo import build_plo_from_need_prompt

_META = ProgramMetadata(
    program_id="program",
    university="มหาวิทยาลัยตัวอย่าง",
    faculty="คณะพยาบาลศาสตร์",
    field="พยาบาลศาสตร์",
    degree_level="bachelor",
    duration_years=4,
)


def _need(statement_th: str, need_id: str = "N01") -> Need:
    return Need(
        need_id=need_id,
        program_id="program",
        statement_th=statement_th,
        ksec_category="S",
        bloom_level="analyze",
        demand_score=0.7,
        member_skill_ids=["S1"],
        freq=3,
        source_evidence_ids=["ev-1"],
        source_stakeholder_types=["employer"],
    )


def _system(*statements: str) -> str:
    needs = [_need(s, f"N{i:02d}") for i, s in enumerate(statements, start=1)]
    return build_plo_from_need_prompt(_META, needs)[0]["content"]


def test_the_rule_contrasts_an_outcome_with_a_requirement() -> None:
    """The contrast used to be learner-voice against market-voice, which worked
    only while every Need opened "ตลาดแรงงานต้องการ...". A Need may now arrive as
    "บัณฑิตต้องมี...", and against the old rule that already reads as the learner's
    voice — so the model is told it has nothing to convert and copies the
    sentence. What separates the two is outcome against requirement, not whose
    voice the sentence is in.
    """
    system = _system("ต้องการบัณฑิตที่ประเมินอาการผู้ป่วยแรกรับได้")

    assert "ห้ามคัดลอก" in system
    assert "บัณฑิตต้องมี" in system


def test_the_rule_no_longer_turns_on_whose_voice_the_need_is_in() -> None:
    """Pinned as a decision: bringing the old contrast back should mean changing
    this line and saying why."""
    system = _system("ต้องการบัณฑิตที่ประเมินอาการผู้ป่วยแรกรับได้")

    assert "ไม่ใช่ 'ตลาดต้องการอะไร'" not in system


def test_a_graduate_side_need_still_reaches_the_prompt_intact() -> None:
    """The Need is quoted, whatever framing it was written in — the model cannot
    convert a sentence it was not shown."""
    statement = "บัณฑิตต้องมีความสามารถประเมินอาการผู้ป่วยแรกรับในสถานการณ์ฉุกเฉิน"
    user = build_plo_from_need_prompt(_META, [_need(statement)])[1]["content"]

    assert statement in user
