from __future__ import annotations

from curriculum_agent.prompts.need_dedup import build_need_dedup_prompt

_ROWS = [
    ("N1", "S", "ต้องการบัณฑิตที่แปลเอกสารธุรกิจไทย-จีนโดยใช้ AI ช่วยตรวจคุณภาพ"),
    ("N2", "S", "ต้องการบัณฑิตที่ควบคุมคุณภาพงานแปลที่ผลิตด้วย AI"),
    ("N3", "EC", "ต้องการบัณฑิตที่ประพฤติตนอย่างมีจริยธรรมในการสื่อสารทางธุรกิจ"),
]


def _text(messages: list[dict[str, str]]) -> str:
    return "\n".join(m["content"] for m in messages)


def test_every_need_appears_once_as_label_tag_and_sentence() -> None:
    user = build_need_dedup_prompt(_ROWS)[-1]["content"]

    for label, tag, statement in _ROWS:
        assert f"{label} | {tag} | {statement}" in user


def test_rows_keep_the_order_they_were_given() -> None:
    """The caller labels in demand order; the prompt must not reshuffle it, or
    N1 stops being the most-demanded Need the model is reading."""
    user = build_need_dedup_prompt(_ROWS)[-1]["content"]

    assert user.index("N1 |") < user.index("N2 |") < user.index("N3 |")


def test_the_rules_the_code_enforces_are_also_told_to_the_model() -> None:
    """accept_groups drops a group that breaks these; telling the model first is
    what keeps a good grouping from being thrown away for a rule it never saw."""
    system = build_need_dedup_prompt(_ROWS)[0]["content"]

    assert "2-5" in system
    assert "2-3" not in system
    assert "ทุกข้อในกลุ่มต้องอยู่ในหมวด KSEC เดียวกัน" not in system, "any KSEC may fold"
    assert "KSEC" in system, "the model is still told the tags may differ"
    assert "ไม่เกินหนึ่งกลุ่ม" in system


def test_an_empty_answer_is_named_as_a_valid_one() -> None:
    """Without this a model asked to find duplicates finds some."""
    system = build_need_dedup_prompt(_ROWS)[0]["content"]

    assert "รายการว่าง" in system


def test_a_duplicate_is_defined_by_main_task_and_object() -> None:
    """The definition is the checkable one — task plus object — and the example
    pair shows that different wording and context do not make two Needs distinct."""
    system = build_need_dedup_prompt(_ROWS)[0]["content"]

    assert "งานหลักและวัตถุหลักเหมือนกัน" in system
    assert "แปลเอกสารธุรกิจโดยใช้เทคโนโลยี" in system
    assert "ประยุกต์ใช้เทคโนโลยีในการแปลเอกสารธุรกิจ" in system


def test_shared_topic_or_source_is_named_as_not_enough() -> None:
    """The failure the evidence-overlap measurement predicts: Needs from the same
    documents, or sharing a tool like AI, read as duplicates."""
    system = build_need_dedup_prompt(_ROWS)[0]["content"]

    assert "ยังไม่พอ" in system


def test_program_context_is_included_when_given_and_absent_otherwise() -> None:
    with_context = _text(
        build_need_dedup_prompt(_ROWS, program_context="หลักสูตรระดับปริญญาตรี สาขาภาษาจีน")
    )
    without = _text(build_need_dedup_prompt(_ROWS))

    assert "หลักสูตรระดับปริญญาตรี สาขาภาษาจีน" in with_context
    assert "หลักสูตร:" not in without
