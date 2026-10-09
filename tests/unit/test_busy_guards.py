"""A running job or graph session blocks the four synchronous writers.

`POST /sessions/`, `POST /sessions/{id}/approve`, `POST /plos/from-needs` and
`POST /programs/{id}/copy` write a program's tables without going through
`start_job`, so each refuses with 409 while `program_busy` says the program has
an active writer. Three of them also hold `program_lock` around the check and
their short write, so a job cannot start between the two. The merge route cannot
hold it across its LLM call, so it registers with `jobs.sync_writer` instead: the
registration is what `program_busy` reports to everyone else while the call runs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import NamedTuple
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from curriculum_agent.api import jobs
from curriculum_agent.api.main import app
from curriculum_agent.api.routes import plos as plos_route
from curriculum_agent.api.routes import programs as programs_route
from curriculum_agent.api.routes import sessions as sessions_route
from curriculum_agent.models import (
    PLO,
    BloomLevel,
    JobInfo,
    KSECCategory,
    Need,
    ProgramMetadata,
    SessionInfo,
)
from tests.support.jobs import InMemoryJobs

client = TestClient(app)

_NOW = datetime(2026, 10, 8, 3, 0, 0)
_PROGRAM = ProgramMetadata(
    program_id="p",
    field="การท่องเที่ยว",
    degree_level="bachelor",
    duration_years=4,
    faculty="คณะ",
    university="มหาวิทยาลัย",
)
_COPY = _PROGRAM.model_copy(update={"program_id": "p-run-1", "copied_from": "p"})
_SUSPENDED = SessionInfo(
    session_id="s1",
    program_id="p",
    thread_id="p:s1",
    status="suspended",
    current_stage="skill_extraction",
    suspended_message="Review",
    created_at=_NOW,
    updated_at=_NOW,
)


def _running_job() -> JobInfo:
    return JobInfo(
        job_id="j1", program_id="p", kind="plo_synthesis", status="running", created_at=_NOW
    )


def _need(need_id: str) -> Need:
    return Need(
        need_id=need_id,
        program_id="p",
        statement_th=f"ต้องการบัณฑิตที่ทำงาน {need_id} ในสถานประกอบการจริงได้",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=[f"S-{need_id}"],
        source_evidence_ids=[f"E-{need_id}"],
        freq=1,
        demand_score=0.7,
        in_field_skill_count=1,
        graduate_capability_skill_count=1,
    )


@pytest.fixture(params=["job", "session"])
def busy_program(
    request: pytest.FixtureRequest, jobs_store: InMemoryJobs, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Program "p" made busy in each of the two ways `program_busy` knows."""
    if request.param == "job":
        jobs_store.rows["j1"] = _running_job()
    else:
        monkeypatch.setattr(jobs, "_running_session", AsyncMock(return_value=True))
    return str(request.param)


# ---------- per-route setups ----------


@pytest.fixture
def session_repo(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """The repositories `create_session` and `approve_session` reach, with the
    graph's own run stubbed out so no background task touches a real graph."""
    repo = MagicMock()
    repo.get = AsyncMock(return_value=_SUSPENDED)
    repo.create = AsyncMock()
    repo.set_status = AsyncMock()
    program_repo = MagicMock(get=AsyncMock(return_value=_PROGRAM))
    evidence_repo = MagicMock(list_by_program=AsyncMock(return_value=[object()]))
    monkeypatch.setattr(sessions_route, "SessionRepository", lambda: repo)
    monkeypatch.setattr(sessions_route, "ProgramRepository", lambda: program_repo)
    monkeypatch.setattr(sessions_route, "EvidenceRepository", lambda: evidence_repo)
    monkeypatch.setattr(sessions_route, "_run_graph", AsyncMock())
    monkeypatch.setattr(app.state, "graph", MagicMock(), raising=False)
    return repo


@pytest.fixture
def copy_program_mock(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    async def exists(self: object, program_id: str) -> bool:
        return program_id == "p"

    copy = AsyncMock(return_value=True)
    monkeypatch.setattr(programs_route.ProgramRepository, "exists", exists)
    monkeypatch.setattr(programs_route.ProgramRepository, "get", AsyncMock(return_value=_COPY))
    monkeypatch.setattr(programs_route, "copy_program", copy)
    monkeypatch.setattr(app.state, "graph", MagicMock(aupdate_state=AsyncMock()), raising=False)
    return copy


@pytest.fixture
def merge_synthesis(monkeypatch: pytest.MonkeyPatch, valid_plo: PLO) -> AsyncMock:
    """Everything `POST /plos/from-needs` reaches; hands back the synthesis call,
    which is the LLM call the guard has to come before."""
    synthesize = AsyncMock(return_value=valid_plo.model_copy(update={"program_id": "p"}))
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_PROGRAM))
    monkeypatch.setattr(
        plos_route.NeedRepository,
        "list_by_program",
        AsyncMock(return_value=[_need("N1"), _need("N2")]),
    )
    monkeypatch.setattr(plos_route.PLORepository, "list_by_program", AsyncMock(return_value=[]))
    monkeypatch.setattr(plos_route.PLORepository, "replace", AsyncMock(return_value=0))
    monkeypatch.setattr("curriculum_agent.stages.plo_synthesis.synthesize_from_needs", synthesize)
    return synthesize


