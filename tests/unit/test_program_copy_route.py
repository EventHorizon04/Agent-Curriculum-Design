"""POST /programs/{id}/copy and the one-session copy behind it."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError

from curriculum_agent import config as cfg
from curriculum_agent.api.main import app
from curriculum_agent.api.routes import programs as programs_route
from curriculum_agent.data import program_copy as pc
from curriculum_agent.models import JobInfo, ProgramMetadata
from tests.support.jobs import InMemoryJobs

client = TestClient(app)

_COPY = ProgramMetadata(
    program_id="program-2-run-1",
    field="การท่องเที่ยว",
    degree_level="bachelor",
    duration_years=4,
    faculty="คณะ",
    university="มหาวิทยาลัย",
    copied_from="program-2",
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    taken: set[str] = {"program-2"}

    async def exists(self, program_id: str) -> bool:  # noqa: ANN001
        return program_id in taken

    copy = AsyncMock(return_value=True)
    get = AsyncMock(return_value=_COPY)
    monkeypatch.setattr(programs_route.ProgramRepository, "exists", exists)
    monkeypatch.setattr(programs_route.ProgramRepository, "get", get)
    monkeypatch.setattr(programs_route, "copy_program", copy)
    graph = MagicMock(aupdate_state=AsyncMock())
    # Restored by monkeypatch's own teardown, the same thing
    # test_api_programs.py gets from its `with patch.object(...)` blocks.
    monkeypatch.setattr(app.state, "graph", graph, raising=False)
    return {"copy": copy, "get": get, "taken": taken, "graph": graph}  # type: ignore[dict-item]


def test_copy_names_the_first_free_run_number(env) -> None:  # noqa: ANN001
    r = client.post("/programs/program-2/copy")
    assert r.status_code == 200
    assert env["copy"].await_args.args[:2] == ("program-2", "program-2-run-1")

    env["taken"].add("program-2-run-1")
    client.post("/programs/program-2/copy")
    assert env["copy"].await_args.args[:2] == ("program-2", "program-2-run-2")


def test_copy_returns_the_copy_metadata(env) -> None:  # noqa: ANN001
    r = client.post("/programs/program-2/copy")
    assert r.json()["program_id"] == "program-2-run-1"
    assert r.json()["copied_from"] == "program-2"


def test_copy_seeds_the_copy_thread_like_create_does(env) -> None:  # noqa: ANN001
    client.post("/programs/program-2/copy")
    config = env["graph"].aupdate_state.await_args.args[0]
    assert config == {"configurable": {"thread_id": "program-2-run-1"}}


def test_copy_of_an_unknown_program_is_404(env) -> None:  # noqa: ANN001
    assert client.post("/programs/nope/copy").status_code == 404
    env["copy"].assert_not_awaited()


def test_copy_while_a_job_runs_is_409(env, jobs_store: InMemoryJobs) -> None:  # noqa: ANN001
    jobs_store.rows["j1"] = JobInfo(
        job_id="j1",
        program_id="program-2",
        kind="plo_synthesis",
        status="running",
        created_at=datetime(2026, 10, 8, 3, 0),
    )
    response = client.post("/programs/program-2/copy")
    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)
    env["copy"].assert_not_awaited()


def test_copy_retries_with_the_next_id_on_a_collision(env) -> None:  # noqa: ANN001
    calls: list[str] = []

    async def collide_once(source_id: str, new_id: str, **_: object) -> bool:
        calls.append(new_id)
        if len(calls) == 1:
            env["taken"].add(new_id)
            raise IntegrityError("insert", {}, Exception("duplicate"))
        return True

    env["copy"].side_effect = collide_once
    assert client.post("/programs/program-2/copy").status_code == 200
    assert calls == ["program-2-run-1", "program-2-run-2"]


def test_copy_does_not_retry_an_integrity_error_that_is_not_an_id_collision(
    env,  # noqa: ANN001
) -> None:
    """An IntegrityError can come from something other than new_id already
    being taken (e.g. a stale FK inside the copy). Retrying it under the next
    id just repeats the same failure and an eventual 409 would misreport it as
    a name clash; it must propagate instead of being swallowed into a retry."""

    async def always_fails(source_id: str, new_id: str, **_: object) -> bool:
        raise IntegrityError("insert", {}, Exception("not a collision"))

    env["copy"].side_effect = always_fails
    with pytest.raises(IntegrityError):
        client.post("/programs/program-2/copy")
    assert env["copy"].await_count == 1


def test_copy_requires_the_api_key(env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(cfg.settings, "api_key", SecretStr("secret-key"))
    assert client.post("/programs/program-2/copy").status_code == 401


# --------------------------- copy_program (mocked session) ---------------------------


def _session_ctx(session: AsyncMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


async def test_copy_program_adds_every_group_and_commits_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    session.add_all = MagicMock()
    session.add = MagicMock()
    src = MagicMock()
    built = pc.ProgramRows(
        program=MagicMock(),
        evidence=[MagicMock()],
        skills=[MagicMock()],
        needs=[MagicMock()],
        plos=[MagicMock()],
        review=MagicMock(),
    )
    monkeypatch.setattr(pc, "load_rows", AsyncMock(return_value=src))
    monkeypatch.setattr(pc, "build_copy", MagicMock(return_value=built))
    with patch.object(pc, "AsyncSessionLocal", return_value=_session_ctx(session)):
        assert (
            await pc.copy_program("program-2", "program-2-run-1", now=datetime(2026, 10, 6)) is True
        )
    session.commit.assert_awaited_once()
    added = [c.args[0] for c in session.add.call_args_list]
    assert added == [built.program, built.review]
    groups = [c.args[0] for c in session.add_all.call_args_list]
    assert groups == [built.evidence, built.skills, built.skill_groups, built.needs, built.plos]


async def test_copy_program_commits_nothing_when_an_insert_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    session.add_all = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock(
        side_effect=[None, None, None, None, RuntimeError("needs insert failed")]
    )
    built = pc.ProgramRows(
        program=MagicMock(),
        evidence=[],
        skills=[],
        needs=[],
        plos=[],
        review=None,
    )
    monkeypatch.setattr(pc, "load_rows", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(pc, "build_copy", MagicMock(return_value=built))
    with (
        patch.object(pc, "AsyncSessionLocal", return_value=_session_ctx(session)),
        pytest.raises(RuntimeError),
    ):
        await pc.copy_program("program-2", "program-2-run-1")
    session.commit.assert_not_awaited()


async def test_copy_program_sets_repeatable_read_before_loading_the_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """need_combination deletes then inserts in two commits under READ
    COMMITTED, so reading the five tables across separate SELECTs could land
    between them and copy an inconsistent set. The session's isolation level
    has to be raised before the first read, not after."""
    session = AsyncMock()
    session.add_all = MagicMock()
    session.add = MagicMock()
    built = pc.ProgramRows(
        program=MagicMock(), evidence=[], skills=[], needs=[], plos=[], review=None
    )
    load_rows = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(pc, "load_rows", load_rows)
    monkeypatch.setattr(pc, "build_copy", MagicMock(return_value=built))

    manager = MagicMock()
    manager.attach_mock(session.connection, "connection")
    manager.attach_mock(load_rows, "load_rows")

    with patch.object(pc, "AsyncSessionLocal", return_value=_session_ctx(session)):
        await pc.copy_program("program-2", "program-2-run-1", now=datetime(2026, 10, 6))

    assert [c[0] for c in manager.mock_calls] == ["connection", "load_rows"]
    session.connection.assert_awaited_once_with(
        execution_options={"isolation_level": "REPEATABLE READ"}
    )


async def test_copy_program_returns_false_when_the_source_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    monkeypatch.setattr(pc, "load_rows", AsyncMock(return_value=None))
    with patch.object(pc, "AsyncSessionLocal", return_value=_session_ctx(session)):
        assert await pc.copy_program("gone", "gone-run-1") is False
    session.commit.assert_not_awaited()


async def test_copy_route_evidence_only_unlocked(
    env,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point of the mode: the copy's evidence can be edited again."""
    from curriculum_agent.api.routes import evidence as evidence_module

    r = client.post("/programs/program-2/copy", json={"mode": "evidence_only"})
    assert r.status_code == 200
    assert env["copy"].await_args.kwargs["mode"] == "evidence_only"

    # Nothing but evidence is stored for the copy, so the Task 4 lock is open.
    monkeypatch.setattr(evidence_module, "program_busy", AsyncMock(return_value=None))
    monkeypatch.setattr(evidence_module.SkillRepository, "has_any", AsyncMock(return_value=False))
    monkeypatch.setattr(evidence_module.NeedRepository, "has_any", AsyncMock(return_value=False))
    assert await evidence_module.evidence_lock_reason("program-2-run-1") is None


def test_copy_route_without_body_is_full(env) -> None:  # noqa: ANN001
    assert client.post("/programs/program-2/copy").status_code == 200
    assert env["copy"].await_args.kwargs["mode"] == "full"
