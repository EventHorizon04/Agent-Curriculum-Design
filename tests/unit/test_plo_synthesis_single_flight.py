"""Guard: refuse a second concurrent PLO synthesis run for the same program.

The bug this pins: `POST /programs/{id}/plos/run` calls `plo_synthesis.run`,
which takes minutes (LLM calls) and then does a delete-by-program followed by a
bulk-insert. Nothing stopped a second run for the same program from starting
while the first was still in flight — the two requests overlapped, both
deleted and inserted, and the PLO set the trace panel read from no longer
matched what the triggering request's own HTTP response described (a card said
"2 needs", its trace showed 1). The fix is a per-process single-flight guard in
the stage itself (`ps.run`), so both entry points that call it — the REST route
and the LangGraph path — are covered without either one having to know about
the other.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import plos as plos_route
from curriculum_agent.graph import AgentState
from curriculum_agent.models import BloomLevel, KSECCategory, Need, ProgramMetadata
from curriculum_agent.stages import plo_synthesis as ps
from tests.support.smart_agent import set_soft_judge

client = TestClient(app)

_META = ProgramMetadata(
    program_id="cs-test",
    name_th="วิทยาการคอมพิวเตอร์",
    name_en="Computer Science",
    field="วิทยาการคอมพิวเตอร์",
    degree_level="bachelor",
    duration_years=4,
    faculty="คณะวิทยาศาสตร์",
    university="มหาวิทยาลัยทดสอบ",
)


def _need(need_id: str, program_id: str = "cs-test") -> Need:
    return Need(
        need_id=need_id,
        program_id=program_id,
        statement_th=f"ต้องการบัณฑิตที่ทำงานด้าน {need_id} ได้ตามมาตรฐานอุตสาหกรรม",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.CREATE,
        member_skill_ids=[f"S-{need_id}"],
        source_evidence_ids=[f"E-{need_id}"],
        freq=1,
        demand_score=0.8,
    )


def _draft(need_id: str) -> ps._PLODraft:
    return ps._PLODraft(
        statement_th=f"ออกแบบระบบสารสนเทศสำหรับงาน {need_id} ตามมาตรฐานอุตสาหกรรมได้",
        bloom_level=BloomLevel.CREATE,
        action_verb_th="ออกแบบ",
        source_need_ids=[need_id],
        rationale_th=f"ทักษะที่ตลาดต้องการสำหรับ {need_id}",
    )


def _state(program_id: str, needs: list[Need]) -> AgentState:
    return {
        "program_id": program_id,
        "metadata": _META.model_dump(mode="json") | {"program_id": program_id},
        "needs": [n.model_dump(mode="json") for n in needs],
    }


def _patch_repos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ps.PLORepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(ps.PLORepository, "bulk_insert", AsyncMock())


@pytest.fixture(autouse=True)
def _clear_in_flight() -> None:
    """Every test starts and ends with an empty guard set. A test that raises
    partway through this module must not strand a program id for the next
    test — `run`'s own `finally` is what this pins, but clearing here as well
    keeps one test's failure from poisoning another's."""
    ps._SYNTHESIS_IN_FLIGHT.clear()
    yield
    ps._SYNTHESIS_IN_FLIGHT.clear()


async def test_a_second_run_for_the_same_program_while_the_first_is_in_flight_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core guarantee. The second `run` must raise before the first one
    finishes, not after — it is suspended inside the first run's draft call
    when the second one is attempted."""
    _patch_repos(monkeypatch)
    set_soft_judge(monkeypatch)

    entered = asyncio.Event()
    release = asyncio.Event()

    async def hangs_mid_draft(model, messages, **kw):  # noqa: ANN001, ANN003
        entered.set()
        await release.wait()
        return ps._SingleDraftResponse(plo=_draft("N1"))

    monkeypatch.setattr(ps, "complete_plo_synthesis", hangs_mid_draft)

    first = asyncio.create_task(ps.run(_state("cs-test", [_need("N1")])))
    await entered.wait()

    with pytest.raises(ps.SynthesisAlreadyRunning, match="cs-test"):
        await ps.run(_state("cs-test", [_need("N1")]))

    release.set()
    result = await first
    assert len(result["plos"]) == 1


async def test_a_run_for_a_different_program_at_the_same_time_is_not_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard is keyed by program id, not a global lock — two designers
    working on two different programs must not block each other."""
    _patch_repos(monkeypatch)
    set_soft_judge(monkeypatch)

    entered = asyncio.Event()
    release = asyncio.Event()

    async def hangs_mid_draft(model, messages, **kw):  # noqa: ANN001, ANN003
        entered.set()
        await release.wait()
        return ps._SingleDraftResponse(plo=_draft("N1"))

    monkeypatch.setattr(ps, "complete_plo_synthesis", hangs_mid_draft)

    first = asyncio.create_task(ps.run(_state("program-a", [_need("N1", "program-a")])))
    await entered.wait()

    # No LLM hang for the second program's draft — it should run to completion.
    monkeypatch.setattr(
        ps,
        "complete_plo_synthesis",
        AsyncMock(return_value=ps._SingleDraftResponse(plo=_draft("N1"))),
    )
    second = await ps.run(_state("program-b", [_need("N1", "program-b")]))
    assert len(second["plos"]) == 1

    release.set()
    first_result = await first
    assert len(first_result["plos"]) == 1


async def test_the_slot_is_freed_after_a_run_that_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run that fails outright (here: need_combination produced an empty
    list) must still free its slot in `finally`, so the same program can be
    retried immediately rather than being locked out by its own failure."""
    failing_state: AgentState = {
        "program_id": "cs-test",
        "needs": [],
        "metadata": _META.model_dump(mode="json"),
    }
    with pytest.raises(ValueError, match="need_combination"):
        await ps.run(failing_state)

    assert "cs-test" not in ps._SYNTHESIS_IN_FLIGHT

    _patch_repos(monkeypatch)
    set_soft_judge(monkeypatch)
    monkeypatch.setattr(
        ps,
        "complete_plo_synthesis",
        AsyncMock(return_value=ps._SingleDraftResponse(plo=_draft("N1"))),
    )

    result = await ps.run(_state("cs-test", [_need("N1")]))
    assert len(result["plos"]) == 1


def test_the_route_answers_409_with_the_thai_detail_when_the_stage_is_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`POST /programs/{id}/plos/run` must translate the stage's refusal into a
    409 the frontend's existing `response.data.detail` handling already shows —
    no frontend change needed."""
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_META))
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need("N1")])
    )

    async def busy(state: AgentState) -> AgentState:
        raise ps.SynthesisAlreadyRunning(
            "กำลังสังเคราะห์ PLO ของโปรแกรม 'cs-test' อยู่ — รอให้รอบเดิมเสร็จก่อน"
        )

    monkeypatch.setattr(ps, "run", busy)

    response = client.post("/programs/cs-test/plos/run")

    assert response.status_code == 409
    assert "กำลังสังเคราะห์ PLO" in response.json()["detail"]
    assert "cs-test" in response.json()["detail"]
