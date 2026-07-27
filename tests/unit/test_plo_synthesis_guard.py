# tests/unit/test_plo_synthesis_guard.py
from __future__ import annotations

import pytest

from curriculum_agent.graph import AgentState
from curriculum_agent.stages.plo_synthesis import run

_METADATA = {
    "program_id": "test",
    "name_th": "วิทยาการคอมพิวเตอร์",
    "name_en": "Computer Science",
    "field": "CS",
    "degree_level": "bachelor",
    "duration_years": 4,
    "faculty": "Engineering",
    "university": "Test University",
    "vision_th": "ผลิตบัณฑิต",
    "mission_th": "พันธกิจของหลักสูตร",
    "philosophy_th": "ปรัชญาของหลักสูตร",
    "program_goals_th": ["เป้าหมายหลักสูตรที่ 1"],
    "program_objectives_th": ["objective 1"],
}


@pytest.mark.asyncio
async def test_run_raises_when_no_needs() -> None:
    """Stage 4 must raise ValueError before hitting LLM when Needs is empty."""
    state: AgentState = {
        "program_id": "test",
        "needs": [],
        "metadata": _METADATA,
    }
    with pytest.raises(ValueError, match="no Needs"):
        await run(state)


@pytest.mark.asyncio
async def test_run_raises_when_needs_missing() -> None:
    """Stage 4 must raise ValueError when the needs key is missing."""
    state: AgentState = {
        "program_id": "test",
        "metadata": _METADATA,
    }
    with pytest.raises(ValueError, match="no Needs"):
        await run(state)
