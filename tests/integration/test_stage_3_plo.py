from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Any
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
    run,
)
from tests.support.smart_agent import scripted_agent


def _draft_for(need: Need) -> _PLODraft:
    return _PLODraft(
        # No plo_id: the code owns it, and _PLODraft has had no such field since
        # the id scheme changed. Pydantic was ignoring it.
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


@dataclass
class _Stubs:
    """The stubs a test may want to assert on, named rather than positional."""

    validator: Any
    bulk_insert: AsyncMock
    delete_by_program: AsyncMock


@contextmanager
def _patched(needs: list[Need]) -> Iterator[_Stubs]:
    """Every provider and repository call the stage makes, stubbed.

    A context manager over an ExitStack rather than a tuple every caller
    unpacks positionally: adding a fifth stub used to mean editing all four
    call sites, and one of them unpacked `p1, _, p3, p4` just to swap the
    second element for a mock it could count.
    """
    drafts = {n.need_id: _draft_for(n) for n in needs}

    async def fake_synthesis(model, messages, **kw):  # noqa: ANN001, ANN003
        body = messages[-1]["content"]
        nid = next(n.need_id for n in needs if n.need_id in body)
        return _SingleDraftResponse(plo=drafts[nid])

    validator = scripted_agent()
    bulk_insert = AsyncMock()
    # run() replaces the set rather than upserting into it, so the delete needs
    # stubbing too or the stage opens a real database connection.
    delete_by_program = AsyncMock(return_value=0)

    with ExitStack() as stack:
        for target, new in (
            ("complete_synthesis", fake_synthesis),
            ("run_smart_agent", validator),
            ("PLORepository.bulk_insert", bulk_insert),
            ("PLORepository.delete_by_program", delete_by_program),
        ):
            stack.enter_context(patch(f"curriculum_agent.stages.plo_synthesis.{target}", new))
        yield _Stubs(
            validator=validator, bulk_insert=bulk_insert, delete_by_program=delete_by_program
        )


@pytest.mark.anyio
async def test_stage_4_produces_one_plo_per_need(state: dict, needs: list[Need]) -> None:
    with _patched(needs):
        result = await run(state)

    plos = result["plos"]
    assert len(plos) == len(needs), f"Expected one PLO per Need ({len(needs)}), got {len(plos)}"
    assert sorted(p["source_need_ids"][0] for p in plos) == sorted(n.need_id for n in needs)


@pytest.mark.anyio
async def test_stage_4_no_forbidden_words(state: dict, needs: list[Need]) -> None:
    with _patched(needs):
        result = await run(state)

    # The same scan the gate and the model validator use — asserting against a
    # bare substring loop here would hold the stage to a stricter rule than the
    # code it is testing, and "รักษา" would fail this test while passing the gate.
    from curriculum_agent.smart_vocabulary import forbidden_words_in

    for plo_dict in result["plos"]:
        stmt = plo_dict["statement_th"]
        found = forbidden_words_in(stmt)
        assert not found, f"Forbidden word '{found[0] if found else ''}' found in: {stmt}"


@pytest.mark.anyio
async def test_stage_4_source_need_ids_non_empty(state: dict, needs: list[Need]) -> None:
    with _patched(needs):
        result = await run(state)

    for plo_dict in result["plos"]:
        assert plo_dict["source_need_ids"], f"PLO {plo_dict['plo_id']} has empty source_need_ids"
        assert plo_dict["source_evidence_ids"], (
            f"PLO {plo_dict['plo_id']} has empty source_evidence_ids"
        )


@pytest.mark.anyio
async def test_stage_4_smart_validator_called_once_per_need(state: dict, needs: list[Need]) -> None:
    with _patched(needs) as stubs:
        result = await run(state)

    # Exactly once per Need, not ">=": the two-phase design finally makes that
    # exact. The old ">=" hid the gate's own retry calls.
    assert len(stubs.validator.calls) == len(needs), (
        "the validator should run exactly once per Need"
    )
    for plo_dict in result["plos"]:
        assert plo_dict["soft_flags"] == [], (
            f"PLO {plo_dict['plo_id']} should have no soft flags when judge passes"
        )
        assert plo_dict["smart_escalated"] is False, (
            f"PLO {plo_dict['plo_id']} should not be escalated when hard checks pass"
        )
