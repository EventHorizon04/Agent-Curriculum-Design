from __future__ import annotations

from curriculum_agent.prompts.extract_skills import build_extract_skills_prompt


def test_ksec_instruction_offers_four_tags_not_the_old_five():
    system = build_extract_skills_prompt("ข้อความ", "general")[0]["content"]

    assert "K|S|E|C" in system
    assert "GS" not in system
    assert "SS" not in system


def test_schema_asks_for_is_field_relevant():
    system = build_extract_skills_prompt("ข้อความ", "general")[0]["content"]

    assert "is_field_relevant" in system


def test_the_field_of_study_reaches_the_model():
    """The prompt has always said 'ทักษะที่ไม่เกี่ยวข้องกับสาขาวิชา ห้ามเสนอ'
    without naming the field — an unanswerable instruction until now."""
    messages = build_extract_skills_prompt(
        "ข้อความ", "general", field_th="วิทยาการคอมพิวเตอร์", program_name_th="วท.บ. วิทยาการคอมพิวเตอร์"
    )
    joined = "\n".join(m["content"] for m in messages)

    assert "วิทยาการคอมพิวเตอร์" in joined
    assert "วท.บ. วิทยาการคอมพิวเตอร์" in joined


def test_omitting_the_field_leaves_no_dangling_header():
    messages = build_extract_skills_prompt("ข้อความ", "general")
    user = messages[1]["content"]

    assert "สาขาวิชา:" not in user
