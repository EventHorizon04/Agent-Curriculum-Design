from __future__ import annotations

from unittest.mock import AsyncMock, patch

from curriculum_agent.models import (
    BloomLevel,
    KSECCategory,
    Need,
    ProgramMetadata,
    StakeholderType,
)
from curriculum_agent.stages import plo_synthesis as ps
from curriculum_agent.stages.need_grouping import MIN_NEEDS
from tests.support.smart_agent import patch_soft_judge


def test_policy_bound_comes_from_need_grouping():
    """The minimum-count policy now lives in need_grouping, not as a local constant here."""
    assert ps.MIN_NEEDS == MIN_NEEDS == 6


def _need(nid: str, *, demand: float = 0.7, optional: bool = False) -> Need:
    return Need(
        need_id=nid,
        program_id="cs-test",
        statement_th=f"ตลาดแรงงานต้องการผู้ที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=demand,
        is_optional=optional,
    )


def _draft(nid: str) -> ps._PLODraft:
    return ps._PLODraft(
        plo_id=f"PLO-{nid}",
        statement_th=f"วิเคราะห์งาน {nid} เพื่อเสนอแนวทางแก้ปัญหาได้",
        bloom_level=BloomLevel.ANALYZE,
        action_verb_th="วิเคราะห์",
        source_need_ids=[nid],
        rationale_th="ตรงกับความต้องการของตลาด",
    )


def _patch_llm(needs: list[Need]):
    drafts = {n.need_id: _draft(n.need_id) for n in needs}

    async def fake_synthesis(model, messages, **kw):  # noqa: ANN001, ANN003
        # Match the whole "need_id: <id>" line, not the bare id: "N1" is a
        # substring of "N10", and a substring match would hand N10's prompt N1's
        # draft — silently, since only the count would still look right.
        body = messages[-1]["content"]
        nid = next(n.need_id for n in needs if f"need_id: {n.need_id}\n" in body)
        return ps._SingleDraftResponse(plo=drafts[nid])

    return (
        patch.object(ps, "complete_plo_synthesis", fake_synthesis),
        patch_soft_judge(),
        patch.object(ps.PLORepository, "delete_by_program", AsyncMock(return_value=0)),
        patch.object(ps.PLORepository, "bulk_insert", AsyncMock()),
    )


async def test_run_warns_when_core_plo_count_is_below_policy(
    program_metadata: ProgramMetadata,
):
    """Fewer than MIN_NEEDS core PLOs must log a policy warning naming the count."""
    needs = [_need(f"N{i}") for i in range(1, 3)]  # 2 < MIN_NEEDS(6)
    p1, p2, p3, p4 = _patch_llm(needs)

    with p1, p2, p3, p4, patch.object(ps, "logger") as mock_logger:
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
    p1, p2, p3, p4 = _patch_llm(needs)

    with p1, p2, p3, p4, patch.object(ps, "logger") as mock_logger:
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


async def test_the_ceiling_keeps_the_ten_highest_demand_core_needs(
    program_metadata: ProgramMetadata,
):
    """Project policy is 6-10 main PLOs, and the ceiling is applied by choosing
    which Needs to use rather than by merging them down to a quota.

    Twelve core Needs therefore yield ten PLOs, the two lowest-demand Needs are the
    ones left out, and every Need survives untouched in the stage's input.
    """
    needs = [_need(f"N{i}", demand=i / 100) for i in range(1, 13)]
    p1, p2, p3, p4 = _patch_llm(needs)

    with p1, p2, p3, p4:
        state = await ps.run(
            {
                "program_id": "cs-test",
                "metadata": program_metadata.model_dump(mode="json"),
                "needs": [n.model_dump(mode="json") for n in needs],
            }
        )

    assert len(state["plos"]) == ps.MAX_CORE_PLOS == 10
    used = {nid for p in state["plos"] for nid in p["source_need_ids"]}
    assert used == {f"N{i}" for i in range(3, 13)}  # N1 and N2 score lowest


