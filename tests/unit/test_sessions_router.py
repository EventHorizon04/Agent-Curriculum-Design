from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from curriculum_agent.api.routes.sessions import router
from curriculum_agent.models import SessionInfo

_NOW = datetime(2026, 6, 1, 12, 0, 0)

_SESS = SessionInfo(
    session_id="s1",
    program_id="p1",
    thread_id="p1:s1",
    status="suspended",
    current_stage="skill_extraction",
    suspended_message="Review clusters",
    created_at=_NOW,
    updated_at=_NOW,
)

app = FastAPI()
app.include_router(router, prefix="/programs/{program_id}/sessions")
app.state.graph = MagicMock()


def _mock_repos(sess_repo_mock):
    return patch(
        "curriculum_agent.api.routes.sessions.SessionRepository", return_value=sess_repo_mock
    )


def _mock_start_repos(*, evidence: list[object], program: object = object()):
    """The two reads POST /sessions makes before it starts anything."""
    prog_repo = AsyncMock()
    prog_repo.get = AsyncMock(return_value=program)
    ev_repo = AsyncMock()
    ev_repo.list_by_program = AsyncMock(return_value=evidence)
    return (
        patch("curriculum_agent.api.routes.sessions.ProgramRepository", return_value=prog_repo),
        patch("curriculum_agent.api.routes.sessions.EvidenceRepository", return_value=ev_repo),
    )


def test_starting_a_run_with_no_evidence_is_refused_before_a_session_exists():
    """stakeholder_needs raises on an empty corpus, so this run cannot succeed.

    Finding that out by starting the graph costs a session row recording a
    failure the caller could have been told about outright, plus a checkpoint
    thread that then has to be cleaned up. The per-stage REST routes answer 422
    on the same condition; this is the graph path agreeing with them.
    """
    sess_repo = AsyncMock()
    sess_repo.create = AsyncMock()
    prog_patch, ev_patch = _mock_start_repos(evidence=[])

    with prog_patch, ev_patch, _mock_repos(sess_repo):
        client = TestClient(app)
        resp = client.post("/programs/p1/sessions/")

    assert resp.status_code == 422
    assert "evidence" in resp.json()["detail"]
    sess_repo.create.assert_not_awaited()


def test_get_session_returns_session_info():
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=_SESS)
    with _mock_repos(repo):
        client = TestClient(app)
        resp = client.get("/programs/p1/sessions/s1")
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "s1"


def test_reject_sets_status():
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=_SESS)
    repo.set_status = AsyncMock()
    with _mock_repos(repo):
        client = TestClient(app)
        resp = client.post("/programs/p1/sessions/s1/reject")
    assert resp.status_code == 200
    repo.set_status.assert_awaited_once_with("s1", "rejected")


def test_reject_discards_the_checkpoint_thread():
    """A rejected session is terminal — retrying means a new session under a new
    thread_id, so nothing will ever resume this thread. Left alone it stays
    suspended for the life of the database holding a full copy of the program's
    evidence, skills and Needs. The session row stays; the checkpoint does not."""
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=_SESS)
    repo.set_status = AsyncMock()
    app.state.graph.checkpointer.adelete_thread = AsyncMock()

    with _mock_repos(repo):
        client = TestClient(app)
        resp = client.post("/programs/p1/sessions/s1/reject")

    assert resp.status_code == 200
    app.state.graph.checkpointer.adelete_thread.assert_awaited_once_with("p1:s1")


def test_reject_still_succeeds_when_the_checkpoint_delete_fails():
    """The status change has already committed. Failing the request here would
    leave the designer with a session that reads as rejected but answered 500."""
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=_SESS)
    repo.set_status = AsyncMock()
    app.state.graph.checkpointer.adelete_thread = AsyncMock(side_effect=RuntimeError("down"))

    with _mock_repos(repo):
        client = TestClient(app)
        resp = client.post("/programs/p1/sessions/s1/reject")

    assert resp.status_code == 200
    assert resp.json()["session_id"] == "s1"


def test_reject_leaves_a_non_suspended_session_thread_alone():
    running = _SESS.model_copy(update={"status": "running"})
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=running)
    app.state.graph.checkpointer.adelete_thread = AsyncMock()

    with _mock_repos(repo):
        client = TestClient(app)
        resp = client.post("/programs/p1/sessions/s1/reject")

    assert resp.status_code == 409
    app.state.graph.checkpointer.adelete_thread.assert_not_awaited()


