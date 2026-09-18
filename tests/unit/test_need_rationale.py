"""`Need.rationale_th` — the model's account of why one skill group is one demand.

An explanation, not a trail. `source_evidence_ids` is what immutable rule 2 is
about and is assembled in code; this field is free text nothing can check against
the evidence, so what these tests protect is the boundary between the two and the
guards that stop the field becoming a heading with nothing under it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from curriculum_agent.models import Need
from curriculum_agent.prompts.summarize_need import (
    MAX_RATIONALE_CHARS,
    MIN_RATIONALE_CHARS,
    build_summarize_need_prompt,
)
from curriculum_agent.stages import need_combination as nc
from tests.support.needs import RATIONALE_TH


def _fields_named_in_prompt(system: str) -> set[str]:
    """Field names the prompt spells out in its response block.

    Read off the instruction text rather than off the model class, so that the
    two are free to disagree — which is the whole point of the check.
    """
    names: set[str] = set()
    for line in system.splitlines():
        if not line.startswith("  ") or ":" not in line:
            continue
        name = line.strip().split(":")[0].strip()
        if name.isascii() and name.isidentifier():
            names.add(name)
    return names


def test_the_prompt_asks_for_no_field_the_caller_cannot_parse() -> None:
    """The other direction of test_the_prompt_asks_for_the_fields_the_caller_actually_parses.

    That test walks `_NeedStatement.model_fields` and checks each name appears in
    the prompt, which is one-way: adding a field to the *prompt* and forgetting
    the model leaves it green while Pydantic drops whatever the model wrote, and
    the tokens are paid on every call of this stage with nobody the wiser. This
    is the guard that catches that, and the reason it exists is that adding
    rationale_th is exactly the change that would have hit it.
    """
    system = build_summarize_need_prompt(["การแปลสัญญา"], "S", "apply")[0]["content"]
    unparsed = _fields_named_in_prompt(system) - set(nc._NeedStatement.model_fields)
    assert not unparsed, f"the prompt asks for {sorted(unparsed)}, which _NeedStatement drops"


def test_the_field_detector_would_actually_catch_one() -> None:
    """The guard above is only worth its line if its reader works.

    A one-way test that silently matches nothing is the same failure it exists to
    catch, so the detector is fed a response block carrying a field no model
    class declares and has to report exactly that one.
    """
    fabricated = "\n".join(
        [
            "ตอบเป็น JSON object ที่มี field:",
            "  statement_th: string (ประโยคภาษาไทย)",
            "  evidence_ids: string (รายการรหัสหลักฐาน)",
        ]
    )
    assert _fields_named_in_prompt(fabricated) - set(nc._NeedStatement.model_fields) == {
        "evidence_ids"
    }


def test_a_reason_that_says_nothing_is_rejected() -> None:
    """The failure mode this field has, and the one it must not ship with.

    "เป็นทักษะที่เกี่ยวข้องกัน" is not a weak answer — it is a claim with nothing
    behind it, in the one place a reader looks for the justification of a Need.
    The scan is the same find_vague_phrase the statement uses, because a second
    vocabulary for one rule is how two copies of it come to disagree.
    """
    with pytest.raises(ValidationError) as exc:
        nc._NeedStatement(
            statement_th="ต้องการบัณฑิตที่แปลและตรวจสอบเอกสารสัญญาทางธุรกิจได้อย่างถูกต้อง",
            rationale_th="ทุกอย่างในกลุ่มนี้เป็นทักษะที่เกี่ยวข้องกันในสายงานเดียวกัน",
        )
    assert "rationale_th" in str(exc.value)


@pytest.mark.parametrize(
    ("rationale", "why"),
    [
        ("สั้นมาก", "under the floor"),
        ("ก" * (MAX_RATIONALE_CHARS + 1), "over the ceiling"),
    ],
)
def test_the_length_bounds_are_enforced(rationale: str, why: str) -> None:
    """The ceiling is not cosmetic: this rides on every Need row, renders inside a
    card beside the sentence, and is the one field in the response with no other
    rule pushing back on length."""
    with pytest.raises(ValidationError):
        nc._NeedStatement(
            statement_th="ต้องการบัณฑิตที่แปลและตรวจสอบเอกสารสัญญาทางธุรกิจได้อย่างถูกต้อง",
            rationale_th=rationale,
        )


def test_a_real_reason_is_accepted() -> None:
    written = nc._NeedStatement(
        statement_th="ต้องการบัณฑิตที่แปลและตรวจสอบเอกสารสัญญาทางธุรกิจได้อย่างถูกต้อง",
        rationale_th=RATIONALE_TH,
    )
    assert written.rationale_th == RATIONALE_TH


def test_the_prompt_states_the_same_bounds_the_validator_enforces() -> None:
    """One number in two places is how an instruction and the rule that rejects
    its answer drift apart — the reason both constants live in the prompt module."""
    system = build_summarize_need_prompt(["การแปลสัญญา"], "S", "apply")[0]["content"]

    assert f"{MIN_RATIONALE_CHARS}-{MAX_RATIONALE_CHARS} ตัวอักษร" in system


def test_a_need_written_before_the_field_still_validates() -> None:
    """A Need also arrives as a plain dict — from a LangGraph checkpoint suspended
    across the deploy that added the column — and those never pass through the
    migration, so the field cannot be required on the model."""
    need = Need.model_validate(
        {
            "need_id": "n1",
            "program_id": "p1",
            "statement_th": "ต้องการบัณฑิตที่ดูแลระบบสารสนเทศขององค์กรได้",
            "ksec_category": "S",
            "bloom_level": "apply",
            "member_skill_ids": ["s1"],
            "source_evidence_ids": ["e1"],
            "freq": 1,
            "demand_score": 0.5,
        }
    )
    assert need.rationale_th == ""


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    path = next(Path("migrations/versions").glob("*_need_rationale.py"))
    spec = importlib.util.spec_from_file_location("need_rationale_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_backfill_only_touches_rows_that_have_no_reason(migration: ModuleType) -> None:
    """Re-running the migration, or running it after new rows exist, must not
    overwrite a reason a model actually wrote."""
    assert "WHERE rationale_th = ''" in migration.BACKFILL_NEED_RATIONALE


def test_the_backfill_writes_only_what_the_row_already_knows(migration: ModuleType) -> None:
    """The honest answer under "why are these skills one demand" for a row nobody
    recorded one for is that nobody did — plus the facts the row carries.

    Composing a plausible reason from the member skill names would put an
    explanation no model ever gave underneath a Need, in the field a reader takes
    as its justification. The backfill therefore reads `needs` and joins nothing.
    """
    sql = migration.BACKFILL_NEED_RATIONALE

    assert "[สร้างย้อนหลัง]" in sql, "the backfilled text must say it was backfilled"
    assert "jsonb_array_length(member_skill_ids)" in sql
    assert "ksec_category" in sql
    assert "skills" not in sql, "a reason must not be composed out of the member skill names"
