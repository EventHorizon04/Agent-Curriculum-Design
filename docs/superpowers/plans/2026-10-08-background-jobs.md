# Background Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Long stage runs become background jobs (202 + poll), so every page shows the true running/finished/failed state across navigation, refresh, other tabs and the Cloudflare tunnel.

**Architecture:** A `jobs` table and `JobRepository` hold each run's status, params, result and Thai error. `api/jobs.py` starts a job (one active writer per program, counting running graph sessions), runs the old route body in an asyncio task through a patchable `spawn`, records the outcome, and sweeps orphaned jobs at startup. Seven routes keep their synchronous preconditions and return 202 + `JobInfo`; `GET /jobs` exposes state. The frontend gets one polling hook shared through a context in `StageLayout`; pages derive "running" and "last result/error" from the server's job list.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, pytest (asyncio_mode=auto); React 19 + TypeScript + Vite, axios.

**Spec:** `docs/superpowers/specs/2026-10-08-background-jobs-design.md`

## Global Constraints

- Work on `main` (user-approved). Stage by explicit path only. Never stage `.scratch/plo-scope-guard/**`, the deleted `curriculum-design-agent.skill`, or untracked `.claude/skills/*`. `frontend/**` is now in scope (the frontend session is closed) — stage only the files your task touches.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
- Never read `.env`. Do not touch the live database (the controller migrates it). Do not call any LLM endpoint. Do not dispatch subagents.
- Mutation checks use Edit, never `git checkout --` / `git restore` / `git stash`.
- Python: `from __future__ import annotations`, type hints on every signature, `loguru` not `logging`, English code/comments/logs, Thai for user-facing strings. Repository pattern for all data access.
- Job `kind` values, exactly: `needs_pipeline`, `skill_extraction`, `need_combination`, `plo_synthesis`, `plo_review`, `plo_report`, `plo_revalidate`. `status` values: `running`, `succeeded`, `failed`.
- One active writer per program: a `running` job **or** a `running` graph session blocks `start_job` and the synchronous writers (`POST /sessions/`, `POST /sessions/{id}/approve`, `POST /plos/from-needs`, `POST /programs/{id}/copy`) with **409** whose `detail` is a plain Thai string.
- The seven routes keep every precondition they check today (404/422/503) synchronous, before any job row exists, and return **202** with `JobInfo` otherwise.
- `JobInfo` timestamps serialize as ISO with `+00:00`. DB columns stay naive UTC (`datetime.utcnow()`), like every other table.
- Backend verify: `uv run pytest -q`, `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, `uv run mypy src/`, with `PYTHONIOENCODING=utf-8`. Frontend verify: `cd frontend && npm run lint && npm run build`.
- No real-DB test fixture exists: repositories are tested with mocked sessions, routes with `TestClient` and patched repositories.

## Review Focus

1. **Double click / two tabs start the same run at once** → exactly one 202, the other 409; pinned in Task 2 (`test_two_concurrent_starts_on_one_program_admit_one`).
2. **Backend restarts (or reloads on a code change) mid-run** → the job reads `failed` with the restart message, the program is not blocked forever, and the page shows the error; pinned in Task 2 (sweep) and Task 7 (latest failed job shown).
3. **Program deleted while its job runs** → recording the outcome on a vanished row must not raise or crash the task; pinned in Task 1 (`finish` on a missing row) and Task 2 (`_run` survives a `finish` failure).
4. **API unreachable while a page polls** (backend stopped, tunnel blip) → the hook keeps its last state, retries on the next tick, and never throws into the page; pinned in Task 6.
5. **Designer switches program while a job runs on the first** → the hook re-keys on `programId`, never shows program A's job on program B; pinned in Task 6.

---

### Task 1: `jobs` table, `JobInfo`, `JobRepository`

**Files:**
- Create: `migrations/versions/d1e2f3a4b5c6_jobs.py`
- Modify: `src/curriculum_agent/data/orm.py` (new `JobTable`)
- Modify: `src/curriculum_agent/models.py` (new `JobKind`, `JobStatus`, `JobInfo`)
- Modify: `src/curriculum_agent/data/repositories.py` (new `JobRepository`; `delete_cascade` deletes jobs)
- Test: `tests/unit/test_job_repository.py` (new)

**Interfaces:**
- Produces:
  - `JobKind = Literal["needs_pipeline", "skill_extraction", "need_combination", "plo_synthesis", "plo_review", "plo_report", "plo_revalidate"]`
  - `JobStatus = Literal["running", "succeeded", "failed"]`
  - `class JobInfo(BaseModel)`: `job_id: str`, `program_id: str`, `kind: JobKind`, `label_th: str = ""`, `status: JobStatus`, `params: dict[str, Any] = {}`, `result: Any | None = None`, `error_th: str | None = None`, `created_at: datetime`, `finished_at: datetime | None = None`; datetimes serialize with `+00:00`.
  - `JobRepository`: `async insert(job: JobInfo) -> None`, `async get(job_id: str) -> JobInfo | None`, `async list_by_program(program_id: str, *, active_only: bool = False, limit: int = 20) -> list[JobInfo]` (newest first), `async find_running(program_id: str) -> JobInfo | None`, `async finish(job_id: str, status: JobStatus, *, result: Any | None = None, error_th: str | None = None) -> bool` (False when the row is gone), `async fail_all_running(message: str) -> int`.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_job_repository.py`

