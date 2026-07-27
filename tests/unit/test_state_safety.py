# tests/unit/test_state_safety.py
from __future__ import annotations

import pytest

from curriculum_agent.graph import AgentState


@pytest.mark.asyncio
async def test_intake_raises_valueerror_not_keyerror_on_missing_metadata() -> None:
    """intake.run() must raise ValueError (not KeyError) when metadata is missing."""
    from curriculum_agent.stages import intake

    state: AgentState = {"program_id": "test"}
    with pytest.raises(ValueError, match="metadata"):
        await intake.run(state)


@pytest.mark.asyncio
async def test_plo_synthesis_raises_valueerror_not_keyerror_on_missing_metadata() -> None:
    """plo_synthesis.run() must raise ValueError (not KeyError) when metadata is missing."""
    from curriculum_agent.stages import plo_synthesis

    state: AgentState = {
        "program_id": "test",
        "needs": [
            {
                "need_id": "N1",
                "program_id": "test",
                "statement_th": "test",
                "ksec_category": "SS",
                "bloom_level": "apply",
                "member_skill_ids": ["S1"],
                "source_evidence_ids": ["E1"],
                "freq": 1,
                "demand_score": 0.9,
            }
        ],
    }
    with pytest.raises(ValueError, match="metadata"):
        await plo_synthesis.run(state)
