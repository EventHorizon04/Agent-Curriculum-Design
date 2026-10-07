"""api/jobs.py: start, run, record, refuse, sweep."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from curriculum_agent.api import jobs
from tests.support.jobs import InMemoryJobs, SpawnRecorder


class _Out(BaseModel):
    n: int


async def _ok() -> _Out:
    return _Out(n=3)


async def test_start_records_running_and_spawns(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    job = await jobs.start_job("p", "plo_report", {"x": 1}, _ok)
    assert job.status == "running"
    assert job.label_th == jobs.JOB_KIND_LABEL_TH["plo_report"]
    assert jobs_store.rows[job.job_id].params == {"x": 1}
    assert len(spawned.coros) == 1


async def test_success_records_the_result_body(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    job = await jobs.start_job("p", "plo_report", {}, _ok)
    await spawned.coros.pop(0)
    done = jobs_store.rows[job.job_id]
    assert done.status == "succeeded"
    assert done.result == {"n": 3}
    assert done.finished_at is not None


async def test_a_list_result_is_dumped_item_by_item(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    async def many() -> list[_Out]:
        return [_Out(n=1), _Out(n=2)]

    job = await jobs.start_job("p", "plo_synthesis", {}, many)
    await spawned.coros.pop(0)
    assert jobs_store.rows[job.job_id].result == [{"n": 1}, {"n": 2}]


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (HTTPException(status_code=422, detail="ยังไม่มี PLO"), "ยังไม่มี PLO"),
        (TimeoutError(), "หมดเวลา"),
        (ValueError("AgentState missing 'metadata'"), "AgentState missing 'metadata'"),
    ],
)
async def test_failure_records_a_readable_error(
    exc: Exception, expected: str, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    async def boom() -> _Out:
        raise exc

    job = await jobs.start_job("p", "plo_report", {}, boom)
    await spawned.coros.pop(0)
    done = jobs_store.rows[job.job_id]
    assert done.status == "failed"
    assert expected in (done.error_th or "")


@pytest.mark.parametrize("returned", [None, {"n": 3}])
async def test_a_result_that_cannot_be_dumped_fails_the_job_instead_of_escaping(
    returned: object, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    """A dump failure used to sit in the try's `else:` and escape: the job stayed
    `running` for ever and locked its program."""

    async def not_a_model() -> _Out:
        return returned  # type: ignore[return-value]

    job = await jobs.start_job("p", "plo_report", {}, not_a_model)
    await spawned.coros.pop(0)  # must not raise
    done = jobs_store.rows[job.job_id]
    assert done.status == "failed"
    assert done.error_th
    assert done.finished_at is not None
    # and the program is free again
    await jobs.start_job("p", "plo_report", {}, _ok)


async def test_a_running_job_refuses_a_second(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    await jobs.start_job("p", "plo_synthesis", {}, _ok)
    with pytest.raises(jobs.JobConflict) as info:
        await jobs.start_job("p", "plo_report", {}, _ok)
    assert jobs.JOB_KIND_LABEL_TH["plo_synthesis"] in info.value.detail_th


async def test_another_program_is_not_blocked(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    await jobs.start_job("p", "plo_synthesis", {}, _ok)
    assert (await jobs.start_job("q", "plo_synthesis", {}, _ok)).program_id == "q"


async def test_a_running_session_blocks_a_job(
    monkeypatch: pytest.MonkeyPatch, spawned: SpawnRecorder
) -> None:
    monkeypatch.setattr(jobs, "_running_session", AsyncMock(return_value=True))
    with pytest.raises(jobs.JobConflict) as info:
        await jobs.start_job("p", "plo_report", {}, _ok)
    assert "pipeline" in info.value.detail_th


async def test_two_concurrent_starts_on_one_program_admit_one(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Double click / two tabs. Without the per-program lock both pass the
    check before either inserts."""
    real_insert = jobs_store.insert

    async def slow_insert(job):  # noqa: ANN001, ANN202
        await asyncio.sleep(0.01)
        await real_insert(job)

    monkeypatch.setattr(jobs_store, "insert", slow_insert)
    results = await asyncio.gather(
        jobs.start_job("p", "plo_report", {}, _ok),
        jobs.start_job("p", "plo_report", {}, _ok),
        return_exceptions=True,
    )
    assert sum(isinstance(r, jobs.JobConflict) for r in results) == 1


async def test_a_failure_while_recording_the_outcome_does_not_escape(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = await jobs.start_job("p", "plo_report", {}, _ok)
    monkeypatch.setattr(jobs_store, "finish", AsyncMock(side_effect=RuntimeError("db down")))
    await spawned.coros.pop(0)  # must not raise
    assert jobs_store.rows[job.job_id].status == "running"


async def test_start_job_or_409(spawned: SpawnRecorder) -> None:
    await jobs.start_job_or_409("p", "plo_report", {}, _ok)
    with pytest.raises(HTTPException) as info:
        await jobs.start_job_or_409("p", "plo_report", {}, _ok)
    assert info.value.status_code == 409
    assert isinstance(info.value.detail, str)


async def test_the_sweep_fails_orphans_with_the_restart_message(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    job = await jobs.start_job("p", "plo_report", {}, _ok)
    assert await jobs.sweep_orphaned_jobs() == 1
    swept = jobs_store.rows[job.job_id]
    assert swept.status == "failed"
    assert swept.error_th == jobs.RESTART_MESSAGE_TH
    # and the program is free again
    await jobs.start_job("p", "plo_report", {}, _ok)


async def test_the_sweep_also_fails_orphaned_graph_sessions(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A graph run is an in-process task too: one left `running` by a dead
    process would block its program for ever, with no UI route able to end it."""
    await jobs.start_job("p", "plo_report", {}, _ok)
    sessions = MagicMock()
    sessions.fail_all_running = AsyncMock(return_value=2)
    monkeypatch.setattr(jobs, "SessionRepository", lambda: sessions)
    assert await jobs.sweep_orphaned_jobs() == 3
    sessions.fail_all_running.assert_awaited_once_with(jobs.RESTART_MESSAGE_TH)


async def test_program_lock_is_the_lock_start_job_takes(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    """Synchronous writers hold the same per-program lock, so a job cannot start
    between their busy-check and their write."""
    async with jobs.program_lock("p"):
        task = asyncio.create_task(jobs.start_job("p", "plo_report", {}, _ok))
        await asyncio.sleep(0.01)
        assert not task.done()
        assert jobs_store.rows == {}
        async with jobs.program_lock("q"):  # another program is not held up
            pass
    await task
    assert len(jobs_store.rows) == 1


async def test_program_busy_reports_job_session_or_none(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert await jobs.program_busy("p") is None
    await jobs.start_job("p", "need_combination", {}, _ok)
    assert jobs.JOB_KIND_LABEL_TH["need_combination"] in (await jobs.program_busy("p") or "")
    monkeypatch.setattr(jobs, "_running_session", AsyncMock(return_value=True))
    assert await jobs.program_busy("q") is not None
