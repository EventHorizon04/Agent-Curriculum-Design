"""The jobs table: one row per background stage run (spec: background jobs)."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from curriculum_agent.data.orm import JobTable
from curriculum_agent.data.repositories import (
    JobRepository,
    ProgramRepository,
    SessionRepository,
)
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
    as_json_dict = _job().model_dump(mode="json")
    assert as_json_dict["created_at"].endswith("+00:00")


def test_python_mode_dump_keeps_datetimes_for_the_orm() -> None:
    """The offset is a JSON concern. JobRepository.insert dumps in python mode
    and hands the result to a DateTime column, which rejects an ISO string."""
    dumped = _job(finished_at=datetime(2026, 10, 8, 3, 5, 0)).model_dump()
    assert isinstance(dumped["created_at"], datetime)
    assert isinstance(dumped["finished_at"], datetime)


def test_the_table_has_the_spec_columns() -> None:
    cols = {c.name for c in JobTable.__table__.columns}
    assert cols == {
        "job_id",
        "program_id",
        "kind",
        "status",
        "params",
        "result",
        "error_th",
        "created_at",
        "finished_at",
    }
    assert [
        fk.column.table.name for fk in JobTable.__table__.columns["program_id"].foreign_keys
    ] == ["programs"]


def test_the_model_declares_the_index_the_migration_creates() -> None:
    """`find_running` and the active-only listing filter on (program_id, status);
    a model without it makes `alembic revision --autogenerate` propose dropping it."""
    indexes = {i.name: [c.name for c in i.columns] for i in JobTable.__table__.indexes}
    assert indexes == {"ix_jobs_program_status": ["program_id", "status"]}


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


async def test_insert_stores_a_row_without_the_label() -> None:
    session = AsyncMock()
    session.add = MagicMock()
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_session_ctx(session)
    ):
        await JobRepository().insert(_job(label_th="สรุปรายงาน"))
    row = session.add.call_args.args[0]
    assert isinstance(row, JobTable)
    assert row.job_id == "j1"
    assert isinstance(row.created_at, datetime)
    session.commit.assert_awaited_once()


async def test_finish_on_a_vanished_row_returns_false_without_raising() -> None:
    """The program can be deleted (and its jobs with it) while the task runs."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_session_ctx(session)
    ):
        assert await JobRepository().finish("gone", "succeeded", result={"x": 1}) is False
    session.commit.assert_not_awaited()


async def test_finish_records_status_result_error_and_time() -> None:
    row = JobTable(
        job_id="j1",
        program_id="p",
        kind="plo_report",
        status="running",
        params={},
        created_at=datetime(2026, 10, 8),
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_session_ctx(session)
    ):
        assert await JobRepository().finish("j1", "failed", error_th="ล้มเหลว") is True
    assert row.status == "failed"
    assert row.error_th == "ล้มเหลว"
    assert row.finished_at is not None
    session.commit.assert_awaited_once()


async def test_finish_records_a_result_and_no_error_on_success() -> None:
    row = JobTable(
        job_id="j1",
        program_id="p",
        kind="plo_report",
        status="running",
        params={},
        created_at=datetime(2026, 10, 8),
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_session_ctx(session)
    ):
        assert await JobRepository().finish("j1", "succeeded", result={"x": 1}) is True
    assert row.status == "succeeded"
    assert row.result == {"x": 1}
    assert row.error_th is None
    assert row.finished_at is not None
    session.commit.assert_awaited_once()


async def test_fail_all_running_returns_the_swept_count_and_commits_once() -> None:
    session = AsyncMock()
    executed: list[str] = []

    async def execute(stmt):  # noqa: ANN001, ANN202
        executed.append(str(stmt))
        result = MagicMock()
        result.rowcount = 2
        return result

    session.execute = execute
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_session_ctx(session)
    ):
        assert await JobRepository().fail_all_running("เซิร์ฟเวอร์รีสตาร์ท") == 2
    session.commit.assert_awaited_once()
    assert len(executed) == 1
    assert executed[0].startswith("UPDATE jobs")
    assert "jobs.status" in executed[0]


async def test_session_fail_all_running_filters_on_running_and_commits_once() -> None:
    """The startup sweep's session half: a graph run is an in-process task, so a
    `running` row after a restart has no owner."""
    session = AsyncMock()
    executed: list[tuple[str, dict[str, object]]] = []

    async def execute(stmt):  # noqa: ANN001, ANN202
        compiled = stmt.compile()
        executed.append((str(compiled), compiled.params))
        result = MagicMock()
        result.rowcount = 3
        return result

    session.execute = execute
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_session_ctx(session)
    ):
        assert await SessionRepository().fail_all_running("เซิร์ฟเวอร์รีสตาร์ท") == 3
    session.commit.assert_awaited_once()
    assert len(executed) == 1
    sql, params = executed[0]
    assert sql.startswith("UPDATE sessions SET")
    assert "WHERE sessions.status = " in sql
    assert params["status_1"] == "running"
    assert params["status"] == "failed"
    assert params["suspended_message"] == "เซิร์ฟเวอร์รีสตาร์ท"
    assert isinstance(params["updated_at"], datetime)


async def test_list_by_program_active_only_filters_on_running() -> None:
    session = AsyncMock()
    compiled: list[str] = []

    async def execute(stmt):  # noqa: ANN001, ANN202
        compiled.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        return result

    session.execute = execute
    repo = JobRepository()
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_session_ctx(session)
    ):
        assert await repo.list_by_program("program-2", active_only=True, limit=5) == []
        assert await repo.list_by_program("program-2") == []
    active, everything = compiled
    assert "jobs.status = 'running'" in active
    assert "jobs.program_id = 'program-2'" in active
    assert "ORDER BY jobs.created_at DESC" in active
    assert "LIMIT 5" in active
    assert "'running'" not in everything
    assert "LIMIT 20" in everything


async def test_find_running_returns_the_newest_running_job_or_none() -> None:
    repo = JobRepository()
    running = _job()
    with patch.object(repo, "list_by_program", AsyncMock(return_value=[running])) as listing:
        assert await repo.find_running("program-2") == running
    listing.assert_awaited_once_with("program-2", active_only=True, limit=1)
    with patch.object(repo, "list_by_program", AsyncMock(return_value=[])):
        assert await repo.find_running("program-2") is None


async def test_delete_cascade_deletes_the_programs_jobs() -> None:
    session = AsyncMock()
    executed: list[str] = []

    async def execute(stmt):  # noqa: ANN001, ANN202
        executed.append(str(stmt))
        result = MagicMock()
        result.rowcount = 1
        return result

    session.execute = execute
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_session_ctx(session)
    ):
        await ProgramRepository().delete_cascade("program-2")
    assert any("DELETE FROM jobs" in s for s in executed)
    # jobs reference programs, so they go before the program row
    assert executed.index(next(s for s in executed if "DELETE FROM jobs" in s)) < executed.index(
        next(s for s in executed if "DELETE FROM programs" in s)
    )