async def test_the_ceiling_names_the_needs_it_left_out(
    program_metadata: ProgramMetadata,
):
    """A silent cut reads as "every Need became a PLO". The warning has to name the
    ids so a designer looking at 12 Needs and 10 PLOs can find the missing two."""
    needs = [_need(f"N{i}", demand=i / 100) for i in range(1, 13)]
    p1, p2, p3, p4 = _patch_llm(needs)

    with p1, p2, p3, p4, patch.object(ps, "logger") as mock_logger:
        await ps.run(
            {
                "program_id": "cs-test",
                "metadata": program_metadata.model_dump(mode="json"),
                "needs": [n.model_dump(mode="json") for n in needs],
            }
        )

    ceiling = [c.args[0] for c in mock_logger.warning.call_args_list if "ceiling" in c.args[0]]
    assert len(ceiling) == 1
    assert "N1" in ceiling[0] and "N2" in ceiling[0]


async def test_exactly_ten_core_needs_pass_without_a_ceiling_warning(
    program_metadata: ProgramMetadata,
):
    needs = [_need(f"N{i}", demand=i / 100) for i in range(1, 11)]
    p1, p2, p3, p4 = _patch_llm(needs)

    with p1, p2, p3, p4, patch.object(ps, "logger") as mock_logger:
        state = await ps.run(
            {
                "program_id": "cs-test",
                "metadata": program_metadata.model_dump(mode="json"),
                "needs": [n.model_dump(mode="json") for n in needs],
            }
        )

    assert len(state["plos"]) == 10
    assert [c.args[0] for c in mock_logger.warning.call_args_list if "ceiling" in c.args[0]] == []


async def test_optional_plos_are_outside_the_ceiling(
    program_metadata: ProgramMetadata,
):
    """Optional outcomes are exempt from the 6 floor, so they are exempt from the
    10 ceiling too — capping them would silently drop supplementary outcomes a
    designer deliberately kept."""
    needs = [_need(f"N{i}", demand=i / 100) for i in range(1, 7)]
    needs += [_need(f"O{i}", demand=i / 100, optional=True) for i in range(1, 13)]
    p1, p2, p3, p4 = _patch_llm(needs)

    with p1, p2, p3, p4:
        state = await ps.run(
            {
                "program_id": "cs-test",
                "metadata": program_metadata.model_dump(mode="json"),
                "needs": [n.model_dump(mode="json") for n in needs],
            }
        )

    optional = [p for p in state["plos"] if p["is_optional"]]
    assert len(optional) == 12
    assert len(state["plos"]) == 18


async def test_warns_when_no_plo_traces_to_the_institution(
    program_metadata: ProgramMetadata,
):
    """Institutional coverage is a property of the PLO set, not of each PLO, so it
    is checked once after synthesis rather than flagged nine times."""
    needs = [_need(f"N{i}") for i in range(1, 7)]  # none carry institutional_direction
    p1, p2, p3, p4 = _patch_llm(needs)

    with p1, p2, p3, p4, patch.object(ps, "logger") as mock_logger:
        await ps.run(
            {
                "program_id": "cs-test",
                "metadata": program_metadata.model_dump(mode="json"),
                "needs": [n.model_dump(mode="json") for n in needs],
            }
        )

    warnings = [c.args[0] for c in mock_logger.warning.call_args_list if "institution" in c.args[0]]
    assert len(warnings) == 1


async def test_does_not_warn_when_a_need_carries_institutional_direction(
    program_metadata: ProgramMetadata,
):
    needs = [_need(f"N{i}") for i in range(1, 7)]
    needs[0] = needs[0].model_copy(
        update={"source_stakeholder_types": [StakeholderType.INSTITUTIONAL_DIRECTION]}
    )
    p1, p2, p3, p4 = _patch_llm(needs)

    with p1, p2, p3, p4, patch.object(ps, "logger") as mock_logger:
        await ps.run(
            {
                "program_id": "cs-test",
                "metadata": program_metadata.model_dump(mode="json"),
                "needs": [n.model_dump(mode="json") for n in needs],
            }
        )

    warnings = [c.args[0] for c in mock_logger.warning.call_args_list if "institution" in c.args[0]]
    assert warnings == []
