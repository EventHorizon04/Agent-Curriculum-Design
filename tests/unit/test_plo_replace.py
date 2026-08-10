"""A synthesis re-run replaces the PLO set; it does not accumulate one.

skill_extraction and need_combination both delete their program's rows before
inserting, because their ids are fresh uuids per run. plo_synthesis only
upserted by plo_id, so a re-run that produced fewer PLOs than the last one left
the extras behind — pointing at Needs that need_combination had just deleted.
The UI showed such a PLO with "Needs (0)": the PLO existed, its evidence trail
resolved to nothing, and nothing said why.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from curriculum_agent.models import (
    BloomLevel,
    KSECCategory,
    Need,
    ProgramMetadata,
)
from curriculum_agent.stages import plo_synthesis as ps


def _need(nid: str, *, is_optional: bool = False) -> Need:
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
        is_optional=is_optional,
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


def _patch_llm(needs: list[Need], delete_mock: AsyncMock, insert_mock: AsyncMock):
    drafts = {n.need_id: _draft(n.need_id) for n in needs}

    async def fake_heavy(model, messages, **kw):  # noqa: ANN001, ANN003
        body = messages[-1]["content"]
        nid = next(n.need_id for n in needs if n.need_id in body)
        return ps._SingleDraftResponse(plo=drafts[nid])

    async def fake_light(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SmartSoftJudge()

    return (
        patch.object(ps, "complete_heavy", fake_heavy),
        patch.object(ps, "complete_light", fake_light),
        patch.object(ps.PLORepository, "delete_by_program", delete_mock),
        patch.object(ps.PLORepository, "bulk_insert", insert_mock),
    )


async def _run(needs: list[Need], metadata: ProgramMetadata) -> tuple[AsyncMock, AsyncMock]:
    delete_mock = AsyncMock(return_value=0)
    insert_mock = AsyncMock()
    p1, p2, p3, p4 = _patch_llm(needs, delete_mock, insert_mock)
    with p1, p2, p3, p4:
        await ps.run(
            {
                "program_id": "cs-test",
                "metadata": metadata.model_dump(mode="json"),
                "needs": [n.model_dump(mode="json") for n in needs],
            }
        )
    return delete_mock, insert_mock


async def test_run_clears_the_previous_set_before_inserting(
    program_metadata: ProgramMetadata,
) -> None:
    needs = [_need(f"N{i}") for i in range(1, 4)]

    delete_mock, insert_mock = await _run(needs, program_metadata)

    delete_mock.assert_awaited_once_with("cs-test")
    insert_mock.assert_awaited_once()


async def test_a_run_producing_only_optional_plos_still_clears_the_core_ones(
    program_metadata: ProgramMetadata,
) -> None:
    """The case that produced the bug: every skill classified `want`, so every
    Need came back optional and the run produced no core PLO at all. Without the
    delete, the previous run's PLO1 survived with its Need already gone."""
    needs = [_need(f"N{i}", is_optional=True) for i in range(1, 3)]

    delete_mock, insert_mock = await _run(needs, program_metadata)

    delete_mock.assert_awaited_once_with("cs-test")
    inserted = insert_mock.await_args.args[0]
    assert inserted, "optional Needs must still yield optional PLOs"
    assert all(p.is_optional for p in inserted)


async def test_nothing_is_deleted_when_synthesis_produces_nothing(
    program_metadata: ProgramMetadata,
) -> None:
    """Same guard skill_extraction and need_combination carry: a run that
    produces nothing must not destroy the last good set."""
    needs = [_need("N1")]

    async def failing_heavy(model, messages, **kw):  # noqa: ANN001, ANN003
        raise RuntimeError("provider down")

    delete_mock = AsyncMock(return_value=0)
    insert_mock = AsyncMock()
    with (
        patch.object(ps, "complete_heavy", failing_heavy),
        patch.object(ps, "complete_light", AsyncMock(return_value=ps._SmartSoftJudge())),
        patch.object(ps.PLORepository, "delete_by_program", delete_mock),
        patch.object(ps.PLORepository, "bulk_insert", insert_mock),
    ):
        await ps.run(
            {
                "program_id": "cs-test",
                "metadata": program_metadata.model_dump(mode="json"),
                "needs": [n.model_dump(mode="json") for n in needs],
            }
        )

    delete_mock.assert_not_awaited()
    insert_mock.assert_not_awaited()


async def test_trace_reports_needs_it_could_not_resolve() -> None:
    """Defence in depth for sets already in this state: the endpoint says which
    ids went missing instead of returning an empty list that reads as "this PLO
    was built from no Needs"."""
    from curriculum_agent.api.routes import plos as plos_route

    plo = ps.PLO(
        plo_id="PLO1",
        program_id="cs-test",
        statement_th="วิเคราะห์ระบบงานเพื่อเสนอแนวทางแก้ปัญหาได้",
        bloom_level=BloomLevel.ANALYZE,
        action_verb_th="วิเคราะห์",
        smart_check=ps.SMARTCheck(
            specific=True, measurable=True, achievable=True, relevant=True, timely=True
        ),
        source_need_ids=["gone-need-id"],
        source_evidence_ids=["E1"],
        rationale_th="เหตุผล",
    )

    with (
        patch.object(plos_route._repo, "list_by_program", AsyncMock(return_value=[plo])),
        patch.object(
            plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need("other")])
        ),
        patch.object(plos_route.EvidenceRepository, "list_by_program", AsyncMock(return_value=[])),
    ):
        trace = await plos_route.get_plo_trace("cs-test", "PLO1")

    assert trace.clusters == []
    assert trace.missing_need_ids == ["gone-need-id"]


def test_plo_repository_exposes_a_delete() -> None:
    from curriculum_agent.data.repositories import PLORepository

    assert hasattr(PLORepository, "delete_by_program")


@pytest.mark.parametrize("repo_name", ["SkillRepository", "NeedRepository", "PLORepository"])
def test_every_regenerated_entity_can_be_cleared(repo_name: str) -> None:
    """All three stages regenerate their rows wholesale; all three need the same
    delete, or the odd one out accumulates dangling references."""
    import curriculum_agent.data.repositories as repos

    assert hasattr(getattr(repos, repo_name), "delete_by_program")
