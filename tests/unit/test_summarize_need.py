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


# The wordings a Need sentence may open with. Hardcoded rather than imported for
# the same reason as _EXPECTED_LABEL_TH above: asserting against the module's own
# string would let a dropped option pass, since both sides would read the same
# shortened list.
_ALLOWED_OPENINGS_TH = (
    "ต้องการ...",
    "ต้องการบัณฑิตที่...",
    "ต้องการหลักสูตรที่...",
    "บัณฑิตต้องมี...",
)


@pytest.mark.parametrize("opening", _ALLOWED_OPENINGS_TH)
def test_summarize_prompt_offers_every_allowed_opening(opening: str) -> None:
    """The sentence no longer has to open with "ตลาดแรงงานต้องการ".

    That prefix carried no information the rest of the sentence did not, and it
    spent characters against a 40-character floor. What the stage actually needs
    is that the sentence state a requirement -- who needs what -- and several
    Thai framings do that equally well. Naming them in the prompt is what stops
    the model from picking one and repeating it across every Need.
    """
    system = build_summarize_need_prompt(["การดูแลผู้ป่วย"], "S", "apply")[0]["content"]

    assert opening in system


def test_summarize_prompt_still_refuses_to_write_a_finished_plo() -> None:
    """The Need/PLO boundary, which the opening rule used to carry by itself.

    plo_synthesis is handed nothing but this sentence, so a Need already written
    as "บัณฑิตวิเคราะห์...ได้" leaves that stage nothing to do but copy, and the
    report can no longer show the step from what the market asked for to what a
    graduate must therefore be able to do. "บัณฑิตต้องมี..." is a requirement and is
    allowed; a finished outcome is not.
    """
    system = build_summarize_need_prompt(["การดูแลผู้ป่วย"], "S", "apply")[0]["content"]

    assert "ห้ามเขียนเป็นผลลัพธ์การเรียนรู้" in system


def test_summarize_prompt_no_longer_mandates_the_labour_market_frame() -> None:
    """Pinned as a decision: the rule that forced one opening is gone, and
    bringing it back should mean changing this line and saying why."""
    system = build_summarize_need_prompt(["การดูแลผู้ป่วย"], "S", "apply")[0]["content"]

    assert "มุมมองของ 'ตลาดแรงงานต้องการอะไร'" not in system


def test_summarize_prompt_refuses_to_dilute_a_specialised_group() -> None:
    """A Need generalised into a competency anyone could claim is unusable.

    It passes every guard in need_grouping — long enough, not a list, no vague
    head/modifier pair — and still describes no program in particular, which is
    expensive against a ceiling of ten core PLOs. The prompt is the only place
    this can be stated.
    """
    system = build_summarize_need_prompt(["การแปลสัญญา", "การจัดการคำศัพท์เฉพาะ"], "S", "apply")[0][
        "content"
    ]

    assert "ห้ามลดทอนทักษะเฉพาะทาง" in system


def test_summarize_prompt_puts_the_professional_function_before_the_generic_skill() -> None:
    """ "ล่ามการเจรจาธุรกิจ", not "การสื่อสาร" — the group's own evidence names a
    function, and the covering skill is a summary of it that a PLO cannot be
    assessed against."""
    system = build_summarize_need_prompt(["การล่ามธุรกิจ"], "S", "apply")[0]["content"]

    assert "ให้เขียนด้วยหน้าที่นั้น" in system


def test_summarize_prompt_asks_for_the_job_identity_check_before_answering() -> None:
    """The self-check that catches what the two rules above miss.

    A sentence can avoid every named generic word and still fit บริหารธุรกิจ,
    นิเทศศาสตร์ and รัฐศาสตร์ at once. No validator can measure that, so it is asked
    for as a last step before the model answers.
    """
    system = build_summarize_need_prompt(["การล่ามธุรกิจ"], "S", "apply")[0]["content"]

    assert "ถ้าลบชื่อสาขาออก" in system


def test_summarize_prompt_keeps_the_subject_this_repo_already_chose() -> None:
    """guidances/market_need_synthesis.md writes every example subject as
    'ผู้ปฏิบัติงาน'. Adopting its rules about specificity must not quietly adopt
    that too: the allowed openings are a decision a5823b9/e09b2d6 landed, and
    reversing it is its own call with its own reasons.
    """
    system = build_summarize_need_prompt(["การล่ามธุรกิจ"], "S", "apply")[0]["content"]

    assert "ผู้ปฏิบัติงาน" not in system
    for opening in _ALLOWED_OPENINGS_TH:
        assert opening in system


def test_the_worked_example_would_survive_the_stage_that_validates_a_need() -> None:
    """The example the prompt shows has to be a sentence _NeedStatement accepts.

    An example that its own validators would bounce teaches the model the shape
    that gets retried — and the three guards it has to clear (length, not a list,
    no vague phrase, no code token) are exactly the ones the rules around it are
    about.
    """
    from curriculum_agent.stages.need_combination import _NeedStatement

    system = build_summarize_need_prompt(["การแปลสัญญา"], "S", "apply")[0]["content"]
    example = "ต้องการบัณฑิตที่ประเมินและปรับปรุงผลลัพธ์การแปลเอกสารธุรกิจระหว่างประเทศ ในบริบทการสื่อสารไทย-จีน"

    assert example in system
    assert _NeedStatement(statement_th=example).statement_th == example
