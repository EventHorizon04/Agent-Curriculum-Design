from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from curriculum_agent.data.repositories import SessionRepository
from curriculum_agent.models import SessionInfo


@pytest.fixture
def session_info() -> SessionInfo:
    return SessionInfo(
        session_id="sess-1",
        program_id="prog-1",
        thread_id="prog-1:sess-1",
        status="running",
        current_stage=None,
        suspended_message=None,
        created_at=datetime(2026, 6, 1, 12, 0, 0),
        updated_at=datetime(2026, 6, 1, 12, 0, 0),
    )


async def test_create_returns_session_info(session_info):
    repo = SessionRepository()
    mock_session = AsyncMock()
    # SessionRepository.create calls db.add(...) synchronously; on a bare
    # AsyncMock that call itself returns an unawaited coroutine object
    # (a real RuntimeWarning at test teardown), even though nothing here
    # awaits it. Pin add() to a plain MagicMock so the mock's shape matches
    # the real sync Session.add.
    mock_session.add = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=mock_ctx):
        result = await repo.create(session_info)

    assert result.session_id == "sess-1"
    mock_session.add.assert_called_once()
    mock_session.commit.assert_awaited_once()


async def test_set_status_calls_update():
    repo = SessionRepository()
    mock_session = AsyncMock()
    mock_row = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_row)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=mock_ctx):
        await repo.set_status("sess-1", "completed")

    assert mock_row.status == "completed"
    mock_session.commit.assert_awaited_once()


async def test_set_suspended_sets_stage_and_message():
    repo = SessionRepository()
    mock_session = AsyncMock()
    mock_row = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_row)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=mock_ctx):
        await repo.set_suspended("sess-1", "skill_extraction", "Review clusters")

    assert mock_row.status == "suspended"
    assert mock_row.current_stage == "skill_extraction"
    assert mock_row.suspended_message == "Review clusters"
    mock_session.commit.assert_awaited_once()