```python
"""The jobs table: one row per background stage run (spec: background jobs)."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from curriculum_agent.data.orm import JobTable
from curriculum_agent.data.repositories import JobRepository, ProgramRepository
from curriculum_agent.models import JobInfo


def _job(**over: object) -> JobInfo:
    base = dict(
        job_id="j1",
        program_id="program-2",
        kind="plo_report",
        status="running",
        params={},
        created_at=datetime(2026, 10, 8, 3, 0, 0),
    )
    base.update(over)
    return JobInfo(**base)  # type: ignore[arg-type]


def test_job_timestamps_serialize_with_a_utc_offset() -> None:
    """A naive ISO string is read by browsers as local time — 7 hours off in
    Thailand — and RunProgress computes elapsed time from created_at."""
    dumped = json.loads(_job(finished_at=datetime(2026, 10, 8, 3, 5, 0)).model_dump_json())
    assert dumped["created_at"].endswith("+00:00")
    assert dumped["finished_at"].endswith("+00:00")
    assert json.loads(_job().model_dump_json())["finished_at"] is None


def test_the_table_has_the_spec_columns() -> None:
    cols = {c.name for c in JobTable.__table__.columns}
    assert cols == {
        "job_id", "program_id", "kind", "status", "params",
        "result", "error_th", "created_at", "finished_at",
    }
    assert [fk.column.table.name for fk in JobTable.__table__.columns["program_id"].foreign_keys] == ["programs"]


def test_the_migration_creates_and_drops_the_table() -> None:
    path = next(Path("migrations/versions").glob("*_jobs.py"))
    spec = importlib.util.spec_from_file_location("m", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    op = MagicMock()
    module.op = op
    module.upgrade()
    module.downgrade()
    assert module.down_revision == "c0f1e2d3a4b5"
    assert op.create_table.call_args.args[0] == "jobs"
    op.drop_table.assert_called_once_with("jobs")


def _session_ctx(session: AsyncMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


async def test_finish_on_a_vanished_row_returns_false_without_raising() -> None:
    """The program can be deleted (and its jobs with it) while the task runs."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_session_ctx(session)):
        assert await JobRepository().finish("gone", "succeeded", result={"x": 1}) is False
    session.commit.assert_not_awaited()


async def test_finish_records_status_result_error_and_time() -> None:
    row = JobTable(job_id="j1", program_id="p", kind="plo_report", status="running",
                   params={}, created_at=datetime(2026, 10, 8))
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_session_ctx(session)):
        assert await JobRepository().finish("j1", "failed", error_th="ล้มเหลว") is True
    assert row.status == "failed"
    assert row.error_th == "ล้มเหลว"
    assert row.finished_at is not None
    session.commit.assert_awaited_once()


async def test_delete_cascade_deletes_the_programs_jobs() -> None:
    session = AsyncMock()
    executed: list[str] = []

    async def execute(stmt):  # noqa: ANN001, ANN202
        executed.append(str(stmt))
        result = MagicMock()
        result.rowcount = 1
        return result

    session.execute = execute
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_session_ctx(session)):
        await ProgramRepository().delete_cascade("program-2")
    assert any("DELETE FROM jobs" in s for s in executed)
    # jobs reference programs, so they go before the program row
    assert executed.index(next(s for s in executed if "DELETE FROM jobs" in s)) < executed.index(
        next(s for s in executed if "DELETE FROM programs" in s)
    )
```

