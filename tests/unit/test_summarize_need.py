from __future__ import annotations

import pytest

from curriculum_agent.models import KSECCategory
from curriculum_agent.prompts.summarize_need import _KSEC_LABEL_TH, build_summarize_need_prompt
from tests.support.needs import RATIONALE_TH

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
    assert _NeedStatement(statement_th=example, rationale_th=RATIONALE_TH).statement_th == example


def test_summarize_prompt_bounds_how_narrow_a_need_may_be() -> None:
    """The only rule here that pushes away from specificity.

    Every other rule drives toward a sentence specific enough to draft a PLO
    from, and none has a lower bound — so a Need could name one task inside a
    profession's work and satisfy all of them. A Need becomes exactly one PLO
    against ten core slots, so one worth less than a tenth of the program still
    spends one.
    """
    system = build_summarize_need_prompt(["การแปลสัญญา"], "S", "apply")[0]["content"]

    assert "ประเภทของงาน" in system
    assert "ภารกิจย่อยชิ้นเดียว" in system


def test_the_narrowness_rule_does_not_license_writing_vaguely() -> None:
    """A model told "too narrow" reaches for "ทักษะการสื่อสาร" unless told not to.

    The boundary is a property of the sentence's object — a class of work rather
    than one instance — never of how precisely it is worded, because the rules
    around it exist to stop exactly the sentence a vaguer rewrite would produce.
    """
    system = build_summarize_need_prompt(["การแปลสัญญา"], "S", "apply")[0]["content"]

    assert "ไม่ได้อนุญาตให้เขียนกว้างลอย ๆ" in system
    # The two rules have to survive together: this one bounds the object, the
    # dilution rule bounds the wording. Losing either leaves the other unopposed.
    assert "ห้ามลดทอนทักษะเฉพาะทาง" in system


def test_each_skill_is_listed_with_the_index_the_answer_cites() -> None:
    """supporting_indices is a list of positions, so the positions must be on the page.

    The names used to arrive as one comma-joined string, so a sentence could not
    say which members it reflects even if it tried — which is why ticket 18's
    silent case (a fifteen-name group whose sentence speaks for three) was
    undetectable by construction rather than merely hard to detect.
    """
    user = build_summarize_need_prompt(["แปลเอกสารสัญญา", "ล่ามการประชุม"], "S", "apply")[1]["content"]
    assert "0 | แปลเอกสารสัญญา" in user
    assert "1 | ล่ามการประชุม" in user


def test_the_prompt_says_leaving_a_skill_out_is_a_right_answer() -> None:
    """Asked which members it covered, a model reaches for all of them.

    Two things follow if nothing pushes back: the coverage figure reads 100%
    everywhere and measures nothing, and the sentence grows to name every member,
    which is the joined skill list `_NeedStatement` rejects. So the prompt says in
    so many words that omitting a member the sentence does not speak for is
    correct, and that the sentence must not be lengthened to cover more.
    """
    system = build_summarize_need_prompt(["ทักษะตัวอย่าง"], "S", "apply")[0]["content"]
    assert "ไม่ต้องพยายามให้ครบทุกข้อ" in system
    assert "ห้ามเขียนประโยคให้ยาวขึ้นเพื่อครอบทุกข้อ" in system


def test_only_the_listed_skills_carry_an_index() -> None:
    """A name past the listing cap cannot be cited, so it must not be numbered."""
    from curriculum_agent.prompts.summarize_need import MAX_LISTED_SKILLS

    names = [f"ทักษะที่{i}" for i in range(MAX_LISTED_SKILLS + 5)]
    user = build_summarize_need_prompt(names, "S", "apply")[1]["content"]
    assert f"{MAX_LISTED_SKILLS - 1} | ทักษะที่{MAX_LISTED_SKILLS - 1}" in user
    assert f"ทักษะที่{MAX_LISTED_SKILLS}" not in user


# --- the apply label no longer hands the model a verb to copy ---------------


def test_the_apply_label_no_longer_carries_a_verb_to_copy() -> None:
    """Every stored apply-level Need read "ประยุกต์ใช้ <resource> ในการ <task>"
    because the model was copying this label's own verb. The replacement names
    the same cognitive demand without a verb a wrapper sentence can echo back.

    Checked against the label value itself, not the whole system message: the
    new wrapper rule legitimately names "ประยุกต์ใช้" as the forbidden shape, so
    a blanket `not in system` would fail on the fix meant to prevent the bug.
    """
    from curriculum_agent.prompts.summarize_need import _BLOOM_LABEL_TH

    assert "ประยุกต์ใช้" not in _BLOOM_LABEL_TH["apply"]


