from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from curriculum_agent.models import (
    BloomLevel,
    Domain,
    ProgramMetadata,
    SkillCluster,
)
from curriculum_agent.stages.plo_synthesis import _PLODraft, _PLODraftList, _SmartSoftJudge, run

_SOFT_OK = _SmartSoftJudge(specific_object_ok=True, achievable_ok=True, relevant_alignment_ok=True)

_SAMPLE_DRAFTS = _PLODraftList(
    plos=[
        _PLODraft(
            plo_id=f"PLO-{i}",
            statement_th=f"ออกแบบและพัฒนาระบบสารสนเทศสำหรับงาน {i} ได้อย่างมีประสิทธิภาพ",
            domain=Domain.COGNITIVE,
            bloom_level=BloomLevel.CREATE,
            is_subject_specific=True,
            action_verb_th="ออกแบบ",
            source_cluster_ids=["C1"],
            source_evidence_ids=["E1"],
            rationale_th=f"ทักษะที่นายจ้างต้องการลำดับที่ {i}",
        )
        for i in range(1, 7)
    ]
)


@pytest.fixture
def state(program_metadata: ProgramMetadata, skill_cluster: SkillCluster) -> dict:
    return {
        "program_id": program_metadata.program_id,
        "metadata": program_metadata.model_dump(mode="json"),
        "skill_clusters": [skill_cluster.model_dump(mode="json")],
    }


@pytest.mark.anyio
async def test_stage_3_produces_plos(state: dict) -> None:
    with (
        patch(
            "curriculum_agent.stages.plo_synthesis.complete_heavy",
            new_callable=AsyncMock,
            return_value=_SAMPLE_DRAFTS,
        ),
        patch(
            "curriculum_agent.stages.plo_synthesis.complete_light",
            new_callable=AsyncMock,
            return_value=_SOFT_OK,
        ),
        patch(
            "curriculum_agent.stages.plo_synthesis.PLORepository.bulk_insert",
            new_callable=AsyncMock,
        ),
    ):
        result = await run(state)

    plos = result["plos"]
    assert 6 <= len(plos) <= 10, f"Expected 6-10 PLOs, got {len(plos)}"


@pytest.mark.anyio
async def test_stage_3_no_forbidden_words(state: dict) -> None:
    with (
        patch(
            "curriculum_agent.stages.plo_synthesis.complete_heavy",
            new_callable=AsyncMock,
            return_value=_SAMPLE_DRAFTS,
        ),
        patch(
            "curriculum_agent.stages.plo_synthesis.complete_light",
            new_callable=AsyncMock,
            return_value=_SOFT_OK,
        ),
        patch(
            "curriculum_agent.stages.plo_synthesis.PLORepository.bulk_insert",
            new_callable=AsyncMock,
        ),
    ):
        result = await run(state)

    from curriculum_agent.models import FORBIDDEN_WORDS_TH

    for plo_dict in result["plos"]:
        stmt = plo_dict["statement_th"]
        for word in FORBIDDEN_WORDS_TH:
            assert word not in stmt, f"Forbidden word '{word}' found in: {stmt}"


@pytest.mark.anyio
async def test_stage_3_source_cluster_ids_non_empty(state: dict) -> None:
    with (
        patch(
            "curriculum_agent.stages.plo_synthesis.complete_heavy",
            new_callable=AsyncMock,
            return_value=_SAMPLE_DRAFTS,
        ),
        patch(
            "curriculum_agent.stages.plo_synthesis.complete_light",
            new_callable=AsyncMock,
            return_value=_SOFT_OK,
        ),
        patch(
            "curriculum_agent.stages.plo_synthesis.PLORepository.bulk_insert",
            new_callable=AsyncMock,
        ),
    ):
        result = await run(state)

    for plo_dict in result["plos"]:
        assert plo_dict["source_cluster_ids"], (
            f"PLO {plo_dict['plo_id']} has empty source_cluster_ids"
        )


@pytest.mark.anyio
async def test_stage_3_smart_validator_called(state: dict) -> None:
    soft_judge_mock = AsyncMock(return_value=_SOFT_OK)
    with (
        patch(
            "curriculum_agent.stages.plo_synthesis.complete_heavy",
            new_callable=AsyncMock,
            return_value=_SAMPLE_DRAFTS,
        ),
        patch("curriculum_agent.stages.plo_synthesis.complete_light", soft_judge_mock),
        patch(
            "curriculum_agent.stages.plo_synthesis.PLORepository.bulk_insert",
            new_callable=AsyncMock,
        ),
    ):
        result = await run(state)

    assert soft_judge_mock.call_count >= len(_SAMPLE_DRAFTS.plos), (
        "soft judge should be called at least once per PLO"
    )
    # Verify the judge result was consumed by checking soft_flags and escalation
    for plo_dict in result["plos"]:
        assert plo_dict["soft_flags"] == [], (
            f"PLO {plo_dict['plo_id']} should have no soft flags when judge passes"
        )
        assert plo_dict["smart_escalated"] is False, (
            f"PLO {plo_dict['plo_id']} should not be escalated when hard checks pass"
        )