Add one more test of your own for `fail_all_running` (mocked `session.execute` returning a result with `rowcount=2` → returns 2, commits once) and one for `list_by_program(active_only=True)` building a query filtered on `status == 'running'` (assert on the compiled SQL string, as the cascade test does).

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/unit/test_job_repository.py -v` → FAIL (imports).

- [ ] **Step 3: Migration** — `migrations/versions/d1e2f3a4b5c6_jobs.py`

```python
"""jobs: background stage runs, one row per run

Revision ID: d1e2f3a4b5c6
Revises: c0f1e2d3a4b5
Create Date: 2026-10-08 00:00:00.000000

A new table, nothing to backfill. See
docs/superpowers/specs/2026-10-08-background-jobs-design.md.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "c0f1e2d3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), sa.ForeignKey("programs.program_id"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_th", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("job_id", name="jobs_pkey"),
    )
    op.create_index("ix_jobs_program_status", "jobs", ["program_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_jobs_program_status", table_name="jobs")
    op.drop_table("jobs")
```

- [ ] **Step 4: ORM** — `src/curriculum_agent/data/orm.py`, after `PLOReviewTable`:

```python
class JobTable(Base):
    """A background stage run (api/jobs.py). `result` is the JSON body the
    route used to return synchronously; `error_th` is what the designer reads
    when it failed. String kind/status, not PG enums (project convention)."""

    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    program_id: Mapped[str] = mapped_column(String, ForeignKey("programs.program_id"))
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    error_th: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

- [ ] **Step 5: Models** — `src/curriculum_agent/models.py`, after `SessionInfo`:

```python
JobKind = Literal[
    "needs_pipeline",
    "skill_extraction",
    "need_combination",
    "plo_synthesis",
    "plo_review",
    "plo_report",
    "plo_revalidate",
]
JobStatus = Literal["running", "succeeded", "failed"]


class JobInfo(BaseModel):
    """A background stage run as the API reports it (api/jobs.py)."""

    job_id: str
    program_id: str
    kind: JobKind
    label_th: str = ""
    status: JobStatus
    params: dict[str, Any] = Field(default_factory=dict)
    result: Any | None = None
    error_th: str | None = None
    created_at: datetime
    finished_at: datetime | None = None

    # Stored naive UTC like every table here; sent with its offset, because a
    # browser reads a naive ISO string as local time.
    @field_serializer("created_at", "finished_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
```

(Import `UTC` from `datetime` and `field_serializer` from pydantic if not already imported.)

- [ ] **Step 6: Repository** — `src/curriculum_agent/data/repositories.py`. Add `JobTable` and `JobInfo`/`JobStatus` imports, a `JobTable` delete in `delete_cascade` (before the `ProgramTable` delete; update the docstring's count of prior deletes), and:

```python
class JobRepository:
    """Background stage runs (api/jobs.py). `label_th` is not stored; the
    runner fills it on the way out."""

    async def insert(self, job: JobInfo) -> None:
        async with AsyncSessionLocal() as session:
            data = job.model_dump(exclude={"label_th"})
            session.add(JobTable(**data))
            await session.commit()

    async def get(self, job_id: str) -> JobInfo | None:
        async with AsyncSessionLocal() as session:
            row = await session.get(JobTable, job_id)
            return None if row is None else JobInfo.model_validate(_row_to_dict(row))

    async def list_by_program(
        self, program_id: str, *, active_only: bool = False, limit: int = 20
    ) -> list[JobInfo]:
        async with AsyncSessionLocal() as session:
            stmt = select(JobTable).where(JobTable.program_id == program_id)
            if active_only:
                stmt = stmt.where(JobTable.status == "running")
            stmt = stmt.order_by(JobTable.created_at.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
            return [JobInfo.model_validate(_row_to_dict(r)) for r in rows]

    async def find_running(self, program_id: str) -> JobInfo | None:
        running = await self.list_by_program(program_id, active_only=True, limit=1)
        return running[0] if running else None

    async def finish(
        self,
        job_id: str,
        status: JobStatus,
        *,
        result: Any | None = None,
        error_th: str | None = None,
    ) -> bool:
        """Record the outcome. False when the row is gone (program deleted
        while the job ran) — never raises for that."""
        async with AsyncSessionLocal() as session:
            row = await session.get(JobTable, job_id)
            if row is None:
                return False
            row.status = status
            row.result = result
            row.error_th = error_th
            row.finished_at = datetime.utcnow()
            await session.commit()
            return True

    async def fail_all_running(self, message: str) -> int:
        """Startup sweep: a job still `running` belongs to a dead process."""
        async with AsyncSessionLocal() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(JobTable)
                    .where(JobTable.status == "running")
                    .values(status="failed", error_th=message, finished_at=datetime.utcnow())
                ),
            )
            await session.commit()
            return result.rowcount
```

- [ ] **Step 7: Run tests** (new file, full suite, ruff, format, mypy).
- [ ] **Step 8: Mutation check** — remove the `if row is None: return False` guard in `finish`; the vanished-row test must fail. Restore.
- [ ] **Step 9: Commit**

```bash
git add migrations/versions/d1e2f3a4b5c6_jobs.py src/curriculum_agent/data/orm.py src/curriculum_agent/models.py src/curriculum_agent/data/repositories.py tests/unit/test_job_repository.py
git commit -m "feat(jobs): a jobs table and repository for background stage runs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Job runner, `GET /jobs`, startup sweep, test harness

**Files:**
- Create: `src/curriculum_agent/api/jobs.py`
- Create: `src/curriculum_agent/api/routes/jobs.py`
- Modify: `src/curriculum_agent/api/main.py` (mount router; sweep in lifespan)
- Create: `tests/support/jobs.py`
- Modify: `tests/conftest.py` (autouse in-memory jobs + spawn recorder)
- Test: `tests/unit/test_job_runner.py` (new), `tests/unit/test_jobs_router.py` (new)

**Interfaces:**
- Consumes: `JobInfo`, `JobKind`, `JobRepository` (Task 1); `SessionRepository.list_by_program`.
- Produces (in `curriculum_agent.api.jobs`):
  - `JOB_KIND_LABEL_TH: dict[str, str]`
  - `class JobConflict(Exception)` with `.detail_th: str`
  - `async def program_busy(program_id: str) -> str | None` — Thai reason or None
  - `def spawn(coro: Coroutine[Any, Any, None]) -> None`
  - `async def start_job(program_id: str, kind: JobKind, params: dict[str, Any], work: Callable[[], Awaitable[BaseModel | Sequence[BaseModel]]]) -> JobInfo`
  - `async def start_job_or_409(...) -> JobInfo` — same args; converts `JobConflict` to `HTTPException(409, detail=detail_th)`
  - `async def sweep_orphaned_jobs() -> int`
  - `def with_label(job: JobInfo) -> JobInfo`
  - `RESTART_MESSAGE_TH = "backend ถูกปิดระหว่างทำงาน — กดรันใหม่"`
- Produces (tests): `tests.support.jobs.InMemoryJobs`, fixture `jobs_store` (autouse in conftest, returns the store), fixture `spawned` (returns the `SpawnRecorder`, with `.coros` and `.drain()`).

- [ ] **Step 1: Test harness** — `tests/support/jobs.py`

```python
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

    async def finish(self, job_id: str, status: str, *, result: Any = None, error_th: str | None = None) -> bool:
        job = self.rows.get(job_id)
        if job is None:
            return False
        self.rows[job_id] = job.model_copy(
            update={"status": status, "result": result, "error_th": error_th,
                    "finished_at": datetime.utcnow()}
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
```

`tests/conftest.py` — add (follow the file's existing autouse style):

```python
@pytest.fixture(autouse=True)
def jobs_store(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemoryJobs]:
    """Every test runs jobs against memory and records spawned bodies instead
    of starting tasks. No running graph session unless a test says so."""
    from curriculum_agent.api import jobs as jobs_mod

    store = InMemoryJobs()
    recorder = SpawnRecorder()
    monkeypatch.setattr(jobs_mod, "JobRepository", lambda: store)
    monkeypatch.setattr(jobs_mod, "spawn", recorder)
    monkeypatch.setattr(jobs_mod, "_running_session", AsyncMock(return_value=False))
    jobs_mod._LOCKS.clear()
    store.recorder = recorder  # type: ignore[attr-defined]
    yield store
    recorder.close()


@pytest.fixture
def spawned(jobs_store: InMemoryJobs) -> SpawnRecorder:
    return jobs_store.recorder  # type: ignore[attr-defined, no-any-return]
```

- [ ] **Step 2: Write the failing runner tests** — `tests/unit/test_job_runner.py`

```python
"""api/jobs.py: start, run, record, refuse, sweep."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from curriculum_agent.api import jobs
from tests.support.jobs import InMemoryJobs, SpawnRecorder


class _Out(BaseModel):
    n: int


async def _ok() -> _Out:
    return _Out(n=3)


async def test_start_records_running_and_spawns(jobs_store: InMemoryJobs, spawned: SpawnRecorder) -> None:
    job = await jobs.start_job("p", "plo_report", {"x": 1}, _ok)
    assert job.status == "running"
    assert job.label_th == jobs.JOB_KIND_LABEL_TH["plo_report"]
    assert jobs_store.rows[job.job_id].params == {"x": 1}
    assert len(spawned.coros) == 1


async def test_success_records_the_result_body(jobs_store: InMemoryJobs, spawned: SpawnRecorder) -> None:
    job = await jobs.start_job("p", "plo_report", {}, _ok)
    await spawned.coros.pop(0)
    done = jobs_store.rows[job.job_id]
    assert done.status == "succeeded"
    assert done.result == {"n": 3}
    assert done.finished_at is not None


