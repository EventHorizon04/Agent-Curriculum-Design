"""In-memory stand-ins for the job runner's two side doors.

`InMemoryJobs` replaces `JobRepository`; `SpawnRecorder` replaces
`api.jobs.spawn`. Under TestClient each request runs on a short-lived portal
loop, so a real background task would be abandoned when the request returns;
recording the coroutine and draining it on a fresh loop is deterministic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime
from typing import Any

from curriculum_agent.models import JobInfo


class InMemoryJobs:
    def __init__(self) -> None:
        self.rows: dict[str, JobInfo] = {}

    async def insert(self, job: JobInfo) -> None:
        self.rows[job.job_id] = job

    async def get(self, job_id: str) -> JobInfo | None:
        return self.rows.get(job_id)

    async def list_by_program(
        self, program_id: str, *, active_only: bool = False, limit: int = 20
    ) -> list[JobInfo]:
        rows = [j for j in self.rows.values() if j.program_id == program_id]
        if active_only:
            rows = [j for j in rows if j.status == "running"]
        return sorted(rows, key=lambda j: j.created_at, reverse=True)[:limit]

    async def find_running(self, program_id: str) -> JobInfo | None:
        running = await self.list_by_program(program_id, active_only=True)
        return running[0] if running else None

    async def finish(
        self, job_id: str, status: str, *, result: Any = None, error_th: str | None = None
    ) -> bool:
        job = self.rows.get(job_id)
        if job is None:
            return False
        self.rows[job_id] = job.model_copy(
            update={
                "status": status,
                "result": result,
                "error_th": error_th,
                "finished_at": datetime.utcnow(),
            }
        )
        return True

    async def fail_all_running(self, message: str) -> int:
        n = 0
        for job_id, job in list(self.rows.items()):
            if job.status == "running":
                await self.finish(job_id, "failed", error_th=message)
                n += 1
        return n


class SpawnRecorder:
    def __init__(self) -> None:
        self.coros: list[Coroutine[Any, Any, None]] = []

    def __call__(self, coro: Coroutine[Any, Any, None]) -> None:
        self.coros.append(coro)

    def drain(self) -> None:
        """Run every recorded job body to completion (sync tests only)."""
        while self.coros:
            asyncio.run(self.coros.pop(0))

    def close(self) -> None:
        for coro in self.coros:
            coro.close()
        self.coros.clear()
