"""The rubric, as the validator is told it.

Four of these came from `test_smart_soft_judge_prompt.py` and are not really
prompt tests — they are how `references/obe-principles.md` is pinned in code.
Each has scar tissue behind it, and the prompt is a new place the rubric can
drift silently, so they moved here rather than leaving with the file:

- วิสัยทัศน์ appears nowhere (`obe-principles.md` R, structural component).
- Relevant is judged against the cited Needs and nothing else.
- Measurable asks about a real assessment instrument, not about wording.
- Time-bound defaults to true.

The rest pin the two things the agent prompt adds: that the code gate has the
last word, and that the designer's note has no route in.
"""

from __future__ import annotations

from curriculum_agent.prompts.smart_agent import (
    build_agent_repair_prompt,
    build_repair_observation,
    build_smart_agent_prompt,
)
from curriculum_agent.smart_vocabulary import SmartFindingCode


def _prompt(**overrides: object) -> list[dict[str, str]]:
    kwargs: dict[str, object] = {
        "statement_th": "ออกแบบระบบสารสนเทศตามมาตรฐานอุตสาหกรรมได้",
        "bloom_level": "create",
        "action_verb_th": "ออกแบบ",
        "degree_level": "bachelor",
        "duration_years": 4,
        "cited_needs": [("N1", "ต้องการบัณฑิตที่ออกแบบระบบสารสนเทศได้")],
        "cited_evidence_ids": ["E1"],
        "sibling_count": 2,
    }
    kwargs.update(overrides)
    return build_smart_agent_prompt(**kwargs)  # type: ignore[arg-type]


def _system() -> str:
    return _prompt()[0]["content"]


def _user(**overrides: object) -> str:
    return _prompt(**overrides)[1]["content"]


# ------------------------- the rubric itself -------------------------


def test_every_soft_verdict_is_named_with_its_question() -> None:
    system = _system()
    for verdict in (
        "specific_object_ok",
        "measurable_ok",
        "achievable_ok",
        "relevant_needs_ok",
        "time_bound_ok",
    ):
        assert verdict in system


def test_vision_appears_nowhere() -> None:
    """R's institutional component is a program-level check on
    Need.source_stakeholder_types, settled once per set in plo_synthesis.run. A
    per-PLO text comparison against a vision string fired on every PLO in a set
    and told the designer nothing."""
    prompt = _system() + _user()

    assert "วิสัยทัศน์" not in prompt
    assert "พันธกิจ" not in prompt


def test_relevant_is_judged_against_the_cited_needs_and_nothing_else() -> None:
    """It used to add "and reflects what the labour market wants", which is not
    checkable from a prompt the market is not in — and which marks down a
    correctly-sourced PLO for not sounding like a job ad."""
    system = _system()

    assert "ตลาดแรงงาน" not in system
    assert "ห้ามอ้างกรอบอื่นที่ไม่ได้แสดงไว้" in system


def test_measurable_asks_about_real_assessment_not_just_wording() -> None:
    """A statement can clear the forbidden-word list and still name nothing an
    instrument could observe."""
    system = _system()

    assert "เครื่องมือทางการศึกษา" in system
    assert "การไม่มีคำห้ามยังไม่นับว่าวัดได้" in system


def test_time_bound_defaults_to_true_in_the_instruction() -> None:
    """A PLO carries "by the end of the program" by convention, so silence
    about time is correct and only a conflicting horizon is a finding."""
    system = _system()

    assert "ค่าเริ่มต้นเป็น true" in system
    assert "ภายในปีที่ 2" in system


def test_the_finding_codes_the_prompt_names_are_the_real_ones() -> None:
    """The model keys its notes by these strings, and the exporter and both
    frontend pages render them. A typo here is a note that lands nowhere."""
    system = _system()
    for code in (
        SmartFindingCode.S_OBJECT,
        SmartFindingCode.M_ASSESSABLE,
        SmartFindingCode.A_LEVEL,
        SmartFindingCode.R_NEEDS,
        SmartFindingCode.T_HORIZON,
    ):
        assert code.value in system


# ------------------------- what the agent is told it cannot do -------------


def test_the_prompt_says_the_code_gate_has_the_last_word() -> None:
    """Not a courtesy. A model told it can sign off on M spends its turns
    arguing instead of instructing a repair."""
    system = _system()

    assert "ประกาศว่าผ่านเองไม่ได้" in system
    assert "request_repair" in system


