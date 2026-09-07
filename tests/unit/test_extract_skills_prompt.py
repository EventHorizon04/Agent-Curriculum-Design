from __future__ import annotations

import difflib

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


# The scope statement measured at 50% recall on the noise set: positive side only,
# itemised, roughly 150 characters. Kept whole rather than abbreviated because the
# tests below assert on how it is embedded, not on its wording.
_SCOPE_TH = (
    "หลักสูตรนี้ครอบคลุมการแปลเอกสารธุรกิจและกฎหมายจีน-ไทย การล่ามการเจรจาธุรกิจ "
    "การตรวจแก้งานแปลที่ได้จากเครื่อง (post-editing) และความรู้ด้านวัฒนธรรมและมารยาท"
    "ทางธุรกิจจีนที่จำเป็นต่องานแปลและล่าม"
)

_SCOPE_HEADING = "ขอบเขตของหลักสูตรนี้"
_NO_MINING_SENTENCE = "ห้ามสกัดทักษะจากบรรทัดนี้"


def test_a_program_without_a_scope_statement_gets_no_scope_line():
    """Empty is the common case and has to cost nothing: the guard is meant to
    disable itself for a program whose designer left the field blank."""
    system = build_extract_skills_prompt("ข้อความ", "general")[0]["content"]

    assert _SCOPE_HEADING not in system
    assert _NO_MINING_SENTENCE not in system


def test_an_empty_scope_statement_is_the_same_prompt_as_omitting_it():
    """Byte for byte, including the separators around the conditional block. An
    empty string that appended a bare dash or a blank line would move
    _EXTRACTION_CONTRACT and re-extract the whole corpus for nothing."""
    assert build_extract_skills_prompt("ข้อความ", "general", scope_th="") == (
        build_extract_skills_prompt("ข้อความ", "general")
    )


def test_adding_a_scope_statement_only_inserts_into_the_system_prompt():
    """Nothing that was already there may be reworded to make room for it.

    Every number this feature rests on was measured against the existing prompt
    with the scope block appended to it; an edit anywhere else invalidates them,
    and the diff is the only thing that can say so. Insert-only opcodes are the
    machine-checkable form of "byte for byte, plus the block".
    """
    without = build_extract_skills_prompt("ข้อความ", "general")[0]["content"]
    with_scope = build_extract_skills_prompt("ข้อความ", "general", scope_th=_SCOPE_TH)[0]["content"]

    changes = [
        op
        for op in difflib.SequenceMatcher(None, without, with_scope, autojunk=False).get_opcodes()
        if op[0] != "equal"
    ]

    assert changes, "the scope statement never reached the system prompt"
    assert {op[0] for op in changes} == {"insert"}


def test_the_scope_statement_goes_in_the_system_message_not_beside_the_evidence():
    """Next to the evidence the model reads it as evidence.

    Measured: eight skills whose name and evidence_span_th were copied word for
    word out of the scope statement, on two evidence items containing none of
    those words. The span is then a verbatim quote of the wrong document, so
    is_grounded() clears it — a broken evidence trail that passes its own check.
    """
    messages = build_extract_skills_prompt("ข้อความ", "general", scope_th=_SCOPE_TH)
    system, user = messages[0], messages[1]

    assert system["role"] == "system"
    assert _SCOPE_TH in system["content"]
    assert user["role"] == "user"
    assert _SCOPE_TH not in user["content"]
    assert _SCOPE_HEADING not in user["content"]


def test_the_user_message_is_untouched_by_the_scope_statement():
    """Same evidence, same user message, whatever the program's scope says."""
    plain = build_extract_skills_prompt("ข้อความ", "general")[1]["content"]
    scoped = build_extract_skills_prompt("ข้อความ", "general", scope_th=_SCOPE_TH)[1]["content"]

    assert plain == scoped


def test_the_scope_line_carries_the_sentence_that_forbids_mining_it():
    """The second sentence is not padding — it is the whole reason the first one
    is safe to include. Without it the model treats the scope as one more source
    to extract from."""
    system = build_extract_skills_prompt("ข้อความ", "general", scope_th=_SCOPE_TH)[0]["content"]

    assert _SCOPE_HEADING in system
    assert _NO_MINING_SENTENCE in system
    assert "ทักษะทุกรายการต้องมาจากข้อความ evidence เท่านั้น" in system
    assert "is_field_relevant" in system.split(_SCOPE_HEADING)[1], (
        "the scope line must say what it is a yardstick for"
    )


def test_the_graduate_capability_rule_and_schema_line_are_there_with_or_without_a_scope():
    """Both are static. The flag is what pushed recall from 3/9 to 5/9 with no
    scope statement present at all, so a program that writes no scope still has
    to be asked the question."""
    for kwargs in ({}, {"scope_th": _SCOPE_TH}):
        system = build_extract_skills_prompt("ข้อความ", "general", **kwargs)[0]["content"]

        assert "is_graduate_capability = true" in system
        assert "กิจกรรมหรือภารกิจของสถาบัน/หลักสูตร" in system
        assert "ห้ามตัดทิ้งเอง" in system
        assert "is_graduate_capability: true|false" in system


def test_the_graduate_capability_rule_asks_for_a_flag_rather_than_a_deletion():
    """The variant that let the model drop institutional skills itself took three
    core skills and six institutional ones with it and left no trace of either.
    Keeping them flagged is what makes the judgement reviewable."""
    system = build_extract_skills_prompt("ข้อความ", "general")[0]["content"]
    rule = system.split("is_graduate_capability = true")[1].split("\n-")[0]

    assert "ให้คงไว้แต่ตั้งเป็น false" in rule
    assert "ห้ามตัดทิ้งเอง" in rule


def test_the_task_line_does_not_narrow_the_corpus_to_the_labour_market():
    """Evidence comes from every StakeholderType, not from job postings alone.

    The opening line asked for "ทักษะที่ตลาดแรงงานต้องการ", which is the wrong
    question in front of a สภาวิชาชีพ standard, an alumni interview, or the
    institution's own vision — and institutional_direction is the one source the
    prompt then asks the model to flag rather than drop, so it has to be read,
    not filtered out by the framing.
    """
    system = build_extract_skills_prompt("ข้อความ", "general")[0]["content"]

    assert "ตลาดแรงงาน" not in system


def test_the_task_line_says_the_evidence_may_come_from_any_stakeholder():
    """The prompt is never told the stakeholder type — only requirement/general —
    so if the framing does not say the source varies, nothing does."""
    system = build_extract_skills_prompt("ข้อความ", "general")[0]["content"]

    assert "ผู้มีส่วนได้ส่วนเสีย" in system
