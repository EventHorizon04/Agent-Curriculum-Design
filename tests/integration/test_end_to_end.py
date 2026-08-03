from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from curriculum_agent.graph import AgentState, build_graph
from curriculum_agent.models import (
    ProgramMetadata,
    SMARTCheck,
    StakeholderEvidence,
    StakeholderType,
)

_SMART_PASS = SMARTCheck(
    specific=True, measurable=True, achievable=True, relevant=True, timely=True
)

_SKILL_RESP = type("_ExtractedSkillsResponse", (), {"skills": []})()

# _CLUSTER_RESP and _PLO_DRAFTS used to stand in for the deleted SkillCluster
# naming/classification step and its downstream PLO drafts. The single test in
# this file stops at the review_evidence interrupt, before skill extraction,
# need_combination, or PLO synthesis ever run, so neither constant was ever
# read — they were deleted rather than reshaped to the Need-based pipeline.
#
# stakeholder_needs.run no longer calls an LLM either: evidence classification
# is now a pure lookup from stakeholder_type (see classify_evidence_type), so
# there is nothing left to mock for that stage beyond its repository write.


@pytest.fixture
def initial_state(program_metadata: ProgramMetadata) -> AgentState:
    evidence = StakeholderEvidence(
        evidence_id="E1",
        program_id=program_metadata.program_id,
        stakeholder_type=StakeholderType.EMPLOYER,
        source_name="บริษัททดสอบ",
        raw_text_th="ต้องการผู้สำเร็จการศึกษาที่เขียนโปรแกรมได้และทำงานเป็นทีมได้",
    )
    return AgentState(
        program_id=program_metadata.program_id,
        metadata=program_metadata.model_dump(mode="json"),
        raw_evidence=[evidence.model_dump(mode="json")],
    )


@pytest.mark.anyio
async def test_full_graph_runs_and_stops_at_interrupt(
    initial_state: AgentState,
) -> None:
    """Graph should process Stage 0+1 then stop at review_evidence interrupt."""
    from langgraph.checkpoint.memory import MemorySaver

    graph = build_graph(checkpointer=MemorySaver())

    evidence_models = [StakeholderEvidence.model_validate(e) for e in initial_state["raw_evidence"]]

    with (
        patch(
            "curriculum_agent.stages.intake.ProgramRepository.upsert",
            new_callable=AsyncMock,
        ),
        patch(
            "curriculum_agent.stages.intake.EvidenceRepository.list_by_program",
            new=AsyncMock(return_value=evidence_models),
        ),
        patch(
            "curriculum_agent.stages.intake.EvidenceRepository.bulk_insert",
            new_callable=AsyncMock,
        ),
        patch(
            "curriculum_agent.stages.stakeholder_needs.EvidenceRepository.bulk_insert",
            new_callable=AsyncMock,
        ),
    ):
        result = await graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": "test-e2e"}},
        )
        assert "__interrupt__" in result, "Graph should have stopped at review_evidence interrupt"
        assert len(result["__interrupt__"]) > 0, "Interrupt list should be non-empty"
