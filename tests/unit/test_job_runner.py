"""api/jobs.py: start, run, record, refuse, sweep."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from curriculum_agent.api import jobs

# Bound here, at import, which is before the autouse `jobs_store` fixture replaces
# `jobs.spawn` with a recorder: this is the one handle on the real function.
from curriculum_agent.api.jobs import spawn as real_spawn
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


async def test_on_success_runs_after_the_job_is_recorded_succeeded(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    seen: list[str] = []

    async def after() -> None:
        seen.append(next(iter(jobs_store.rows.values())).status)

    await jobs.start_job("p", "plo_report", {}, _ok, on_success=after)
    await spawned.coros.pop(0)
    assert seen == ["succeeded"]


async def test_on_success_not_called_on_failure(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    after = AsyncMock()

    async def boom() -> _Out:
        raise RuntimeError("x")

    job = await jobs.start_job("p", "plo_report", {}, boom, on_success=after)
    await spawned.coros.pop(0)
    after.assert_not_awaited()
    assert jobs_store.rows[job.job_id].status == "failed"


async def test_on_success_exception_does_not_flip_job_status(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    async def after() -> None:
        raise RuntimeError("chain broke")

    job = await jobs.start_job("p", "plo_report", {}, _ok, on_success=after)
    await spawned.coros.pop(0)
    done = jobs_store.rows[job.job_id]
    assert done.status == "succeeded"
    assert done.result == {"n": 3}


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


async def test_the_409_text_keeps_the_label_and_the_verb_apart(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    """Thai has no spaces to fall back on: "{label}กำลังทำอยู่" ran an English
    label straight into the verb ("สังเคราะห์ PLOกำลังทำอยู่")."""
    await jobs.start_job("p", "plo_synthesis", {}, _ok)
    with pytest.raises(jobs.JobConflict) as info:
        await jobs.start_job("p", "plo_report", {}, _ok)
    assert "PLO กำลังทำอยู่" in info.value.detail_th


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


# ---------- sync_writer: the merge route's registration ----------


async def test_a_registered_sync_writer_makes_its_program_busy_with_its_own_reason(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    assert await jobs.program_busy("p") is None
    async with jobs.sync_writer("p", "กำลังรวม Need"):
        assert await jobs.program_busy("p") == "กำลังรวม Need"
        assert await jobs.program_busy("q") is None
    assert await jobs.program_busy("p") is None


async def test_a_registered_sync_writer_refuses_start_job(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    async with jobs.sync_writer("p", "กำลังรวม Need"):
        with pytest.raises(jobs.JobConflict) as info:
            await jobs.start_job("p", "plo_report", {}, _ok)
    assert info.value.detail_th == "กำลังรวม Need"
    assert jobs_store.rows == {}
    assert spawned.coros == []


async def test_a_second_sync_writer_is_refused_with_the_first_ones_reason(
    jobs_store: InMemoryJobs,
) -> None:
    async with jobs.sync_writer("p", "กำลังรวม Need"):
        with pytest.raises(HTTPException) as info:
            async with jobs.sync_writer("p", "อย่างอื่น"):
                pytest.fail("the second writer must not get in")
    assert info.value.status_code == 409
    assert info.value.detail == "กำลังรวม Need"
    # the refused one did not register, and the first one's registration survived it
    assert await jobs.program_busy("p") is None


async def test_sync_writer_is_refused_while_a_job_runs_and_does_not_register(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    await jobs.start_job("p", "plo_synthesis", {}, _ok)
    with pytest.raises(HTTPException) as info:
        async with jobs.sync_writer("p", "กำลังรวม Need"):
            pytest.fail("a busy program must not admit a writer")
    assert info.value.status_code == 409
    assert "PLO กำลังทำอยู่" in str(info.value.detail)
    assert "p" not in jobs._SYNC_WRITERS


async def test_sync_writer_registration_is_removed_when_its_body_raises() -> None:
    with pytest.raises(RuntimeError):
        async with jobs.sync_writer("p", "กำลังรวม Need"):
            raise RuntimeError("synthesis blew up")
    assert await jobs.program_busy("p") is None
    assert jobs._SYNC_WRITERS == {}


async def test_sync_writer_does_not_hold_the_program_lock_across_its_body(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    """The body is an LLM call of minutes. Holding the lock would stall every
    other writer's queue for that long instead of answering them 409."""
    async with jobs.sync_writer("p", "กำลังรวม Need"):
        async with asyncio.timeout(1):
            async with jobs.program_lock("p"):
                pass


async def test_sync_writer_waits_for_the_program_lock_before_checking(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    entered = asyncio.Event()

    async def writer() -> None:
        async with jobs.sync_writer("p", "กำลังรวม Need"):
            entered.set()

    async with jobs.program_lock("p"):
        task = asyncio.create_task(writer())
        await asyncio.sleep(0.01)
        assert not entered.is_set()
    await task
    assert entered.is_set()


# ---------- spawn ----------


async def test_spawn_holds_the_task_while_it_runs_and_lets_go_when_it_ends() -> None:
    gate = asyncio.Event()

    async def body() -> None:
        await gate.wait()

    before = set(jobs._TASKS)
    real_spawn(body())
    (task,) = jobs._TASKS - before
    assert not task.done()
    gate.set()
    await task
    await asyncio.sleep(0)  # done-callbacks run on the loop's next turn
    assert task not in jobs._TASKS


# ---------- what is logged ----------


def _capture_errors() -> tuple[list[str], int]:
    from loguru import logger  # noqa: PLC0415

    seen: list[str] = []
    sink_id = logger.add(lambda m: seen.append(str(m)), level="ERROR", format="{message}")
    return seen, sink_id


async def test_an_unexpected_failure_is_logged_with_its_traceback(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    from loguru import logger  # noqa: PLC0415

    async def boom() -> _Out:
        raise ValueError("kaboom-marker")

    seen, sink_id = _capture_errors()
    try:
        await jobs.start_job("p", "plo_report", {}, boom)
        await spawned.coros.pop(0)
    finally:
        logger.remove(sink_id)
    text = "\n".join(seen)
    assert "kaboom-marker" in text
    assert "Traceback" in text


async def test_an_http_failure_stays_a_one_line_log(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    from loguru import logger  # noqa: PLC0415

    async def refused() -> _Out:
        raise HTTPException(status_code=422, detail="ยังไม่มี PLO")

    seen, sink_id = _capture_errors()
    try:
        await jobs.start_job("p", "plo_report", {}, refused)
        await spawned.coros.pop(0)
    finally:
        logger.remove(sink_id)
    text = "\n".join(seen)
    assert "failed" in text
    assert "Traceback" not in text