def test_the_prompt_says_it_does_not_write_the_sentence_itself() -> None:
    system = _system()

    assert "คุณไม่ได้เขียนประโยคเอง" in system


def test_the_prompt_asks_for_the_code_check_first() -> None:
    """A sound statement should cost two or three turns, not eight. The cheap
    deterministic answer comes before any investigation."""
    assert "check_hard" in _user()
    assert "เรียกเครื่องมือนี้เป็นรอบแรกเสมอ" in _system()


# ------------------------- what reaches the user turn -------------------------


def test_the_needs_and_the_declared_bloom_level_reach_the_prompt() -> None:
    """achievable_ok used to be asked without being shown the Bloom level, so
    it had to infer it from the sentence."""
    user = _user()

    assert "ต้องการบัณฑิตที่ออกแบบระบบสารสนเทศได้" in user
    # The id beside it is what get_need accepts. Without it the agent passed the
    # sentence as a need_id, was refused, and read that as a broken trail.
    assert "N1" in user
    assert "create" in user
    assert "bachelor" in user
    assert "4 ปี" in user


def test_an_empty_need_list_leaves_no_dangling_header() -> None:
    user = _user(cited_needs=[])

    assert "Need ที่อ้างถึง" not in user


def test_no_sibling_means_no_invitation_to_look_for_one() -> None:
    user = _user(sibling_count=0)

    assert "list_sibling_plos" not in user


# ------------------------- the repair prompt -------------------------


def test_the_repair_prompt_cannot_be_given_the_designer_note() -> None:
    """This invariant used to rest on _build_fix_prompt happening not to take
    the argument. Here it rests on the signature: there is no parameter to
    pass, so the note cannot reach a repair prompt even by mistake."""
    import inspect

    params = set(inspect.signature(build_agent_repair_prompt).parameters)

    assert "note_th" not in params
    assert "note" not in params


def test_the_repair_prompt_carries_the_instruction_and_the_old_sentence() -> None:
    """The model that wrote the diagnosis is not the model that writes the fix,
    so the instruction has to stand on its own — and nothing else belongs: no
    tool results, no sibling PLOs, no rubric recital."""
    messages = build_agent_repair_prompt(
        statement_th="เข้าใจหลักการออกแบบระบบ",
        bloom_level="understand",
        action_verb_th="เข้าใจ",
        degree_level="bachelor",
        instruction_th="แทน 'เข้าใจ' ด้วยกริยาที่สังเกตได้ เช่น อธิบาย",
        criteria=["M_forbidden"],
        keep_th="หลักการออกแบบระบบ",
    )
    user = messages[1]["content"]

    assert "เข้าใจหลักการออกแบบระบบ" in user
    assert "แทน 'เข้าใจ' ด้วยกริยาที่สังเกตได้" in user
    assert "M_forbidden" in user
    assert "หลักการออกแบบระบบ" in user
    assert "list_sibling_plos" not in user


def test_the_repair_prompt_still_forbids_the_unmeasurable_words() -> None:
    """The repair is the last model call before the statement ships, so the
    word list has to be in front of it — not only in the draft prompt."""
    system = build_agent_repair_prompt(
        statement_th="x",
        bloom_level="create",
        action_verb_th="ออกแบบ",
        degree_level="bachelor",
        instruction_th="แก้",
        criteria=[],
    )[0]["content"]

    for word in ("รู้", "จำ", "เข้าใจ", "ซาบซึ้ง", "ตระหนัก", "ศรัทธา", "รัก"):
        assert word in system


def test_the_repair_prompt_asks_for_the_verb_field_to_follow_the_sentence() -> None:
    """A rewrite that changes the verb in the sentence but not action_verb_th
    fails S forever."""
    user = build_agent_repair_prompt(
        statement_th="x",
        bloom_level="create",
        action_verb_th="ออกแบบ",
        degree_level="bachelor",
        instruction_th="แก้",
        criteria=[],
    )[1]["content"]

    assert "action_verb_th" in user


def test_the_repair_observation_reports_the_verdict_both_before_and_after() -> None:
    observation = build_repair_observation(
        before_statement="เข้าใจหลักการ",
        after_statement="อธิบายหลักการได้",
        before_failures=["M_forbidden"],
        after_failures=[],
    )

    assert "M_forbidden" in observation
    assert "(ไม่มี)" in observation
    assert "เข้าใจหลักการ" in observation
    assert "อธิบายหลักการได้" in observation
