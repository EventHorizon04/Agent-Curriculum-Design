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
async def test_run_raises_when_no_clusters() -> None:
    """Stage 3 must raise ValueError before hitting LLM when clusters is empty."""
    state: AgentState = {
        "program_id": "test",
        "skill_clusters": [],
        "metadata": _METADATA,
    }
    with pytest.raises(ValueError, match="no skill clusters"):
        await run(state)


@pytest.mark.asyncio
async def test_run_raises_when_clusters_missing() -> None:
    """Stage 3 must raise ValueError when clusters_dicts is missing."""
    state: AgentState = {
        "program_id": "test",
        "metadata": _METADATA,
    }
    with pytest.raises(ValueError, match="no skill clusters"):
        await run(state)
