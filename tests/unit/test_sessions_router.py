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
