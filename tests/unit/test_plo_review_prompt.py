from __future__ import annotations

from curriculum_agent.prompts.plo_review import ReviewItem, build_plo_review_prompt


def _item(plo_id: str = "PLO1", **kw: object) -> ReviewItem:
    base: dict[str, object] = dict(
        plo_id=plo_id,
        is_optional=False,
        statement_th="แปลเอกสารกฎหมายระหว่างภาษาไทยและภาษาจีน",
        action_verb_th="แปล",
        bloom_level="apply",
        current_ksec=("S",),
        need_statements_th=("ต้องการบัณฑิตที่แปลเอกสารกฎหมายได้",),
    )
    base.update(kw)
    return ReviewItem(**base)  # type: ignore[arg-type]


def _system() -> str:
    return build_plo_review_prompt([_item()])[0]["content"]


def test_every_plo_and_its_needs_and_ksec_reach_the_user_turn() -> None:
    user = build_plo_review_prompt(
        [_item(), _item("OPT1", is_optional=True, current_ksec=("E", "C"))]
    )[1]["content"]
    assert "[PLO1]" in user and "[OPT1]" in user
    assert "แปลเอกสารกฎหมายระหว่างภาษาไทยและภาษาจีน" in user
    assert "ต้องการบัณฑิตที่แปลเอกสารกฎหมายได้" in user
    assert "E|C" in user
    assert "(เสริม)" in user and "(หลัก)" in user


def test_program_context_line_only_when_given() -> None:
    with_ctx = build_plo_review_prompt([_item()], program_context="หลักสูตรระดับปริญญาตรี สาขาการแปล")
    assert "หลักสูตร: หลักสูตรระดับปริญญาตรี สาขาการแปล" in with_ctx[1]["content"]
    assert "หลักสูตร:" not in build_plo_review_prompt([_item()])[1]["content"]


def test_rubric_names_the_three_checks_and_the_json_keys() -> None:
    system = _system()
    for key in ("redundancies", "ksec", "bloom", "bloom_distribution_th", "summary_th"):
        assert key in system


def test_rubric_allows_more_than_one_ksec() -> None:
    assert "มากกว่าหนึ่งหมวด" in _system()


def test_rubric_says_the_reviewer_changes_nothing() -> None:
    system = _system()
    assert "คุณไม่ได้แก้ PLO" in system
    assert "ห้ามเขียนประโยค PLO ใหม่" in system


def test_rubric_says_sharing_a_field_is_not_redundancy() -> None:
    assert "ไม่ถือว่าซ้ำ" in _system()


def test_rubric_allows_a_clean_set() -> None:
    assert "ให้ส่งรายการของเรื่องนั้นว่าง" in _system()
