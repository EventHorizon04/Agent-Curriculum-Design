from __future__ import annotations

import pytest

from curriculum_agent.models import KSECCategory
from curriculum_agent.prompts.summarize_need import _KSEC_LABEL_TH, build_summarize_need_prompt

# Expected labels, written independently of _KSEC_LABEL_TH: if a test asserted
# against the module's own dict value, a mistyped entry would still make the
# test pass (both sides would read the same wrong string). Hardcoding the
# expectation here is what makes a mistyped or dropped entry visible.
_EXPECTED_LABEL_TH = {
    KSECCategory.K: "ความรู้",
    KSECCategory.S: "ทักษะ",
    KSECCategory.EC: "คุณธรรมจริยธรรมและคุณลักษณะบุคคล",
    KSECCategory.E: "คุณธรรมจริยธรรม",
    KSECCategory.C: "คุณลักษณะบุคคล",
}


def test_expected_labels_cover_every_ksec_category() -> None:
    """Guards the test data itself: every KSECCategory member must be exercised."""
    assert set(_EXPECTED_LABEL_TH) == set(KSECCategory)


def test_ksec_label_th_covers_every_category() -> None:
    """A direct, pytest-visible check of the completeness _KSEC_LABEL_TH must hold.

    summarize_need.py also asserts this at import time (raising before any test
    can even collect), so a dropped entry surfaces as a collection error rather
    than a red test here. This test exists so "the dict must cover the enum" is
    also a normal, readable assertion, not only an import-time crash.
    """
    assert set(_KSEC_LABEL_TH) == {c.value for c in KSECCategory}


@pytest.mark.parametrize("ksec", list(KSECCategory))
def test_prompt_carries_the_thai_label_not_the_raw_code(ksec: KSECCategory) -> None:
    """build_summarize_need_prompt must put the Thai label in the prompt.

    Regression test for the bug where _KSEC_LABEL_TH was keyed by the removed
    GS/SS and had no S/EC entries: build_summarize_need_prompt(..., "S", ...)
    or (..., "EC", ...) rendered the bare code straight into the Thai prompt
    text via the ksec.get(ksec, ksec) fallback, with nothing failing.
    """
    messages = build_summarize_need_prompt(["ทักษะตัวอย่าง"], ksec.value, "apply")
    user_message = messages[1]["content"]
    # An exact-line check, not a substring check: "ทักษะ" is itself a substring
    # of the wrong label "ทักษะทั่วไป", so a bare `in` assertion would pass even
    # on a mistyped entry. Pin the whole "หมวดสมรรถนะ: <label> (<code>)" line the
    # production code emits so a mistype is as visible as a drop.
    expected_line = f"หมวดสมรรถนะ: {_EXPECTED_LABEL_TH[ksec]} ({ksec.value})"
    assert expected_line in user_message


def test_the_prompt_asks_for_the_fields_the_caller_actually_parses() -> None:
    """The prompt and the response model are one contract, split across two files.

    need_combination calls this prompt with `_NeedStatement`, so a system message
    that asks for any other JSON shape makes Instructor retry three times and then
    fall back to a `[ต้องทบทวน]` skill list for every single Need — a total
    pipeline failure that no other test in this file notices, because the rest
    assert on the user message only. This is that guard.
    """
    from curriculum_agent.stages.need_combination import _NeedStatement

    system = build_summarize_need_prompt(["ทักษะตัวอย่าง"], "S", "apply")[0]["content"]
    for field in _NeedStatement.model_fields:
        assert field in system, f"the prompt never names '{field}', which the caller parses"


def test_summarize_prompt_carries_the_program_context() -> None:
    """The sentence becomes a PLO for one specific program, so the writer has to
    know which field it is being written for."""
    messages = build_summarize_need_prompt(
        ["การดูแลผู้ป่วย"],
        "S",
        "apply",
        program_context="หลักสูตรระดับปริญญาตรี สาขาพยาบาลศาสตร์",
    )
    assert "หลักสูตรระดับปริญญาตรี สาขาพยาบาลศาสตร์" in messages[1]["content"]


def test_summarize_prompt_forbids_inventing_content_from_the_context() -> None:
    """Context frames the wording; it is not new evidence.

    Every PLO must trace to the evidence behind its Need, so a sentence that
    adds a capability the skill group never named would be an untraceable PLO.
    """
    system = build_summarize_need_prompt(
        ["การดูแลผู้ป่วย"], "S", "apply", program_context="หลักสูตรสาขาพยาบาลศาสตร์"
    )[0]["content"]
    assert "ห้ามเพิ่มเนื้อหาที่ไม่มีในกลุ่มทักษะ" in system


def test_no_program_context_leaves_the_summarize_prompt_unchanged() -> None:
    """Programs created before intake collected a field keep the old prompt."""
    assert build_summarize_need_prompt(["x"], "S", "apply") == build_summarize_need_prompt(
        ["x"], "S", "apply", program_context=None
    )
