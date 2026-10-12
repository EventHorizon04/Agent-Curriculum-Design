from __future__ import annotations

from curriculum_agent.models import BloomHistogram, KsecCoverage, UnusedNeedFinding
from curriculum_agent.prompts.plo_review import (
    ReviewItem,
    build_plo_review_prompt,
    build_review_observation,
    build_review_refusal,
)
from curriculum_agent.stages.plo_review_facts import ReviewDossier


def _dossier(**kw: object) -> ReviewDossier:
    base: dict = dict(
        program_context="หลักสูตรปริญญาตรี สาขาการแปล",
        degree_level="bachelor",
        items=(
            ReviewItem(
                plo_id="PLO1",
                is_optional=False,
                statement_th="แปลเอกสารธุรกิจโดยใช้เครื่องมือดิจิทัล",
                action_verb_th="แปล",
                bloom_level="apply",
                current_ksec=("S",),
                need_statements_th=("ต้องการบัณฑิตที่แปลเอกสารธุรกิจได้",),
            ),
            ReviewItem(
                plo_id="OPT1",
                is_optional=True,
                statement_th="ประพฤติตนตามจรรยาบรรณนักแปล",
                action_verb_th="ประพฤติตน",
                bloom_level="apply",
                current_ksec=("E", "C"),
                need_statements_th=(),
            ),
        ),
        ksec_coverage=KsecCoverage(
            counts={"K": 0, "S": 1, "E": 0, "C": 0}, missing=["K", "E", "C"], flags=["no_e_or_c"]
        ),
        bloom_histogram=BloomHistogram(
            counts={
                "remember": 0,
                "understand": 0,
                "apply": 1,
                "analyze": 0,
                "evaluate": 0,
                "create": 0,
            },
            degree_level="bachelor",
            flags=[],
        ),
        core_count=1,
        unused_needs=(
            UnusedNeedFinding(
                need_id="n9",
                statement_th="ต้องการบัณฑิตที่ล่ามในการประชุมได้",
                demand_score=0.42,
                ksec_category="S",
                stakeholder_types=["employer"],
                exclusion="lost_on_demand",
            ),
        ),
    )
    base.update(kw)
    return ReviewDossier(**base)


def _turns() -> tuple[str, str]:
    msgs = build_plo_review_prompt(_dossier())
    assert [m["role"] for m in msgs] == ["system", "user"]
    return msgs[0]["content"], msgs[1]["content"]


def test_every_plo_its_needs_and_ksec_reach_the_user_turn() -> None:
    _, user = _turns()
    assert "[PLO1] (หลัก)" in user and "[OPT1] (เสริม)" in user
    assert "ต้องการบัณฑิตที่แปลเอกสารธุรกิจได้" in user
    assert "E|C" in user
    assert "(ไม่พบ Need)" in user


def test_the_code_facts_reach_the_user_turn_as_facts() -> None:
    _, user = _turns()
    assert "K 0 · S 1 · E 0 · C 0" in user
    assert "no_e_or_c" in user
    assert "apply 1" in user
    assert "PLO หลัก 1 ข้อ" in user


def test_the_unused_needs_reach_the_user_turn_with_their_ids() -> None:
    _, user = _turns()
    assert "[n9]" in user and "0.42" in user and "lost_on_demand" in user


def test_no_unused_need_is_said_outright() -> None:
    user = build_plo_review_prompt(_dossier(unused_needs=()))[1]["content"]
    assert "ไม่มี Need สำคัญที่ไม่ได้เป็น PLO" in user


def test_rubric_names_the_six_checks_tools_budget_and_json_keys() -> None:
    system, _ = _turns()
    for key in (
        "redundancies",
        "ksec",
        "bloom",
        "bloom_distribution_th",
        "coverage_th",
        "unused_needs",
        "summary_th",
        "bloom_lookup",
        "check_verbs",
        "need_detail",
    ):
        assert key in system, key
    assert "4 ครั้ง" in system


def test_rubric_says_the_reviewer_changes_nothing_and_does_not_recount() -> None:
    system, _ = _turns()
    assert "ห้ามเขียนประโยค PLO ใหม่" in system
    assert "ไม่ต้องนับใหม่" in system


def test_rubric_keeps_the_existing_rules() -> None:
    system, _ = _turns()
    assert "ไม่ถือว่าซ้ำ" in system  # sharing a field is not redundancy
    assert "มากกว่าหนึ่งหมวด" in system  # KSEC may be several


def test_observation_and_refusal_are_thai_user_turn_text() -> None:
    assert "check_verbs" in build_review_observation("check_verbs", {"plo_id": "PLO1"})
    assert "ปฏิเสธ" in build_review_refusal("ใช้ tool ครบแล้ว")