async def test_a_list_result_is_dumped_item_by_item(jobs_store: InMemoryJobs, spawned: SpawnRecorder) -> None:
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


async def test_a_running_job_refuses_a_second(jobs_store: InMemoryJobs, spawned: SpawnRecorder) -> None:
    await jobs.start_job("p", "plo_synthesis", {}, _ok)
    with pytest.raises(jobs.JobConflict) as info:
        await jobs.start_job("p", "plo_report", {}, _ok)
    assert jobs.JOB_KIND_LABEL_TH["plo_synthesis"] in info.value.detail_th


async def test_another_program_is_not_blocked(jobs_store: InMemoryJobs, spawned: SpawnRecorder) -> None:
    await jobs.start_job("p", "plo_synthesis", {}, _ok)
    assert (await jobs.start_job("q", "plo_synthesis", {}, _ok)).program_id == "q"


async def test_a_running_session_blocks_a_job(monkeypatch: pytest.MonkeyPatch, spawned: SpawnRecorder) -> None:
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


async def test_program_busy_reports_job_session_or_none(
    jobs_store: InMemoryJobs, spawned: SpawnRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert await jobs.program_busy("p") is None
    await jobs.start_job("p", "need_combination", {}, _ok)
    assert jobs.JOB_KIND_LABEL_TH["need_combination"] in (await jobs.program_busy("p") or "")
    monkeypatch.setattr(jobs, "_running_session", AsyncMock(return_value=True))
    assert await jobs.program_busy("q") is not None
```

- [ ] **Step 3: Router tests** — `tests/unit/test_jobs_router.py`

```python
from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.models import JobInfo
from tests.support.jobs import InMemoryJobs

client = TestClient(app)


def _put(store: InMemoryJobs, job_id: str, program_id: str, status: str, minute: int) -> None:
    store.rows[job_id] = JobInfo(
        job_id=job_id, program_id=program_id, kind="plo_report", status=status,  # type: ignore[arg-type]
        created_at=datetime(2026, 10, 8, 3, minute),
    )


def test_list_jobs_newest_first_with_labels(jobs_store: InMemoryJobs) -> None:
    _put(jobs_store, "a", "p", "succeeded", 1)
    _put(jobs_store, "b", "p", "running", 2)
    _put(jobs_store, "c", "other", "running", 3)
    body = client.get("/programs/p/jobs").json()
    assert [j["job_id"] for j in body] == ["b", "a"]
    assert all(j["label_th"] for j in body)
    active = client.get("/programs/p/jobs?active=true").json()
    assert [j["job_id"] for j in active] == ["b"]


def test_get_one_job_and_404_across_programs(jobs_store: InMemoryJobs) -> None:
    _put(jobs_store, "a", "p", "succeeded", 1)
    assert client.get("/programs/p/jobs/a").json()["status"] == "succeeded"
    assert client.get("/programs/other/jobs/a").status_code == 404
    assert client.get("/programs/p/jobs/missing").status_code == 404
```

- [ ] **Step 4: Run to verify failure** — both files FAIL on import.

- [ ] **Step 5: Implement the runner** — `src/curriculum_agent/api/jobs.py`

```python
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
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from loguru import logger
from pydantic import BaseModel

from curriculum_agent.data.repositories import JobRepository, SessionRepository
from curriculum_agent.models import JobInfo, JobKind

JOB_KIND_LABEL_TH: dict[str, str] = {
    "needs_pipeline": "สกัดทักษะและรวมความต้องการ",
    "skill_extraction": "สกัดทักษะ",
    "need_combination": "รวมความต้องการ",
    "plo_synthesis": "สังเคราะห์ PLO",
    "plo_review": "ตรวจชุด PLO",
    "plo_report": "ออกรายงาน PLO",
    "plo_revalidate": "ตรวจ SMART ซ้ำ",
}
RESTART_MESSAGE_TH = "backend ถูกปิดระหว่างทำงาน — กดรันใหม่"

_LOCKS: dict[str, asyncio.Lock] = {}
_TASKS: set[asyncio.Task[None]] = set()


class JobConflict(Exception):
    def __init__(self, detail_th: str) -> None:
        super().__init__(detail_th)
        self.detail_th = detail_th


def with_label(job: JobInfo) -> JobInfo:
    return job.model_copy(update={"label_th": JOB_KIND_LABEL_TH.get(job.kind, job.kind)})


async def _running_session(program_id: str) -> bool:
    sessions = await SessionRepository().list_by_program(program_id)
    return any(s.status == "running" for s in sessions)


async def program_busy(program_id: str) -> str | None:
    """Why this program cannot take another writer right now, in Thai, or None."""
    running = await JobRepository().find_running(program_id)
    if running is not None:
        label = JOB_KIND_LABEL_TH.get(running.kind, running.kind)
        return f"หลักสูตรนี้มีงาน{label}กำลังทำอยู่ — รอให้เสร็จก่อน"
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


async def _run(job_id: str, kind: str, work: Callable[[], Awaitable[BaseModel | Sequence[BaseModel]]]) -> None:
    repo = JobRepository()
    try:
        value = await work()
    except Exception as exc:  # noqa: BLE001 - every failure becomes the job's error
        logger.error(f"job {job_id} ({kind}) failed: {exc!r}")
        outcome: dict[str, Any] = {"status": "failed", "error_th": _error_th(exc)}
    else:
        outcome = {"status": "succeeded", "result": _dump(value)}
        logger.info(f"job {job_id} ({kind}) succeeded")
    try:
        status = outcome.pop("status")
        if not await repo.finish(job_id, status, **outcome):
            logger.warning(f"job {job_id}: row gone before its outcome was recorded")
    except Exception as exc:  # noqa: BLE001 - nobody is awaiting this task
        logger.error(f"job {job_id}: could not record its outcome: {exc!r}")


async def start_job(
    program_id: str,
    kind: JobKind,
    params: dict[str, Any],
    work: Callable[[], Awaitable[BaseModel | Sequence[BaseModel]]],
) -> JobInfo:
    lock = _LOCKS.setdefault(program_id, asyncio.Lock())
    async with lock:
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
    spawn(_run(job.job_id, kind, work))
    return with_label(job)


async def start_job_or_409(
    program_id: str,
    kind: JobKind,
    params: dict[str, Any],
    work: Callable[[], Awaitable[BaseModel | Sequence[BaseModel]]],
) -> JobInfo:
    try:
        return await start_job(program_id, kind, params, work)
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail_th) from exc


