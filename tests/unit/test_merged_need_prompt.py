from __future__ import annotations

import json
from pathlib import Path

from curriculum_agent.prompts.merged_need import build_merged_need_prompt
from curriculum_agent.prompts.summarize_need import (
    NEED_SENTENCE_CONTEXT_RULE_TH,
    NEED_SENTENCE_RULES_HEAD_TH,
    NEED_SENTENCE_RULES_TAIL_TH,
    NEED_SPECIFICITY_CHECK_TH,
    NEED_SUPPORTING_INDICES_RULE_TH,
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


def test_it_carries_every_shared_rule_constant() -> None:
    """The two builders must not drift: each shared rule lives in one constant."""
    merged = _build()[0]["content"]
    for rule in (
        NEED_SENTENCE_RULES_HEAD_TH,
        NEED_SENTENCE_RULES_TAIL_TH,
        NEED_SENTENCE_CONTEXT_RULE_TH,
        NEED_SPECIFICITY_CHECK_TH,
        NEED_SUPPORTING_INDICES_RULE_TH,
    ):
        assert rule in merged


def test_the_context_rule_is_only_present_alongside_a_context() -> None:
    assert NEED_SENTENCE_CONTEXT_RULE_TH not in _build(None)[0]["content"]


def test_frequencies_are_listed_as_a_third_column() -> None:
    user = build_merged_need_prompt(
        ["แปลเอกสารธุรกิจ", "ตรวจคุณภาพงานแปลด้วย AI"],
        ["K", "S"],
        "apply",
        "เหตุผล",
        program_context=None,
        skill_frequencies=[4, 1],
    )[-1]["content"]

    assert "0 | แปลเอกสารธุรกิจ | 4" in user
    assert "1 | ตรวจคุณภาพงานแปลด้วย AI | 1" in user
    assert "ความถี่" in user


def test_without_frequencies_there_is_no_frequency_column() -> None:
    assert "ความถี่" not in _build()[-1]["content"]


def test_summarize_prompt_is_byte_identical_to_its_pre_refactor_text() -> None:
    golden = json.loads(
        (Path(__file__).parent / "golden" / "summarize_need_prompts.json").read_text(
            encoding="utf-8"
        )
    )
    built = [
        build_summarize_need_prompt(["ก", "ข", "ค"], "S", "apply"),
        build_summarize_need_prompt(
            ["ก", "ข", "ค"],
            "K",
            "create",
            note_th="หมายเหตุ",
            program_context="หลักสูตร X",
            skill_frequencies=[3, 2, 1],
        ),
        build_summarize_need_prompt(["ก"], "EC", "analyze", program_context="หลักสูตร X"),
    ]
    assert built == golden
