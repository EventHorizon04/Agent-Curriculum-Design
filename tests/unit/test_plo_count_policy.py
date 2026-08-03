from __future__ import annotations

from unittest.mock import AsyncMock, patch

from curriculum_agent.models import BloomLevel, KSECCategory, Need, ProgramMetadata
from curriculum_agent.stages import plo_synthesis as ps
from curriculum_agent.stages.need_grouping import MIN_NEEDS


def test_policy_bound_comes_from_need_grouping():
    """The minimum-count policy now lives in need_grouping, not as a local constant here."""
    assert ps.MIN_NEEDS == MIN_NEEDS == 6


def _need(nid: str) -> Need:
    return Need(
        need_id=nid,
        program_id="cs-test",
        statement_th=f"สามารถทำงาน {nid} ตามที่ตลาดต้องการ",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=0.7,
    )


def _draft(nid: str) -> ps._PLODraft:
    return ps._PLODraft(
        plo_id=f"PLO-{nid}",
        statement_th=f"วิเคราะห์งาน {nid} เพื่อเสนอแนวทางแก้ปัญหาได้",
        bloom_level=BloomLevel.ANALYZE,
        is_subject_specific=True,
        action_verb_th="วิเคราะห์",
        source_need_ids=[nid],
        source_evidence_ids=[f"E-{nid}"],
        rationale_th="ตรงกับความต้องการของตลาด",
    )


def _patch_llm(needs: list[Need]):
    drafts = {n.need_id: _draft(n.need_id) for n in needs}

    async def fake_heavy(model, messages, **kw):  # noqa: ANN001, ANN003
        body = messages[-1]["content"]
        nid = next(n.need_id for n in needs if n.need_id in body)
        return ps._SingleDraftResponse(plo=drafts[nid])

    async def fake_light(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SmartSoftJudge(
            specific_object_ok=True, achievable_ok=True, relevant_alignment_ok=True
        )

    return (
        patch.object(ps, "complete_heavy", fake_heavy),
        patch.object(ps, "complete_light", fake_light),
        patch.object(ps.PLORepository, "bulk_insert", AsyncMock()),
    )


async def test_run_warns_when_core_plo_count_is_below_policy(
    program_metadata: ProgramMetadata,
):
    """Fewer than MIN_NEEDS core PLOs must log a policy warning naming the count."""
    needs = [_need(f"N{i}") for i in range(1, 3)]  # 2 < MIN_NEEDS(6)
    p1, p2, p3 = _patch_llm(needs)

    with p1, p2, p3, patch.object(ps, "logger") as mock_logger:
        state = await ps.run(
            {
                "program_id": "cs-test",
                "metadata": program_metadata.model_dump(mode="json"),
                "needs": [n.model_dump(mode="json") for n in needs],
            }
        )

    assert len(state["plos"]) == 2
    policy_warnings = [
        call.args[0] for call in mock_logger.warning.call_args_list if "core PLOs" in call.args[0]
    ]
    assert len(policy_warnings) == 1
    assert "2 core PLOs" in policy_warnings[0]
    assert "6" in policy_warnings[0]


async def test_run_does_not_warn_when_core_plo_count_is_within_policy(
    program_metadata: ProgramMetadata,
):
    needs = [_need(f"N{i}") for i in range(1, 7)]  # 6 == MIN_NEEDS, within policy
    p1, p2, p3 = _patch_llm(needs)

    with p1, p2, p3, patch.object(ps, "logger") as mock_logger:
        state = await ps.run(
            {
                "program_id": "cs-test",
                "metadata": program_metadata.model_dump(mode="json"),
                "needs": [n.model_dump(mode="json") for n in needs],
            }
        )

    assert len(state["plos"]) == 6
    policy_warnings = [
        call.args[0] for call in mock_logger.warning.call_args_list if "core PLOs" in call.args[0]
    ]
    assert policy_warnings == []


async def test_run_does_not_warn_above_the_old_ten_cap(
    program_metadata: ProgramMetadata,
):
    """No upper cap: 12 core PLOs (above the removed MAX_NEEDS=10) must not warn."""
    needs = [_need(f"N{i}") for i in range(1, 13)]
    p1, p2, p3 = _patch_llm(needs)

    with p1, p2, p3, patch.object(ps, "logger") as mock_logger:
        state = await ps.run(
            {
                "program_id": "cs-test",
                "metadata": program_metadata.model_dump(mode="json"),
                "needs": [n.model_dump(mode="json") for n in needs],
            }
        )

    assert len(state["plos"]) == 12
    policy_warnings = [
        call.args[0] for call in mock_logger.warning.call_args_list if "core PLOs" in call.args[0]
    ]
    assert policy_warnings == []