async def sweep_orphaned_jobs() -> int:
    """At startup: a job still `running` was owned by a process that is gone."""
    n = await JobRepository().fail_all_running(RESTART_MESSAGE_TH)
    if n:
        logger.warning(f"jobs: marked {n} orphaned running job(s) failed at startup")
    return n
```

`src/curriculum_agent/api/routes/jobs.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from curriculum_agent.api import jobs
from curriculum_agent.models import JobInfo

router = APIRouter()


@router.get("/", response_model=list[JobInfo])
async def list_jobs(program_id: str, active: bool = False) -> list[JobInfo]:
    """Newest first, the latest 20. `active=true`: only running jobs."""
    rows = await jobs.JobRepository().list_by_program(program_id, active_only=active)
    return [jobs.with_label(j) for j in rows]


@router.get("/{job_id}", response_model=JobInfo)
async def get_job(program_id: str, job_id: str) -> JobInfo:
    job = await jobs.JobRepository().get(job_id)
    if job is None or job.program_id != program_id:
        raise HTTPException(status_code=404, detail="ไม่พบงานนี้")
    return jobs.with_label(job)
```

(The routes reach the repository through `jobs.JobRepository` on purpose, so the one conftest patch covers them.)

`src/curriculum_agent/api/main.py`: import the router and mount it `app.include_router(jobs_routes.router, prefix="/programs/{program_id}/jobs", tags=["jobs"])` beside the others; in `lifespan`, right after the checkpointer setup and before warm-up:

```python
        from curriculum_agent.api.jobs import sweep_orphaned_jobs

        try:
            await sweep_orphaned_jobs()
        except Exception as exc:
            logger.warning(f"jobs: startup sweep failed: {exc}")
```

- [ ] **Step 6: Run tests** — new files, then full suite + ruff + format + mypy. The conftest autouse fixture must not break any existing test.
- [ ] **Step 7: Mutation checks** — (a) remove the `async with lock:` (dedent its body) → `test_two_concurrent_starts_on_one_program_admit_one` fails; (b) drop the `_running_session` check from `program_busy` → `test_a_running_session_blocks_a_job` fails. Restore both.
- [ ] **Step 8: Commit**

```bash
git add src/curriculum_agent/api/jobs.py src/curriculum_agent/api/routes/jobs.py src/curriculum_agent/api/main.py tests/support/jobs.py tests/conftest.py tests/unit/test_job_runner.py tests/unit/test_jobs_router.py
git commit -m "feat(jobs): run stage work in the background, one writer per program

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The three needs routes become jobs

**Files:**
- Modify: `src/curriculum_agent/api/routes/needs.py` (`run_need_pipeline`, `run_skill_extraction`, `run_need_combination`)
- Modify: `tests/unit/test_needs_router.py` and any other test calling these three paths (`grep -rln "needs/run\|skills/run\|combine/run" tests`)
- Test: `tests/unit/test_needs_jobs.py` (new)

**Interfaces:**
- Consumes: `start_job_or_409` (Task 2), fixtures `jobs_store`, `spawned` (Task 2).
- Produces: the three routes answer `202` + `JobInfo`; the job `result` is the old `NeedRunResult` / `SkillRunResult` body. `params` = `{"note_th": <note or None>}`.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_needs_jobs.py`. For each of the three routes, with the repositories and stage `run` functions patched the way `tests/unit/test_needs_router.py` patches them:
  - success path: `POST` → `status_code == 202`, body `kind` is `needs_pipeline` / `skill_extraction` / `need_combination`, `status == "running"`; the stage was **not** called yet (`run` mock not awaited); after `spawned.drain()` the stage was called and `jobs_store.rows[job_id].result` has the old response's keys (`needs`/`skills`, `dropped_ungrounded_count`) and `status == "succeeded"`.
  - precondition path (no evidence for `/run` and `/skills/run`; no skills for `/combine/run`; unknown program → 404): the old status and Thai `detail` come back synchronously and `jobs_store.rows` stays empty.
  - busy path: with a running job already in `jobs_store` for the program, each route answers `409` with a string `detail`.
  - note path: a body `{"note_th": "x"}` reaches the stage state (`designer_note`) when drained, and `params == {"note_th": "x"}`.

```python
# shape of one success test — write the rest in the same style
def test_combine_run_returns_202_and_runs_in_the_background(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    run_needs = AsyncMock(return_value={"needs": [], "dropped_ungrounded_count": 0})
    monkeypatch.setattr("curriculum_agent.stages.need_combination.run", run_needs)
    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=_META))
    monkeypatch.setattr(needs_route.SkillRepository, "list_by_program", AsyncMock(return_value=[_skill()]))

    r = client.post("/programs/cs-test/needs/combine/run")

    assert r.status_code == 202
    assert r.json()["kind"] == "need_combination"
    run_needs.assert_not_awaited()
    spawned.drain()
    run_needs.assert_awaited_once()
    job = jobs_store.rows[r.json()["job_id"]]
    assert job.status == "succeeded"
    assert job.result == {"needs": [], "dropped_ungrounded_count": 0}
