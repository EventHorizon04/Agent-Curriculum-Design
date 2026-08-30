from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from curriculum_agent.data.repositories import LLMCacheRepository


async def test_get_returns_none_on_miss():
    repo = LLMCacheRepository()
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=ctx):
        result = await repo.get("nonexistent_hash")

    assert result is None


async def test_get_returns_model_and_json_on_hit():
    from curriculum_agent.data.orm import LLMCacheTable

    stored = LLMCacheTable(
        evidence_hash="abc123",
        kind="extraction",
        model="typhoon2:8b",
        contract="aaaa111122223333",
        result_json='{"skills": []}',
        created_at=datetime.utcnow(),
    )
    repo = LLMCacheRepository()
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=stored)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=ctx):
        result = await repo.get("abc123")

    assert result is not None
    model_name, result_json = result
    assert model_name == "typhoon2:8b"
    assert result_json == '{"skills": []}'


async def test_set_records_the_kind_and_contract_that_wrote_the_row():
    """Both are already inside the key, so they change nothing about what gets
    hit. They are columns so that a sweep can name *why* a row is unreachable —
    a hash cannot be asked which prompt produced it."""
    repo = LLMCacheRepository()
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)
    # add() is synchronous on a real AsyncSession; an AsyncMock here returns an
    # un-awaited coroutine and the suite grows a RuntimeWarning.
    mock_session.add = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=ctx):
        await repo.set(
            "abc123",
            "typhoon2:8b",
            '{"skills": []}',
            kind="extraction",
            contract="aaaa111122223333",
        )

    (added,) = mock_session.add.call_args[0]
    assert added.kind == "extraction"
    assert added.contract == "aaaa111122223333"
    assert added.model == "typhoon2:8b"


async def test_overwriting_a_row_updates_its_kind_and_contract():
    """Reachable only when two callers collide on one hash. Leaving the old
    values would make the sweep classify the row against a contract that did not
    produce the payload sitting next to it."""
    from curriculum_agent.data.orm import LLMCacheTable

    existing = LLMCacheTable(
        evidence_hash="abc123",
        kind="extraction",
        model="typhoon2:8b",
        contract="0000dead0000beef",
        result_json="{}",
        created_at=datetime.utcnow(),
    )
    repo = LLMCacheRepository()
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=existing)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=ctx):
        await repo.set(
            "abc123",
            "typhoon2:8b",
            '{"skills": []}',
            kind="extraction",
            contract="aaaa111122223333",
        )

    assert existing.contract == "aaaa111122223333"
    assert existing.result_json == '{"skills": []}'