def test_approve_requires_suspended_status():
    running_sess = _SESS.model_copy(update={"status": "running"})
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=running_sess)
    with _mock_repos(repo):
        client = TestClient(app)
        resp = client.post("/programs/p1/sessions/s1/approve")
    assert resp.status_code == 409


def test_list_sessions_returns_list():
    repo = AsyncMock()
    repo.list_by_program = AsyncMock(return_value=[_SESS])
    with _mock_repos(repo):
        client = TestClient(app)
        resp = client.get("/programs/p1/sessions")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_a_failed_graph_run_stores_the_reason():
    """The reason a run died reaches the session row, not just the log.

    `_run_graph` catches everything a stage raises — which is now where a missing
    precondition is reported — and used to record only the word "failed".
    """
    from curriculum_agent.api.routes.sessions import _run_graph

    graph = MagicMock()
    graph.ainvoke = AsyncMock(
        side_effect=ValueError("ไม่มี evidence สำหรับโปรแกรมนี้ กรุณาเพิ่ม evidence ก่อน")
    )
    repo = MagicMock()
    repo.set_status = AsyncMock()

    with patch("curriculum_agent.api.routes.sessions.SessionRepository", return_value=repo):
        await _run_graph(graph, {"configurable": {"thread_id": "t"}}, {}, "sess-1")

    repo.set_status.assert_awaited_once()
    args, kwargs = repo.set_status.await_args
    assert args[:2] == ("sess-1", "failed")
    assert "evidence" in (kwargs.get("message") or args[2])


def test_delete_removes_the_session_row():
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=_SESS)
    repo.delete = AsyncMock(return_value=True)
    app.state.graph.checkpointer.adelete_thread = AsyncMock()

    with _mock_repos(repo):
        client = TestClient(app)
        resp = client.delete("/programs/p1/sessions/s1")

    assert resp.status_code == 204
    repo.delete.assert_awaited_once_with("p1", "s1")


def test_delete_drops_the_checkpoint_thread_with_it():
    """The row is the only place the thread id is written down.

    LangGraph's checkpoints live in their own schema with no foreign key back to
    the session table, so deleting the row cannot reach them — it only makes them
    unnameable, while they go on holding a full copy of that run's evidence,
    skills, Needs and PLOs. Dropping the thread has to happen here or nowhere.
    """
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=_SESS)
    repo.delete = AsyncMock(return_value=True)
    app.state.graph.checkpointer.adelete_thread = AsyncMock()

    with _mock_repos(repo):
        client = TestClient(app)
        resp = client.delete("/programs/p1/sessions/s1")

    assert resp.status_code == 204
    app.state.graph.checkpointer.adelete_thread.assert_awaited_once_with("p1:s1")


def test_delete_refuses_a_running_session_and_touches_nothing():
    """Deleting a run in flight does not stop it.

    The graph task keeps executing in the background and keeps writing — stage
    output to the repositories, status back to this row. All the delete removes
    is the record that would have shown the run happening, and the message it
    would have failed with.
    """
    running = _SESS.model_copy(update={"status": "running"})
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=running)
    repo.delete = AsyncMock()
    app.state.graph.checkpointer.adelete_thread = AsyncMock()

    with _mock_repos(repo):
        client = TestClient(app)
        resp = client.delete("/programs/p1/sessions/s1")

    assert resp.status_code == 409
    repo.delete.assert_not_awaited()
    app.state.graph.checkpointer.adelete_thread.assert_not_awaited()


def test_delete_of_another_programs_session_is_a_404():
    """Scoped by program like every other session route: a caller must not learn
    that an id exists under a program they did not ask about."""
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=_SESS)
    repo.delete = AsyncMock()
    app.state.graph.checkpointer.adelete_thread = AsyncMock()

    with _mock_repos(repo):
        client = TestClient(app)
        resp = client.delete("/programs/other/sessions/s1")

    assert resp.status_code == 404
    repo.delete.assert_not_awaited()
    app.state.graph.checkpointer.adelete_thread.assert_not_awaited()