```

(`_META`, `_skill()`: build them as `test_needs_router.py` does; read that file first. If the stage modules are imported inside the route functions, patch the attribute on the stage module as shown.)

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** — in each route: keep everything up to and including the precondition checks as is, then move the rest into a local `async def work() -> <OldResult>:` and return `await start_job_or_409(program_id, "<kind>", {"note_th": body.note_th if body else None}, work)`. Change the decorators to `response_model=JobInfo, status_code=202`. Keep the `asyncio.wait_for(..., timeout=300)` calls inside `work`. Keep `NeedRunResult` / `SkillRunResult` classes (they are the documented `result` shapes); say so in a one-line comment on each. Update each route's docstring with one sentence: it answers 202 and the result arrives through `GET /jobs`.

```python
@router.post("/combine/run", response_model=JobInfo, status_code=202)
async def run_need_combination(program_id: str, body: DesignerNoteRequest | None = None) -> JobInfo:
    ...  # docstring + unchanged preconditions, ending with state["extracted_skills"] = ...

    async def work() -> NeedRunResult:
        done = await asyncio.wait_for(run_needs(state), timeout=300)
        return NeedRunResult(
            needs=[Need.model_validate(n) for n in done.get("needs", [])],
            dropped_ungrounded_count=done.get("dropped_ungrounded_count", 0),
        )

    return await start_job_or_409(
        program_id, "need_combination", {"note_th": body.note_th if body else None}, work
    )
```

- [ ] **Step 4: Update the existing tests** that called these routes expecting `200` + body: they now expect `202`, then `spawned.drain()`, then assert on `jobs_store.rows[...]` (`.result`) or on the patched stage mocks. Keep what each test was asserting; change only how it reads the outcome.
- [ ] **Step 5: Run** — new + changed tests, full suite, ruff, format, mypy.
- [ ] **Step 6: Mutation check** — call `await work()` directly and return its result instead of `start_job_or_409` in `run_need_combination` → the 202 test fails. Restore.
- [ ] **Step 7: Commit**

```bash
git add src/curriculum_agent/api/routes/needs.py tests/unit/test_needs_jobs.py <each changed test file>
git commit -m "feat(needs): skill extraction and need combination run as background jobs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The four PLO routes become jobs

**Files:**
- Modify: `src/curriculum_agent/api/routes/plos.py` (`run_plo_synthesis`, `run_plo_report`, `run_plo_review`, `revalidate_plo`)
- Modify: every test calling these paths (`grep -rln "plos/run\|report/run\|review/run\|revalidate" tests` — at least `test_api_plos.py`, `test_plo_report_router.py`, `test_plo_review_run.py`, `test_plo_review_wiring.py`, `test_plo_synthesis_single_flight.py`, `test_plo_synthesis_guard.py`, `test_validation_switch.py`)
- Test: `tests/unit/test_plos_jobs.py` (new)

**Interfaces:**
- Consumes: `start_job_or_409` (Task 2), fixtures `jobs_store`, `spawned`.
- Produces: `POST /plos/run` → kind `plo_synthesis`, params `{"note_th", "run_validation"}`, result `list[PLO]`; `POST /plos/report/run` → `plo_report`, params `{}`, result `PLOReportResponse`; `POST /plos/review/run` → `plo_review`, params `{}`, result `PLOReviewResponse`; `POST /plos/{plo_id}/revalidate` → `plo_revalidate`, params `{"plo_id": plo_id}`, result `PLO`. All `status_code=202`, `response_model=JobInfo`.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_plos_jobs.py`, in the style of Task 3's tests (patch repositories and stage functions the way the existing tests of each route do; read them first):
  - each route: 202 + right `kind` + stage not yet called; after `spawned.drain()`, `succeeded` with the old body's shape in `result` (for `/plos/run`, a list of PLO dicts).
  - preconditions stay synchronous with no job row: `/plos/run` 404 unknown program and 422 no Needs; `/report/run` 422 no PLOs; `/review/run` 422 no PLOs and **503** when `settings.plo_review_provider` is `""`; `/revalidate` 404 unknown program, 404 unknown PLO, 422 Needs gone, 401 without the API key when one is configured.
  - in-work failures become `failed` jobs with the Thai text: `/review/run` whose `fresh_review` returns `None` → `error_th` "ตรวจชุด PLO ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"; `/revalidate` whose `validate_and_build` returns `None` → "ตรวจ SMART ไม่สำเร็จ กรุณาลองใหม่"; `/report/run` whose PLOs vanish during the review → the 422 text.
  - `/plos/run` with `{"run_validation": false}`: after drain the stage state had `run_validation is False`; `params["run_validation"] is False`.
  - busy: each route 409 while a job runs.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** — same transformation as Task 3: preconditions unchanged and synchronous; the rest moves into `work()`; return `await start_job_or_409(...)`. Inside `work`, keep raising `HTTPException` where the old code did (the runner turns `detail` into `error_th`). In `run_plo_synthesis`, the `SynthesisAlreadyRunning` → 409 mapping goes away (the job rule refuses first; if it ever fires inside a job, it is a failed job with its own Thai message) — remove that `try/except` and the now-unused import. In `run_plo_report`, the post-review re-read of PLOs stays inside `work` exactly as it is. Update each docstring with one sentence about 202/`GET /jobs`.
- [ ] **Step 4: Update the existing tests** of these routes to the new contract (202 → `spawned.drain()` → assert on `jobs_store` rows or on the patched stage mocks). Tests that pinned the old synchronous 409 from `SynthesisAlreadyRunning` / `ReviewAlreadyRunning` at the route level now pin the job-level 409 instead (a running job in `jobs_store`); the stage-level single-flight tests that call `plo_synthesis.run` / `plo_review` directly stay as they are.
- [ ] **Step 5: Run** — new + changed tests, full suite, ruff, format, mypy.
- [ ] **Step 6: Mutation check** — move the `settings.plo_review_provider` check into `work()` in `run_plo_review` → the synchronous-503 test fails. Restore.
- [ ] **Step 7: Commit**

```bash
git add src/curriculum_agent/api/routes/plos.py tests/unit/test_plos_jobs.py <each changed test file>
git commit -m "feat(plos): synthesis, report, review and revalidate run as background jobs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Busy guards on the synchronous writers

**Files:**
- Modify: `src/curriculum_agent/api/routes/sessions.py` (`create_session`, `approve_session`)
- Modify: `src/curriculum_agent/api/routes/plos.py` (`create_plo_from_needs`)
- Modify: `src/curriculum_agent/api/routes/programs.py` (`copy_program_route`)
- Modify: `src/curriculum_agent/stages/plo_synthesis.py` (delete `is_synthesis_running`)
- Modify: `tests/unit/test_program_copy_route.py` (its 409 test now uses a running job)
- Test: `tests/unit/test_busy_guards.py` (new)

