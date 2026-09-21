"""The program's field must reach both calls need_combination makes.

Skill names alone are ambiguous — "การดูแล" groups with clinical work in a
nursing program and with facility operations in an engineering one — and the
sentence written from a group becomes one PLO for that specific program. The
metadata is already on the state (every route builds it through `_base_state`),
so the only thing that can go wrong is the stage not passing it on.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import BloomLevel, ExtractedSkill, KSECCategory, StakeholderType
from curriculum_agent.stages import need_combination as nc
from tests.support.needs import RATIONALE_TH

_METADATA = {
    "program_id": "nursing",
    "field": "พยาบาลศาสตร์",
    "degree_level": "bachelor",
    "faculty": "คณะพยาบาลศาสตร์",
    "university": "มหาวิทยาลัยตัวอย่าง",
    "duration_years": 4,
}


def _skill(name: str, sid: str) -> ExtractedSkill:
    return ExtractedSkill(
        skill_id=sid,
        program_id="nursing",
        skill_name_th=name,
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.APPLY,
        evidence_span_th=name,
        source_evidence_id="E1",
        source_stakeholder_type=StakeholderType.EMPLOYER,
        classification="need",
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
    )


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Run the stage with both LLM calls and the repository stubbed out."""
    seen: dict[str, object] = {}

    async def fake_cluster(
        names: list[str], target: int | None = None, program_context: str | None = None
    ) -> list[list[int]]:
        seen["cluster_context"] = program_context
        return [list(range(len(names)))]

    async def fake_summarize(model, messages, **kw):  # noqa: ANN001, ANN003
        seen["summarize_prompt"] = "\n".join(m["content"] for m in messages)
        return nc._NeedStatement(
            statement_th="ตลาดแรงงานต้องการผู้ที่ดูแลผู้ป่วยในหอผู้ป่วยตามมาตรฐานวิชาชีพได้อย่างปลอดภัย",
            statement_en="The market needs nurses who care for inpatients safely",
            rationale_th=RATIONALE_TH,
        )

    monkeypatch.setattr(nc, "cluster_skill_names", fake_cluster)
    monkeypatch.setattr(nc, "complete_need_combination", fake_summarize)
    monkeypatch.setattr(nc.NeedRepository, "delete_by_program", AsyncMock())
    monkeypatch.setattr(nc.NeedRepository, "bulk_insert", AsyncMock())
    return seen


async def _run(metadata: dict[str, object] | None, captured: dict[str, object]) -> None:
    state: dict[str, object] = {
        "program_id": "nursing",
        "extracted_skills": [s.model_dump(mode="json") for s in [_skill("การดูแลผู้ป่วย", "S1")]],
    }
    if metadata is not None:
        state["metadata"] = metadata
    await nc.run(state)  # type: ignore[arg-type]


async def test_clustering_is_told_which_program_it_is_grouping_for(
    captured: dict[str, object],
) -> None:
    await _run(_METADATA, captured)
    context = captured["cluster_context"]
    assert isinstance(context, str)
    assert "พยาบาลศาสตร์" in context
    assert "ปริญญาตรี" in context


async def test_the_need_sentence_is_written_for_that_program(
    captured: dict[str, object],
) -> None:
    await _run(_METADATA, captured)
    prompt = captured["summarize_prompt"]
    assert isinstance(prompt, str)
    assert "พยาบาลศาสตร์" in prompt


async def test_a_program_without_a_field_keeps_the_context_free_behaviour(
    captured: dict[str, object],
) -> None:
    """Rows written before intake collected a field must still cluster."""
    await _run({"program_id": "nursing", "degree_level": "bachelor"}, captured)
    assert captured["cluster_context"] is None
    assert "บริบทหลักสูตร" not in str(captured["summarize_prompt"])


async def test_a_state_without_metadata_still_runs(captured: dict[str, object]) -> None:
    """The graph path can reach the stage without metadata on the state."""
    await _run(None, captured)
    assert captured["cluster_context"] is None
