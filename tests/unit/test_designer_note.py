"""The designer note reaches the two prompts that author prose, and nothing else."""

from __future__ import annotations

from curriculum_agent.models import BloomLevel, KSECCategory, Need, ProgramMetadata
from curriculum_agent.prompts.designer_note import (
    NOTE_HEADER_TH,
    NOTE_POLICY_TH,
    append_note,
)
from curriculum_agent.prompts.stage_3_plo import build_plo_from_need_prompt
from curriculum_agent.prompts.summarize_need import build_summarize_need_prompt

NOTE = "เน้นทักษะด้าน AI และการวิเคราะห์ข้อมูลขนาดใหญ่"


def _need() -> Need:
    return Need(
        need_id="N1",
        program_id="p1",
        statement_th="ตลาดต้องการผู้ที่วิเคราะห์ข้อมูลขนาดใหญ่ได้",
        ksec_category=KSECCategory.SS,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=["S1"],
        source_evidence_ids=["E1"],
        freq=2,
        demand_score=0.8,
    )


def _meta() -> ProgramMetadata:
    return ProgramMetadata(
        program_id="p1",
        name_th="วิทยาการคอมพิวเตอร์",
        name_en="Computer Science",
        field="Computer Science",
        degree_level="bachelor",
        duration_years=4,
        faculty="วิศวกรรมศาสตร์",
        university="มหาวิทยาลัยทดสอบ",
        vision_th="มุ่งผลิตบัณฑิตที่มีความเชี่ยวชาญด้านเทคโนโลยี",
        mission_th="พันธกิจของหลักสูตร",
        philosophy_th="ปรัชญาของหลักสูตร",
        program_goals_th=["เป้าหมายที่ 1"],
        program_objectives_th=["วัตถุประสงค์ที่ 1"],
    )


# --- append_note ---


def test_append_note_returns_the_message_unchanged_when_there_is_no_note():
    assert append_note("เนื้อหา", None) == "เนื้อหา"
    assert append_note("เนื้อหา", "") == "เนื้อหา"


def test_append_note_adds_a_headed_block_after_the_original_content():
    out = append_note("เนื้อหา", NOTE)
    assert out.startswith("เนื้อหา")
    assert NOTE_HEADER_TH in out
    assert NOTE in out


# --- build_summarize_need_prompt ---


def test_need_prompt_puts_the_note_in_the_user_message_only():
    messages = build_summarize_need_prompt(["วิเคราะห์ข้อมูล"], ["ตัวอย่าง evidence"], "SS", NOTE)
    assert NOTE in messages[1]["content"]
    assert NOTE_HEADER_TH in messages[1]["content"]
    # The note is data the model is given, not policy it is bound by.
    assert NOTE not in messages[0]["content"]


def test_need_prompt_without_a_note_has_no_guidance_block():
    messages = build_summarize_need_prompt(["วิเคราะห์ข้อมูล"], ["ตัวอย่าง evidence"], "SS")
    assert NOTE_HEADER_TH not in messages[1]["content"]


def test_need_prompt_system_text_is_identical_with_and_without_a_note():
    """The policy line is unconditional, so system text never varies per request.

    Prompt text elsewhere in this project is hashed into LLM cache keys
    (skill_extraction._extraction_contract_fingerprint,
    llm_clustering._clustering_contract_fingerprint). A system message that
    changed with the input would make such a fingerprint meaningless.
    """
    with_note = build_summarize_need_prompt(["x"], [], "SS", NOTE)
    without = build_summarize_need_prompt(["x"], [], "SS")
    assert NOTE_POLICY_TH in without[0]["content"]
    assert with_note[0]["content"] == without[0]["content"]


# --- build_plo_from_need_prompt ---


def test_plo_prompt_puts_the_note_in_the_user_message_only():
    messages = build_plo_from_need_prompt(_meta(), [_need()], NOTE)
    assert NOTE in messages[1]["content"]
    assert NOTE_HEADER_TH in messages[1]["content"]
    assert NOTE not in messages[0]["content"]


def test_plo_prompt_without_a_note_has_no_guidance_block():
    messages = build_plo_from_need_prompt(_meta(), [_need()])
    assert NOTE_HEADER_TH not in messages[1]["content"]


def test_plo_prompt_system_text_is_identical_with_and_without_a_note():
    with_note = build_plo_from_need_prompt(_meta(), [_need()], NOTE)
    without = build_plo_from_need_prompt(_meta(), [_need()])
    assert NOTE_POLICY_TH in without[0]["content"]
    assert with_note[0]["content"] == without[0]["content"]


def test_plo_prompt_still_carries_the_need_id_and_statement():
    """Guards against the appended note displacing the Need block it follows."""
    messages = build_plo_from_need_prompt(_meta(), [_need()], NOTE)
    assert "N1" in messages[1]["content"]
    assert "ตลาดต้องการผู้ที่วิเคราะห์ข้อมูลขนาดใหญ่ได้" in messages[1]["content"]