**Interfaces:**
- Consumes: `program_busy` (Task 2).

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_busy_guards.py`: with a running job placed in `jobs_store` for program `p` (and, separately, with `jobs._running_session` patched to return True):
  - `POST /programs/p/sessions/` → 409, string `detail`, no session row created (patch `SessionRepository.create` and assert not awaited);
  - `POST /programs/p/sessions/{id}/approve` on a suspended session → 409, status not changed (`set_status` not awaited);
  - `POST /programs/p/plos/from-needs` → 409 before any LLM call (patch the synthesis entry and assert not awaited);
  - `POST /programs/p/copy` → 409, `copy_program` not awaited;
  - with nothing running, each proceeds as before (reuse the existing happy-path setups from `test_sessions_router.py`, `test_api_plos.py`, `test_program_copy_route.py`).
  Note: for `approve`, the session being approved is itself `suspended`, so `_running_session` must not count it; patch `_running_session` only in the "a session runs" variant.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** — in each of the four routes, after the existing 404 checks and before any write or LLM call:

```python
    if (reason := await program_busy(program_id)) is not None:
        raise HTTPException(status_code=409, detail=reason)
```

In `copy_program_route`, this replaces the `is_synthesis_running` check and its import; delete `is_synthesis_running` from `plo_synthesis.py` and any test that targeted it. Update the copy route's docstring: the need_combination gap is now closed.
- [ ] **Step 4: Run** — new + changed tests, full suite, ruff, format, mypy.
- [ ] **Step 5: Mutation check** — remove the guard from `approve_session` → its 409 test fails. Restore.
- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/api/routes/sessions.py src/curriculum_agent/api/routes/plos.py src/curriculum_agent/api/routes/programs.py src/curriculum_agent/stages/plo_synthesis.py tests/unit/test_busy_guards.py tests/unit/test_program_copy_route.py <other changed tests>
git commit -m "feat(jobs): synchronous writers wait for a program's running job or session

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Frontend job infrastructure

**Files:**
- Create: `frontend/src/api/jobs.ts`
- Create: `frontend/src/hooks/useProgramJobs.tsx` (hook + `JobsProvider` + `useJobs`)
- Modify: `frontend/src/components/StageLayout.tsx` (wrap the outlet in `JobsProvider`; running-job line)
- Modify: `frontend/src/mock/handlers.ts`, `frontend/src/mock/db.ts` (jobs)

**Interfaces:**
- Produces:
  - `type JobKind = 'needs_pipeline' | 'skill_extraction' | 'need_combination' | 'plo_synthesis' | 'plo_review' | 'plo_report' | 'plo_revalidate'`
  - `interface JobInfo { job_id: string; program_id: string; kind: JobKind; label_th: string; status: 'running' | 'succeeded' | 'failed'; params: Record<string, unknown>; result: unknown; error_th: string | null; created_at: string; finished_at: string | null }`
  - `startJob(path: string, body?: unknown): Promise<JobInfo>` (POST, returns `res.data`; axios throws on 409 as usual)
  - `useJobs(): { running: JobInfo | null; latestOf: (kinds: JobKind[]) => JobInfo | null; refresh: () => Promise<void>; started: (job: JobInfo) => void }`
  - `JOB_PAGE: Record<JobKind, { path: string }>` — `needs_pipeline`/`skill_extraction`/`need_combination` → `/skill-extraction`; `plo_synthesis`/`plo_revalidate` → `/plo-synthesis`; `plo_review`/`plo_report` → `/plo-report`.

- [ ] **Step 1: `api/jobs.ts`** — types above, `startJob`, `listJobs(programId)` (`GET /programs/{id}/jobs`), and `JOB_PAGE`.
- [ ] **Step 2: `hooks/useProgramJobs.tsx`** — `JobsProvider({ programId, children })` holding `jobs: JobInfo[]` for the current program:
  - fetch `listJobs` on mount and whenever `programId` changes; **clear the list immediately on a program change** so program A's job is never shown on program B (Review Focus 5);
  - while `jobs.some(j => j.status === 'running')`, poll every 2000 ms with `setTimeout` (not overlapping requests); stop when nothing runs; `started(job)` inserts the job and restarts polling;
  - a failed poll (network error, 5xx) keeps the last list, does not throw, and retries on the next tick (Review Focus 4); log once with `console.warn`;
  - `latestOf(kinds)` = the newest job (by `created_at`) whose kind is in `kinds`; `running` = the newest running job;
  - `refresh()` refetches now.
  `useJobs()` reads the context (throws a clear error if used outside the provider).
- [ ] **Step 3: `StageLayout`** — wrap the layout's outlet in `<JobsProvider programId={programId}>`; above the outlet, when `running` is not null, one line: `กำลังทำงาน: {running.label_th} · เริ่ม {local time from created_at}` and a link to `JOB_PAGE[running.kind].path` (match the file's existing classes; no new Tailwind palette — read `frontend/src/index.css` component classes and the visual-identity notes in its header).
- [ ] **Step 4: Mock layer** — in `mock/db.ts` add a jobs list; in `mock/handlers.ts`:
  - `GET /programs/:pid/jobs` (+ `?active=true`) and `GET /programs/:pid/jobs/:jid` from the mock db;
  - a helper that, for the seven job POSTs, creates a `running` job, answers **202** with it, and after a short delay (e.g. 1500 ms) applies the handler's existing effect and marks the job `succeeded` with the old response body as `result` (or `failed` with `error_th` where the existing mock answered an error);
  - a second job POST on a program with a running mock job answers 409 with a Thai `detail`.
  Keep mock mode starting and working (read the mock's header comment for how it is switched on).
- [ ] **Step 5: Verify** — `cd frontend && npm run lint && npm run build` (both must pass).
- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/jobs.ts frontend/src/hooks/useProgramJobs.tsx frontend/src/components/StageLayout.tsx frontend/src/mock/handlers.ts frontend/src/mock/db.ts
git commit -m "feat(ui): one polled view of a program's background jobs, shared by every page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Stage pages run through jobs

**Files:**
- Modify: `frontend/src/pages/SkillExtraction.tsx`
- Modify: `frontend/src/pages/PloSynthesis.tsx`
- Modify: `frontend/src/pages/PloReport.tsx`
- Modify (if needed): `frontend/src/components/RunProgress.tsx` (accept `since` already exists — use it)

**Interfaces:**
- Consumes: `startJob`, `useJobs`, `JobInfo`, `JobKind` (Task 6).

Each page follows one pattern:

```tsx
const { running, latestOf, started } = useJobs()
const PAGE_KINDS: JobKind[] = ['skill_extraction', 'need_combination', 'needs_pipeline'] // per page
const mine = running && PAGE_KINDS.includes(running.kind) ? running : null
const last = latestOf(PAGE_KINDS)
const busy = running !== null   // any job of this program blocks every start button

