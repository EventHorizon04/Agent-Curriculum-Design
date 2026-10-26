from __future__ import annotations

from curriculum_agent.prompts.merged_need import build_merged_need_prompt
from curriculum_agent.prompts.summarize_need import (
    NEED_SENTENCE_RULES_HEAD_TH,
    NEED_SENTENCE_RULES_TAIL_TH,
    build_summarize_need_prompt,
)


def _build(context: str | None = "หลักสูตรระดับปริญญาตรี สาขาภาษาจีน") -> list[dict[str, str]]:
    return build_merged_need_prompt(
        ["แปลเอกสารธุรกิจ", "ตรวจคุณภาพงานแปลด้วย AI"],
        ["K", "S"],
        "apply",
        "ทั้งสองข้อคือการแปลเอกสารธุรกิจโดยใช้ AI",
        program_context=context,
    )


def test_it_carries_the_shared_need_sentence_rules() -> None:
    merged = _build()[0]["content"]
    single = build_summarize_need_prompt(["ก", "ข"], "S", "apply", program_context="x")[0][
        "content"
    ]

    for rules in (NEED_SENTENCE_RULES_HEAD_TH, NEED_SENTENCE_RULES_TAIL_TH):
        assert rules in merged and rules in single


def test_the_user_turn_lists_top_skills_tags_level_and_reason() -> None:
    user = _build()[-1]["content"]

    assert "0 | แปลเอกสารธุรกิจ" in user and "1 | ตรวจคุณภาพงานแปลด้วย AI" in user
    assert "(K)" in user and "(S)" in user
    assert "apply" in user
    assert "ทั้งสองข้อคือการแปลเอกสารธุรกิจโดยใช้ AI" in user
    assert "สาขาภาษาจีน" in user


def test_no_context_line_without_a_program_context() -> None:
    messages = _build(None)

    assert "บริบทหลักสูตร" not in messages[-1]["content"]
    assert "ตีความทักษะตามบริบทหลักสูตร" not in messages[0]["content"]