# ---------- the 409 ----------


def test_starting_a_session_is_refused_while_the_program_is_busy(
    busy_program: str, session_repo: MagicMock
) -> None:
    response = client.post("/programs/p/sessions/")
    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)
    session_repo.create.assert_not_awaited()


def test_approving_a_session_is_refused_while_the_program_is_busy(
    busy_program: str, session_repo: MagicMock
) -> None:
    """The session being approved is itself suspended, so it is not the thing
    that makes the program busy."""
    response = client.post("/programs/p/sessions/s1/approve")
    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)
    session_repo.set_status.assert_not_awaited()


def test_a_merge_is_refused_before_any_llm_call_while_the_program_is_busy(
    busy_program: str, merge_synthesis: AsyncMock
) -> None:
    response = client.post("/programs/p/plos/from-needs", json={"need_ids": ["N1", "N2"]})
    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)
    merge_synthesis.assert_not_awaited()


def test_a_copy_is_refused_while_the_program_is_busy(
    busy_program: str, copy_program_mock: AsyncMock
) -> None:
    response = client.post("/programs/p/copy")
    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)
    copy_program_mock.assert_not_awaited()


# ---------- nothing running: as before ----------


def test_a_session_starts_when_nothing_runs(session_repo: MagicMock) -> None:
    response = client.post("/programs/p/sessions/")
    assert response.status_code == 200
    session_repo.create.assert_awaited_once()


def test_a_session_is_approved_when_nothing_runs(session_repo: MagicMock) -> None:
    response = client.post("/programs/p/sessions/s1/approve")
    assert response.status_code == 200
    session_repo.set_status.assert_awaited_once_with("s1", "running")


def test_a_merge_runs_when_nothing_runs(merge_synthesis: AsyncMock) -> None:
    response = client.post("/programs/p/plos/from-needs", json={"need_ids": ["N1", "N2"]})
    assert response.status_code == 200, response.text
    merge_synthesis.assert_awaited_once()


def test_a_copy_runs_when_nothing_runs(copy_program_mock: AsyncMock) -> None:
    response = client.post("/programs/p/copy")
    assert response.status_code == 200
    copy_program_mock.assert_awaited_once()


# ---------- the lock ----------
#
# `start_job` holds `program_lock` around its busy check and its row insert. A
# writer that checked without the lock could pass the check, lose the race to a
# job's insert, and then write under a running job. These drive the route
# coroutines directly on the test's own loop, so the real lock — not a stand-in —
# is what holds them back.


class Writer(NamedTuple):
    call: Callable[[], Awaitable[object]]
    write: AsyncMock


@pytest.fixture(params=["create_session", "approve_session", "copy_program"])
def writer(
    request: pytest.FixtureRequest, session_repo: MagicMock, copy_program_mock: AsyncMock
) -> Writer:
    fake_request = MagicMock()
    fake_request.app.state.graph.aupdate_state = AsyncMock()
    if request.param == "create_session":
        return Writer(
            lambda: sessions_route.create_session("p", fake_request, BackgroundTasks()),
            session_repo.create,
        )
    if request.param == "approve_session":
        return Writer(
            lambda: sessions_route.approve_session("p", "s1", fake_request, BackgroundTasks()),
            session_repo.set_status,
        )
    return Writer(lambda: programs_route.copy_program_route("p", fake_request), copy_program_mock)


async def _let_it_run() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


