"""A Need that never got its sentence says which of two things went wrong.

Both failures used to produce the same "[ต้องทบทวน]" Need: a sentence the model
wrote and our validators refused, and a call that never reached the model at
all. They need opposite responses — the first only a human can settle, the
second is very likely fixed by re-running the stage — and the designer had
nothing on screen to tell them apart.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from instructor.core.exceptions import InstructorRetryException
from pydantic import ValidationError as PydanticValidationError

from curriculum_agent.models import BloomLevel, ExtractedSkill, KSECCategory, StakeholderType
from curriculum_agent.stages import need_combination as nc
from curriculum_agent.stages import skill_grouping as sg
from tests.support.needs import RATIONALE_TH, run_need_pipeline_from_skills


def _skill(name: str, sid: str, eid: str) -> ExtractedSkill:
    return ExtractedSkill(
        skill_id=sid,
        program_id="cs-test",
        skill_name_th=name,
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.APPLY,
        evidence_span_th=name,
        source_evidence_id=eid,
        source_stakeholder_type=StakeholderType.EMPLOYER,
        classification="need",
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
    )


def _a_real_validation_error() -> PydanticValidationError:
    """The error _NeedStatement actually raises, not a hand-built stand-in."""
    with pytest.raises(PydanticValidationError) as caught:
        nc._NeedStatement(statement_th="สั้นไป", rationale_th=RATIONALE_TH)
    return caught.value


async def _run_with(monkeypatch: pytest.MonkeyPatch, error: Exception) -> list[dict]:
    async def failing_summarize(model, messages, **kw):  # noqa: ANN001, ANN003
        raise error

    async def fake_cluster(
        names: list[str], target: int | None = None, program_context: str | None = None
    ) -> list[list[int]]:
        return [[i for i in range(len(names))]]

    monkeypatch.setattr(sg, "cluster_skill_names", fake_cluster)
    monkeypatch.setattr(nc, "complete_need_combination", failing_summarize)
    monkeypatch.setattr(nc.NeedRepository, "delete_by_program", AsyncMock())
    monkeypatch.setattr(nc.NeedRepository, "bulk_insert", AsyncMock())

    state = await run_need_pipeline_from_skills(
        {
            "program_id": "cs-test",
            "extracted_skills": [_skill("ออกแบบฐานข้อมูล", "S1", "E1").model_dump(mode="json")],
        }
    )
    return state["needs"]


async def test_a_rejected_sentence_is_marked_for_the_designer(monkeypatch):
    """Instructor wraps the last ValidationError positionally, where neither
    __cause__ nor __context__ is set — so the wrapped args have to be read."""
    wrapped = InstructorRetryException(
        _a_real_validation_error(),
        last_completion=None,
        n_attempts=3,
        messages=[],
        create_kwargs={},
        total_usage=0,
    )
    needs = await _run_with(monkeypatch, wrapped)
    assert needs[0]["statement_th"].startswith(nc._REVIEW_MARKER_TH)


async def test_an_unreachable_provider_is_marked_as_a_call_failure(monkeypatch):
    needs = await _run_with(monkeypatch, ConnectionError("connection reset by peer"))
    assert needs[0]["statement_th"].startswith(nc._PROVIDER_MARKER_TH)


async def test_a_provider_error_instructor_gave_up_on_is_still_a_call_failure(monkeypatch):
    """Instructor raises the same exception type either way, so a transport error
    it exhausted its retries over must not read as a content problem."""
    wrapped = InstructorRetryException(
        TimeoutError("read timed out"),
        last_completion=None,
        n_attempts=3,
        messages=[],
        create_kwargs={},
        total_usage=0,
    )
    needs = await _run_with(monkeypatch, wrapped)
    assert needs[0]["statement_th"].startswith(nc._PROVIDER_MARKER_TH)


def test_the_two_markers_are_distinguishable():
    assert not nc._PROVIDER_MARKER_TH.startswith(nc._REVIEW_MARKER_TH)
    assert not nc._REVIEW_MARKER_TH.startswith(nc._PROVIDER_MARKER_TH)


def test_a_validation_error_nested_by_chaining_is_still_found():
    """Raised inside an except block rather than passed as an arg — the other
    shape the walk has to cover."""
    try:
        try:
            raise _a_real_validation_error()
        except PydanticValidationError as exc:
            raise RuntimeError("summarize failed") from exc
    except RuntimeError as outer:
        assert nc._model_answered_but_was_rejected(outer)


def test_a_plain_transport_error_is_not_mistaken_for_a_rejection():
    assert not nc._model_answered_but_was_rejected(ConnectionError("reset"))
