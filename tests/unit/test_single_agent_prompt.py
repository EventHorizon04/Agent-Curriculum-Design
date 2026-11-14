"""The single-agent prompt: one system prompt for every task, four task openers.

The system prompt is the whole of the single agent's behaviour, so these tests
pin what it must carry (every tool and action name, the forbidden words, the
seven soft codes) and what it must not (a stage name of the multi pipeline, the
retired `vision_th` field). The openers are pinned on what they list.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from curriculum_agent.prompts import single_agent
from curriculum_agent.prompts.designer_note import NOTE_HEADER_TH, NOTE_POLICY_TH
from curriculum_agent.prompts.single_agent import (
    EvidenceIndexRow,
    NeedBrief,
    build_closing_instruction,
    build_dropped_marker,
    build_merge_need_task,
    build_needs_task,
    build_observation,
    build_one_plo_task,
    build_plos_task,
    build_refusal,
    build_single_agent_system,
    build_turns_left_note,
)
from curriculum_agent.smart_vocabulary import FORBIDDEN_WORDS_TH, HARD_CODES, SmartFindingCode

FORBIDDEN_WORDS = sorted(FORBIDDEN_WORDS_TH)
SOFT_CODES = [code.value for code in SmartFindingCode if code not in HARD_CODES]

ROW_A = EvidenceIndexRow(
    evidence_id="ev-a",
    stakeholder_type="employer",
    source_name="บริษัทแปลภาษา",
    classification="general",
    total_chars=978,
    parts=1,
)
ROW_B = EvidenceIndexRow(
    evidence_id="ev-b",
    stakeholder_type="professional_council",
    source_name="มาตรฐานวิชาชีพ",
    classification="requirement",
    total_chars=13000,
    parts=3,
)


def _need(need_id: str, statement_th: str, *, score: float = 0.5) -> NeedBrief:
    return NeedBrief(
        need_id=need_id,
        statement_th=statement_th,
        ksec_categories=("S",),
        bloom_level="apply",
        demand_score=score,
        stakeholder_types=("employer", "alumni"),
        evidence_ids=("ev-a", "ev-b"),
    )


CORE = _need("need-core", "ต้องการบัณฑิตที่แปลเอกสารสัญญาธุรกิจ", score=0.8)
OPTIONAL = _need("need-opt", "ต้องการบัณฑิตที่ล่ามการประชุม", score=0.2)
UNUSED = _need("need-cut", "ต้องการบัณฑิตที่เขียนบทแปลบรรณาธิการ", score=0.1)

# Stage names of the multi pipeline. The single agent is one structure, not a
# renamed chain, and naming them would hand the model a script to imitate.
MULTI_STAGE_NAMES = [
    "intake",
    "stakeholder_needs",
    "skill_extraction",
    "skill_grouping",
    "need_combination",
    "need_dedup",
    "need_analysis",
    "plo_synthesis",
    "plo_review",
    "plo_report",
    "validation",
]


def test_system_prompt_takes_no_arguments_and_is_stable() -> None:
    assert build_single_agent_system() == build_single_agent_system()
    assert inspect.signature(build_single_agent_system).parameters == {}


@pytest.mark.parametrize(
    "token",
    [
        "get_evidence",
        "get_need",
        "need_detail",
        "list_sibling_plos",
        "check_hard",
        "bloom_lookup",
        "check_verbs",
        "call_tool",
        "save_need",
        "drop_need",
        "save_plo",
        "drop_plo",
        "note",
        "finish",
        *FORBIDDEN_WORDS,
        *SOFT_CODES,
    ],
)
def test_system_prompt_names_every_tool_action_and_rule(token: str) -> None:
    assert token in build_single_agent_system()


@pytest.mark.parametrize(
    "field",
    [
        "specific_object_ok",
        "measurable_ok",
        "achievable_ok",
        "actor_ok",
        "scope_ok",
        "relevant_needs_ok",
        "time_bound_ok",
        "findings_th",
        "points_th",
        "plo_ref",
        "source_evidence_ids",
        "source_need_ids",
        "ksec_categories",
        "action_verb_th",
    ],
)
def test_system_prompt_names_the_fields_the_actions_carry(field: str) -> None:
    assert field in build_single_agent_system()


def test_system_prompt_names_every_ksec_tag_and_bloom_level() -> None:
    system = build_single_agent_system()
    for level in ("remember", "understand", "apply", "analyze", "evaluate", "create"):
        assert level in system
    for tag in ("K", "S", "E", "C"):
        assert f"- {tag} " in system


@pytest.mark.parametrize("name", [*MULTI_STAGE_NAMES, "vision_th"])
def test_system_prompt_names_no_multi_stage_and_no_vision_field(name: str) -> None:
    assert name not in build_single_agent_system()


def test_system_prompt_says_how_to_read_the_designers_note() -> None:
    assert NOTE_POLICY_TH in build_single_agent_system()


def test_needs_task_lists_every_evidence_item_without_its_text() -> None:
    msg = build_needs_task(program_context="ctx", scope_th=None, evidence_index=[ROW_A, ROW_B])
    assert ROW_A.evidence_id in msg and ROW_B.evidence_id in msg and "RAW TEXT" not in msg
    assert "ctx" in msg
    assert "requirement" in msg and "general" in msg
    assert "3 ส่วน" in msg


def test_needs_task_shows_scope_only_when_the_designer_wrote_one() -> None:
    without = build_needs_task(program_context="ctx", scope_th=None, evidence_index=[ROW_A])
    with_scope = build_needs_task(
        program_context="ctx", scope_th="งานแปลและล่าม", evidence_index=[ROW_A]
    )
    assert "ขอบเขตวิชาชีพ" not in without
    assert "งานแปลและล่าม" in with_scope and "ขอบเขตวิชาชีพ" in with_scope


def test_plos_task_names_core_optional_and_unused_needs() -> None:
    msg = build_plos_task(
        program_context="ctx",
        scope_th=None,
        core_needs=[CORE],
        optional_needs=[OPTIONAL],
        unused_needs=[UNUSED],
        note_th=None,
    )
    for need in (CORE, OPTIONAL, UNUSED):
        assert need.need_id in msg and need.statement_th in msg
    assert msg.index(CORE.need_id) < msg.index(OPTIONAL.need_id) < msg.index(UNUSED.need_id)
    assert NOTE_HEADER_TH not in msg


def test_plos_task_carries_the_designers_note_under_its_header() -> None:
    msg = build_plos_task(
        program_context="ctx",
        scope_th=None,
        core_needs=[CORE],
        optional_needs=[],
        unused_needs=[],
        note_th="เน้นงานแปลกฎหมาย",
    )
    assert f"{NOTE_HEADER_TH}\nเน้นงานแปลกฎหมาย" in msg


def test_one_plo_task_shows_the_current_statement_only_when_there_is_one() -> None:
    fresh = build_one_plo_task(
        program_context="ctx", scope_th=None, needs=[CORE], current_statement_th=None, note_th=None
    )
    again = build_one_plo_task(
        program_context="ctx",
        scope_th=None,
        needs=[CORE],
        current_statement_th="แปลเอกสารสัญญาธุรกิจไทย-อังกฤษ",
        note_th=None,
    )
    assert CORE.need_id in fresh and CORE.need_id in again
    assert "ประโยคปัจจุบัน" not in fresh
    assert "แปลเอกสารสัญญาธุรกิจไทย-อังกฤษ" in again and "ประโยคปัจจุบัน" in again


def test_merge_task_lists_every_need_and_the_reason() -> None:
    msg = build_merge_need_task(
        program_context="ctx", needs=[CORE, OPTIONAL], reason_th="ขอสมรรถนะเดียวกัน"
    )
    assert CORE.need_id in msg and OPTIONAL.need_id in msg and "ขอสมรรถนะเดียวกัน" in msg
    assert "ev-a" in msg


def test_loop_messages_carry_what_they_are_given() -> None:
    assert "get_evidence" in build_observation("get_evidence", '{"part": 1}')
    assert '{"part": 1}' in build_observation("get_evidence", '{"part": 1}')
    assert "เหตุผล X" in build_refusal("เหตุผล X")
    assert "5" in build_turns_left_note(5)
    assert "finish" in build_closing_instruction()


def test_dropped_marker_points_at_the_note_or_at_a_reread() -> None:
    noted = build_dropped_marker("ev-a", "ผู้ใช้บัณฑิตขอนักแปลสัญญา")
    unnoted = build_dropped_marker("ev-a", None)
    assert "ev-a" in noted and "ผู้ใช้บัณฑิตขอนักแปลสัญญา" in noted
    assert "ev-a" in unnoted and "get_evidence" in unnoted


def test_prompt_module_imports_nothing_from_stages() -> None:
    tree = ast.parse(Path(inspect.getfile(single_agent)).read_text(encoding="utf-8"))
    imported = [
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not [name for name in imported if name.startswith("curriculum_agent.stages")]
