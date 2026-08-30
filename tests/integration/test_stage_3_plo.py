from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from curriculum_agent.models import (
    BloomLevel,
    Need,
    ProgramMetadata,
)
from curriculum_agent.stages.plo_synthesis import (
    _PLODraft,
    _SingleDraftResponse,
    _SmartSoftJudge,
    run,
)

_SOFT_OK = _SmartSoftJudge(specific_object_ok=True, achievable_ok=True, relevant_alignment_ok=True)


def _draft_for(need: Need) -> _PLODraft:
    return _PLODraft(
        plo_id=f"PLO-{need.need_id}",
        statement_th=f"ออกแบบและพัฒนาระบบสารสนเทศสำหรับงาน {need.need_id} ได้อย่างมีประสิทธิภาพ",
        bloom_level=BloomLevel.CREATE,
        action_verb_th="ออกแบบ",
        source_need_ids=[need.need_id],
        rationale_th=f"ทักษะที่นายจ้างต้องการลำดับที่ {need.need_id}",
    )


@pytest.fixture
def needs() -> list[Need]:
    return [
        Need(
            need_id=f"N{i}",
            program_id="cs-test",
            statement_th=f"สามารถทำงานสารสนเทศลำดับที่ {i} ได้",
            ksec_category="S",
            bloom_level=BloomLevel.CREATE,
            member_skill_ids=[f"S{i}"],
            source_evidence_ids=[f"E{i}"],
            freq=2,
            demand_score=0.8,
        )
        for i in range(1, 7)
    ]


@pytest.fixture
def state(program_metadata: ProgramMetadata, needs: list[Need]) -> dict:
    return {
        "program_id": program_metadata.program_id,
        "metadata": program_metadata.model_dump(mode="json"),
        "needs": [n.model_dump(mode="json") for n in needs],
    }


def _patched(needs: list[Need]):
    drafts = {n.need_id: _draft_for(n) for n in needs}

    async def fake_synthesis(model, messages, **kw):  # noqa: ANN001, ANN003
        body = messages[-1]["content"]
        nid = next(n.need_id for n in needs if n.need_id in body)
        return _SingleDraftResponse(plo=drafts[nid])

    return (
        patch(
            "curriculum_agent.stages.plo_synthesis.complete_synthesis",
            new=fake_synthesis,
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
        # run() replaces the set rather than upserting into it, so the delete
        # needs stubbing too or the stage opens a real database connection.
        patch(
            "curriculum_agent.stages.plo_synthesis.PLORepository.delete_by_program",
            new_callable=AsyncMock,
            return_value=0,
        ),
    )


@pytest.mark.anyio
async def test_stage_4_produces_one_plo_per_need(state: dict, needs: list[Need]) -> None:
    p1, p2, p3, p4 = _patched(needs)
    with p1, p2, p3, p4:
        result = await run(state)

    plos = result["plos"]
    assert len(plos) == len(needs), f"Expected one PLO per Need ({len(needs)}), got {len(plos)}"
    assert sorted(p["source_need_ids"][0] for p in plos) == sorted(n.need_id for n in needs)


@pytest.mark.anyio
async def test_stage_4_no_forbidden_words(state: dict, needs: list[Need]) -> None:
    p1, p2, p3, p4 = _patched(needs)
    with p1, p2, p3, p4:
        result = await run(state)

    from curriculum_agent.models import FORBIDDEN_WORDS_TH

    for plo_dict in result["plos"]:
        stmt = plo_dict["statement_th"]
        for word in FORBIDDEN_WORDS_TH:
            assert word not in stmt, f"Forbidden word '{word}' found in: {stmt}"


@pytest.mark.anyio
async def test_stage_4_source_need_ids_non_empty(state: dict, needs: list[Need]) -> None:
    p1, p2, p3, p4 = _patched(needs)
    with p1, p2, p3, p4:
        result = await run(state)

    for plo_dict in result["plos"]:
        assert plo_dict["source_need_ids"], f"PLO {plo_dict['plo_id']} has empty source_need_ids"
        assert plo_dict["source_evidence_ids"], (
            f"PLO {plo_dict['plo_id']} has empty source_evidence_ids"
        )


@pytest.mark.anyio
async def test_stage_4_smart_validator_called_once_per_need(state: dict, needs: list[Need]) -> None:
    p1, _, p3, p4 = _patched(needs)
    soft_judge_mock = AsyncMock(return_value=_SOFT_OK)
    with (
        p1,
        patch("curriculum_agent.stages.plo_synthesis.complete_light", soft_judge_mock),
        p3,
        p4,
    ):
        result = await run(state)

    assert soft_judge_mock.call_count >= len(needs), (
        "soft judge should be called at least once per Need"
    )
    for plo_dict in result["plos"]:
        assert plo_dict["soft_flags"] == [], (
            f"PLO {plo_dict['plo_id']} should have no soft flags when judge passes"
        )
        assert plo_dict["smart_escalated"] is False, (
            f"PLO {plo_dict['plo_id']} should not be escalated when hard checks pass"
        )