def test_the_apply_group_user_turn_does_not_carry_the_old_verb_either() -> None:
    user = build_summarize_need_prompt(["การดูแลผู้ป่วย"], "S", "apply")[1]["content"]
    assert "ประยุกต์ใช้" not in user
    assert "นำไปลงมือทำงานจริงได้" in user


# --- the new rules this review added ----------------------------------------


def test_summarize_prompt_states_the_wrapper_rule() -> None:
    """ "ประยุกต์ใช้ AI ในการแปล" is the wrapper shape the apply label used to
    teach; the task must be the main verb and the resource a "โดยใช้..." clause.
    """
    system = build_summarize_need_prompt(["การแปลสัญญา"], "S", "apply")[0]["content"]
    assert "ห้ามเขียนในรูป 'ประยุกต์ใช้/ใช้" in system
    assert "โดยใช้..." in system


def test_summarize_prompt_states_the_actor_rule() -> None:
    """The doer has to be a new graduate, not the institution or its management."""
    system = build_summarize_need_prompt(["การแปลสัญญา"], "S", "apply")[0]["content"]
    assert "ผู้ลงมือทำคือบัณฑิตจบใหม่" in system
    assert "not_covered_indices" in system


def test_summarize_prompt_states_the_off_profession_rule() -> None:
    """Another profession's work must not be the sentence's main task."""
    system = build_summarize_need_prompt(["การแปลสัญญา"], "S", "apply")[0]["content"]
    assert "งานของวิชาชีพอื่นที่ไม่ใช่งานของสาขานี้" in system


def test_summarize_prompt_forbids_qualifiers_not_in_the_skill_names() -> None:
    """Stored PLO2 carried "อย่างลึกซึ้ง" copied from its Need, with no member
    skill ever saying so."""
    system = build_summarize_need_prompt(["การแปลสัญญา"], "S", "apply")[0]["content"]
    assert "อย่างลึกซึ้ง" in system  # named as a forbidden example
    assert "ห้ามเติมคำขยายที่ไม่มีในชื่อทักษะของกลุ่ม" in system


def test_summarize_prompt_forbids_floating_quantifiers() -> None:
    system = build_summarize_need_prompt(["การแปลสัญญา"], "S", "apply")[0]["content"]
    assert "ห้ามใช้คำบอกปริมาณลอย ๆ" in system


def test_summarize_prompt_states_the_majority_rule_not_a_percentage() -> None:
    """Every skill name has frequency 1 on the stored corpus, so the rule is
    written as "what most of the group shares", never as an X% threshold."""
    system = build_summarize_need_prompt(["การแปลสัญญา"], "S", "apply")[0]["content"]
    assert "ยึดสิ่งที่ทักษะส่วนใหญ่มีร่วมกัน" in system
    assert "เฉพาะเมื่อทักษะส่วนใหญ่ในกลุ่ม" in system


def test_summarize_prompt_states_the_designer_note_rule() -> None:
    system = build_summarize_need_prompt(["การแปลสัญญา"], "S", "apply")[0]["content"]
    assert "ข้อกำหนดเพิ่มเติมจากผู้ออกแบบหลักสูตร (ถ้ามี) ใช้เลือกถ้อยคำ" in system
    assert "designer_input_used" in system


def test_the_json_spec_names_the_two_new_fields() -> None:
    system = build_summarize_need_prompt(["การแปลสัญญา"], "S", "apply")[0]["content"]
    assert "not_covered_indices" in system
    assert "designer_input_used" in system


# --- the frequency column is opt-in --------------------------------------


def test_the_frequency_column_appears_only_when_frequencies_are_given() -> None:
    with_freq = build_summarize_need_prompt(
        ["แปลเอกสารสัญญา", "ล่ามการประชุม"], "S", "apply", skill_frequencies=[3, 1]
    )[1]["content"]
    assert "0 | แปลเอกสารสัญญา | 3" in with_freq
    assert "1 | ล่ามการประชุม | 1" in with_freq
    assert "เลขลำดับ | ทักษะ | ความถี่" in with_freq


def test_the_listing_is_unchanged_without_frequencies() -> None:
    """The two-column listing a caller that never heard of frequencies relies on
    must not move underneath it."""
    without_freq = build_summarize_need_prompt(["แปลเอกสารสัญญา", "ล่ามการประชุม"], "S", "apply")[1][
        "content"
    ]
    assert "0 | แปลเอกสารสัญญา\n1 | ล่ามการประชุม" in without_freq
    assert "เลขลำดับ | ทักษะ):" in without_freq
