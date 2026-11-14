from __future__ import annotations

from typing import Any

import pytest

from curriculum_agent.data import repositories
from curriculum_agent.data.repositories import PLORepository


class _Result:
    rowcount = 3


class _Session:
    def __init__(self) -> None:
        self.executed: list[Any] = []
        self.added: list[Any] = []
        self.commits = 0

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, stmt: Any) -> _Result:
        self.executed.append(stmt)
        return _Result()

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.commits += 1


async def test_replace_by_program_is_one_session_and_one_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    session = _Session()
    sessions: list[_Session] = []

    def factory() -> _Session:
        sessions.append(session)
        return session

    monkeypatch.setattr(repositories, "AsyncSessionLocal", factory)
    monkeypatch.setattr(repositories, "_plo_row_data", lambda plo: {"program_id": "p", "plo_id": plo})
    removed = await PLORepository().replace_by_program("p", ["a", "b"])  # type: ignore[list-item]
    assert removed == 3 and len(sessions) == 1 and session.commits == 1
    # superseded, feedback actions, report, PLOs — deleted before the inserts
    assert len(session.executed) == 4 and len(session.added) == 2
