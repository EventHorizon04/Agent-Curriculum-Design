from __future__ import annotations

from curriculum_agent.prompts.plo_classify import build_plo_classify_prompt


def test_prompt_has_system_and_user_messages():
    msgs = build_plo_classify_prompt(
        "ออกแบบและพัฒนาระบบซอฟต์แวร์",
        "cognitive",
        ["Programming (skill_type=knowledge, เฉพาะสาขา)"],
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "generic" in msgs[0]["content"]
    assert "specific" in msgs[0]["content"]


def test_prompt_includes_statement_and_clusters():
    msgs = build_plo_classify_prompt(
        "วิเคราะห์ข้อมูล",
        "cognitive",
        ["Data Analysis (skill_type=knowledge, เฉพาะสาขา)"],
    )
    user = msgs[1]["content"]
    assert "วิเคราะห์ข้อมูล" in user
    assert "Data Analysis" in user


def test_prompt_handles_no_clusters():
    msgs = build_plo_classify_prompt("สื่อสารอย่างมีประสิทธิภาพ", "affective", [])
    assert len(msgs) == 2
    assert isinstance(msgs[1]["content"], str)