// start
const res = await startJob(`/programs/${programId}/needs/${RUN_PATH[kind]}`, { note_th: note.trim() || null })
started(res)   // 409 → show err.response.data.detail in the existing error slot

// refetch when this page's latest job finishes successfully after our last load
const loadedAt = useRef(0)
useEffect(() => {
  if (last?.status === 'succeeded' && last.finished_at && Date.parse(last.finished_at) > loadedAt.current) {
    fetchAll()  // which sets loadedAt.current = Date.now() when it completes
  }
}, [last?.job_id, last?.status])

// running view: <RunProgress since={Date.parse(mine.created_at)} ... /> while mine !== null
// error view: last?.status === 'failed' → show last.error_th and its finished time
```

- [ ] **Step 1: SkillExtraction** — kinds `needs_pipeline`, `skill_extraction`, `need_combination`. Replace the local `running` state with `mine` (which run is showing comes from `mine.kind`: map `needs_pipeline`→`'all'`, `skill_extraction`→`'skills'`, `need_combination`→`'needs'`). `droppedCount` comes from the latest succeeded job of kind `needs_pipeline`/`skill_extraction` (`result.dropped_ungrounded_count`), not from a response.
- [ ] **Step 2: PloSynthesis** — kinds `plo_synthesis`, `plo_revalidate`. Synthesis start sends `{ note_th, run_validation: agentWillRun }`; the `RunProgress` plan choice (`PLO_SYNTHESIS_PLAN` vs code-only) reads `mine.params.run_validation !== false` instead of the local checkbox, so a page reopened mid-run shows the plan that is actually running. Revalidate becomes `startJob(.../revalidate)`; while a `plo_revalidate` job runs, the card for `mine.params.plo_id` shows its busy state; on success refetch PLOs. The merge (`from-needs`) button stays synchronous but is disabled while `busy`, and a 409 from it shows the detail.
- [ ] **Step 3: PloReport** — kind `plo_report` (and `plo_review` for display). The report run becomes a job; the report view renders from a fresh `GET` load after success, or directly from `last.result` (a `PLOReportResponse`) if the page has no separate GET for the report — read the page and keep whichever source it uses today.
- [ ] **Step 4: Review-focus behaviors to confirm by hand in mock mode** (write what you did in the report): start a run, navigate to another page and back → still running, then the result appears without refresh; refresh mid-run → still running; make the mock fail a job → the error shows and stays after navigating away and back; switch program mid-run → the other program shows no running job.
- [ ] **Step 5: Verify** — `cd frontend && npm run lint && npm run build`.
- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SkillExtraction.tsx frontend/src/pages/PloSynthesis.tsx frontend/src/pages/PloReport.tsx frontend/src/components/RunProgress.tsx
git commit -m "feat(ui): stage pages follow background jobs across navigation and refresh

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Docs

**Files:**
- Modify: `CLAUDE.md` (Common pitfalls)
- Modify: `.claude/skills/curriculum-design-agent/references/data-schemas.md`

- [ ] **Step 1: CLAUDE.md** — add after the program-copy pitfall:

```markdown
- **Long stage runs are jobs, and a program takes one writer at a time.** The
  seven run routes (`/needs/run`, `/needs/skills/run`, `/needs/combine/run`,
  `/plos/run`, `/plos/report/run`, `/plos/review/run`, `/plos/{id}/revalidate`)
  check their preconditions synchronously, then `api/jobs.start_job` records a
  `jobs` row and runs the old body in a background task; they answer 202, and
  the page reads `GET /programs/{id}/jobs`. Holding the request open lost the
  running state on navigation, never reached a refreshed page, and was cut by
  the tunnel at ~100 s. A running job **or a running graph session** blocks
  another job and the synchronous writers (`/sessions/`, `/approve`,
  `/plos/from-needs`, `/copy`) with a Thai 409 — every stage deletes and
  rewrites what the next one reads. Jobs left `running` by a dead process are
  failed at startup (`sweep_orphaned_jobs`), or the program would stay blocked.
  `result` is the body the route used to return. Timestamps go out with
  `+00:00`; the naive ones elsewhere are read by the browser as local time.
  Tests reach none of this for real: conftest swaps `JobRepository` for memory
  and `spawn` for a recorder — `spawned.drain()` runs the bodies.
```

- [ ] **Step 2: data-schemas.md** — a short `JobInfo` / `jobs` entry (fields, kinds, statuses, `result` = old route body, one-writer rule). Edit nothing else under `.claude/skills`.
- [ ] **Step 3: Verify** — `uv run python scripts/dump_prompts.py --check`, `uv run pytest -q`.
- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md .claude/skills/curriculum-design-agent/references/data-schemas.md
git commit -m "docs: background jobs and the one-writer rule

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9 (controller): live migration and check

Done by the controller, not a subagent.

- [ ] `uv run alembic upgrade head` → `d1e2f3a4b5c6`.
- [ ] Rebuild the frontend (`npm run build`), ask the user to restart the backend (or restart it if they agree), then: `POST /programs/program-2-run-1/plos/report/run` → 202; poll `GET /programs/program-2-run-1/jobs/{id}` to `succeeded`; a second POST while it runs → 409.
- [ ] Browser check on `program-2-run-1`: start the report run, navigate away and back, refresh — running state and result both appear without a manual refresh.
