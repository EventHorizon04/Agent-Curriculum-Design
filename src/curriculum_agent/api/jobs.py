"""Background stage runs: one active writer per program, outcome recorded.

Every long stage route used to hold its HTTP request open for minutes: the page
lost "running" when the designer navigated away, a refresh never knew, and the
Cloudflare tunnel cuts a request at ~100 s. A route now checks its
preconditions, calls `start_job`, and answers 202; the page polls
`GET /jobs`. See docs/superpowers/specs/2026-10-08-background-jobs-design.md.

One active writer per program: every stage deletes and rewrites tables the
next stage reads, so two runs on one program — or a run and a graph session —
interleave. The check-then-insert is serialised per program in this process
(the deployment is one uvicorn process).

A writer that finishes inside its request holds `program_lock` around the check and
its short write. One whose write follows an LLM call of minutes — the merge route —
cannot hold a lock that long, so it registers with `sync_writer` instead: the lock
covers only the check and the registration, and `program_busy` reports the
registration to everyone else until the call is over.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from loguru import logger
from pydantic import BaseModel

from curriculum_agent.data.repositories import JobRepository, SessionRepository
from curriculum_agent.models import JobInfo, JobKind

# JobRepository is re-exported on purpose: the routes reach the repository through
# this module so one patch (tests/conftest.py) covers the runner and the routes.
__all__ = [
    "JOB_KIND_LABEL_TH",
    "RESTART_MESSAGE_TH",
    "JobConflict",
    "JobRepository",
    "program_busy",
    "program_lock",
    "spawn",
    "start_job",
    "start_job_or_409",
    "sweep_orphaned_jobs",
    "sync_writer",
    "with_label",
]

JOB_KIND_LABEL_TH: dict[str, str] = {
    "needs_pipeline": "สกัดทักษะและรวมความต้องการ",
    "skill_extraction": "สกัดทักษะ",
    "need_combination": "รวมความต้องการ",
    "plo_synthesis": "สังเคราะห์ PLO",
    "plo_review": "ตรวจคุณภาพชุด PLO",
    "plo_report": "ออกรายงาน PLO",
    "plo_revalidate": "ตรวจ SMART ซ้ำ",
}
RESTART_MESSAGE_TH = "backend ถูกปิดระหว่างทำงาน — กดรันใหม่"

_LOCKS: dict[str, asyncio.Lock] = {}
_TASKS: set[asyncio.Task[None]] = set()
# program_id -> why it is busy, for a synchronous writer in the middle of its call.
_SYNC_WRITERS: dict[str, str] = {}


class JobConflict(Exception):
    def __init__(self, detail_th: str) -> None:
        super().__init__(detail_th)
        self.detail_th = detail_th


@asynccontextmanager
async def program_lock(program_id: str) -> AsyncIterator[None]:
    """Synchronous writers hold this around their busy-check and their short write."""
    async with _LOCKS.setdefault(program_id, asyncio.Lock()):
        yield


@asynccontextmanager
async def sync_writer(program_id: str, reason_th: str) -> AsyncIterator[None]:
    """A writer whose work outlasts any lock it could hold (an LLM call).

    Under `program_lock` it checks `program_busy` — 409 with the reason when the
    program is busy — and registers, then releases the lock before the body runs:
    holding it for minutes would stall every `start_job` queued behind it, where
    the registration makes them answer 409 at once. `reason_th` is what everyone
    else is told while it runs. The registration goes whatever the body does."""
    async with program_lock(program_id):
        busy = await program_busy(program_id)
        if busy is not None:
            raise HTTPException(status_code=409, detail=busy)
        _SYNC_WRITERS[program_id] = reason_th
    try:
        yield
    finally:
        _SYNC_WRITERS.pop(program_id, None)


def with_label(job: JobInfo) -> JobInfo:
    return job.model_copy(update={"label_th": JOB_KIND_LABEL_TH.get(job.kind, job.kind)})


async def _running_session(program_id: str) -> bool:
    sessions = await SessionRepository().list_by_program(program_id)
    return any(s.status == "running" for s in sessions)


async def program_busy(program_id: str) -> str | None:
    """Why this program cannot take another writer right now, in Thai, or None."""
    if (registered := _SYNC_WRITERS.get(program_id)) is not None:
        return registered
    running = await JobRepository().find_running(program_id)
    if running is not None:
        label = JOB_KIND_LABEL_TH.get(running.kind, running.kind)
        return f"หลักสูตรนี้มีงาน{label} กำลังทำอยู่ — รอให้เสร็จก่อน"
    if await _running_session(program_id):
        return "หลักสูตรนี้กำลังรัน pipeline อยู่ — รอให้เสร็จก่อน"
    return None


def spawn(coro: Coroutine[Any, Any, None]) -> None:
    """Start a job body. Holds a reference until it ends: a bare create_task
    can be garbage-collected mid-run. Tests replace this function."""
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def _error_th(exc: BaseException) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    if isinstance(exc, TimeoutError):
        return "หมดเวลา — งานใช้เวลานานเกินกำหนด กรุณาลองใหม่"
    return str(exc) or type(exc).__name__


def _dump(value: BaseModel | Sequence[BaseModel]) -> Any:
    # Sequence, not list: list is invariant, so a work() returning list[PLO]
    # would not type-check against list[BaseModel].
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return [v.model_dump(mode="json") for v in value]


async def _run(
    job_id: str,
    kind: str,
    work: Callable[[], Awaitable[BaseModel | Sequence[BaseModel]]],
    on_success: Callable[[], Awaitable[None]] | None = None,
) -> None:
    repo = JobRepository()
    try:
        # The dump is inside the try: a work() that returns something that is not
        # a model would otherwise escape here and leave the job `running` for ever.
        outcome: dict[str, Any] = {"status": "succeeded", "result": _dump(await work())}
        logger.info(f"job {job_id} ({kind}) succeeded")
    except Exception as exc:  # noqa: BLE001 - every failure becomes the job's error
        if isinstance(exc, HTTPException):
            # A refusal the stage chose to make: its detail is the whole story.
            logger.error(f"job {job_id} ({kind}) failed: {exc!r}")
        else:
            # Anything else is a bug or an outage, and the job row keeps only
            # str(exc) — the traceback is lost unless it is logged here.
            logger.opt(exception=exc).error(f"job {job_id} ({kind}) failed: {exc!r}")
        outcome = {"status": "failed", "error_th": _error_th(exc)}
    try:
        status = outcome.pop("status")
        if not await repo.finish(job_id, status, **outcome):
            logger.warning(f"job {job_id}: row gone before its outcome was recorded")
    except Exception as exc:  # noqa: BLE001 - nobody is awaiting this task
        logger.error(f"job {job_id}: could not record its outcome: {exc!r}")
        return
    if on_success is None or status != "succeeded":
        return
    # After the row says `succeeded`, so the follow-up's busy check sees this job
    # finished. A failure here is the follow-up's own; the finished job stays as is.
    try:
        await on_success()
    except Exception as exc:  # noqa: BLE001 - nobody is awaiting this task
        logger.opt(exception=exc).error(f"job {job_id} ({kind}): on_success failed: {exc!r}")


async def start_job(
    program_id: str,
    kind: JobKind,
    params: dict[str, Any],
    work: Callable[[], Awaitable[BaseModel | Sequence[BaseModel]]],
    *,
    on_success: Callable[[], Awaitable[None]] | None = None,
) -> JobInfo:
    async with program_lock(program_id):
        reason = await program_busy(program_id)
        if reason is not None:
            raise JobConflict(reason)
        job = JobInfo(
            job_id=str(uuid.uuid4()),
            program_id=program_id,
            kind=kind,
            status="running",
            params=params,
            created_at=datetime.utcnow(),
        )
        await JobRepository().insert(job)
    logger.info(f"job {job.job_id} ({kind}) started for {program_id}")
    spawn(_run(job.job_id, kind, work, on_success))
    return with_label(job)


async def start_job_or_409(
    program_id: str,
    kind: JobKind,
    params: dict[str, Any],
    work: Callable[[], Awaitable[BaseModel | Sequence[BaseModel]]],
    *,
    on_success: Callable[[], Awaitable[None]] | None = None,
) -> JobInfo:
    try:
        return await start_job(program_id, kind, params, work, on_success=on_success)
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail_th) from exc


async def sweep_orphaned_jobs() -> int:
    """At startup: a job or graph session still `running` was owned by a process
    that is gone. Both block their program until swept."""
    jobs_swept = await JobRepository().fail_all_running(RESTART_MESSAGE_TH)
    if jobs_swept:
        logger.warning(f"jobs: marked {jobs_swept} orphaned running job(s) failed at startup")
    sessions_swept = await SessionRepository().fail_all_running(RESTART_MESSAGE_TH)
    if sessions_swept:
        logger.warning(
            f"jobs: marked {sessions_swept} orphaned running session(s) failed at startup"
        )
    return jobs_swept + sessions_swept