async def test_a_writer_waits_for_the_program_lock_before_it_writes(writer: Writer) -> None:
    async with jobs.program_lock("p"):
        task = asyncio.ensure_future(writer.call())
        await _let_it_run()
        assert not task.done()
        writer.write.assert_not_awaited()
    await task
    writer.write.assert_awaited()


async def test_a_writer_checks_busy_after_it_gets_the_lock(
    writer: Writer, jobs_store: InMemoryJobs
) -> None:
    """A job that started while the writer queued for the lock still stops it:
    the check belongs inside the lock, not before it."""
    async with jobs.program_lock("p"):
        task = asyncio.ensure_future(writer.call())
        await _let_it_run()
        jobs_store.rows["j1"] = _running_job()
    with pytest.raises(HTTPException) as refused:
        await task
    assert refused.value.status_code == 409
    writer.write.assert_not_awaited()


# ---------- the merge registers as a writer ----------
#
# `POST /plos/from-needs` checks the program once and then spends minutes in an LLM
# call. A synthesis job that started and finished in that window would leave the
# merge replacing ids that now name different outcomes. The merge therefore
# registers for the length of the call, without holding `program_lock`.


@pytest.fixture
def merge_in_flight(merge_synthesis: AsyncMock) -> tuple[asyncio.Event, asyncio.Event]:
    """Makes the merge's LLM call wait for the test. Returns (reached, release)."""
    reached, release = asyncio.Event(), asyncio.Event()
    result = merge_synthesis.return_value

    async def wait_for_the_test(*args: object, **kwargs: object) -> PLO:
        reached.set()
        await release.wait()
        return result  # type: ignore[no-any-return]

    merge_synthesis.side_effect = wait_for_the_test
    return reached, release


def _merge_call() -> Awaitable[PLO]:
    body = plos_route.MergeNeedsRequest(need_ids=["N1", "N2"])
    return plos_route.create_plo_from_needs("p", body)


async def test_every_other_writer_is_refused_while_a_merge_is_in_flight(
    merge_in_flight: tuple[asyncio.Event, asyncio.Event],
    session_repo: MagicMock,
    copy_program_mock: AsyncMock,
    jobs_store: InMemoryJobs,
) -> None:
    reached, release = merge_in_flight
    fake_request = MagicMock()
    fake_request.app.state.graph.aupdate_state = AsyncMock()
    merge = asyncio.ensure_future(_merge_call())
    await asyncio.wait_for(reached.wait(), timeout=2)

    with pytest.raises(jobs.JobConflict) as job_refused:
        await jobs.start_job("p", "plo_synthesis", {}, AsyncMock())
    assert "Need" in job_refused.value.detail_th
    assert jobs_store.rows == {}

    for refused_call in (
        _merge_call(),
        programs_route.copy_program_route("p", fake_request),
        sessions_route.create_session("p", fake_request, BackgroundTasks()),
    ):
        with pytest.raises(HTTPException) as refused:
            await refused_call
        assert refused.value.status_code == 409
        assert "Need" in str(refused.value.detail)
    copy_program_mock.assert_not_awaited()
    session_repo.create.assert_not_awaited()

    release.set()
    await merge
    # once it is over the program is free again
    assert await jobs.program_busy("p") is None


async def test_the_merge_does_not_make_another_program_busy(
    merge_in_flight: tuple[asyncio.Event, asyncio.Event],
) -> None:
    reached, release = merge_in_flight
    merge = asyncio.ensure_future(_merge_call())
    await asyncio.wait_for(reached.wait(), timeout=2)
    assert await jobs.program_busy("q") is None
    release.set()
    await merge


async def test_the_merge_registration_is_removed_when_the_merge_fails(
    merge_synthesis: AsyncMock,
) -> None:
    merge_synthesis.return_value = None  # synthesis gave up: the route answers 502
    with pytest.raises(HTTPException) as failed:
        await _merge_call()
    assert failed.value.status_code == 502
    assert await jobs.program_busy("p") is None
    assert jobs._SYNC_WRITERS == {}


async def test_the_merge_registration_is_removed_when_the_merge_is_refused_early(
    merge_synthesis: AsyncMock,
) -> None:
    with pytest.raises(HTTPException) as refused:
        await plos_route.create_plo_from_needs(
            "p", plos_route.MergeNeedsRequest(need_ids=["N1", "NOPE"])
        )
    assert refused.value.status_code == 422
    assert jobs._SYNC_WRITERS == {}
    merge_synthesis.assert_not_awaited()
