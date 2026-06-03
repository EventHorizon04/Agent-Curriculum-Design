from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

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
        model="typhoon2:8b",
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
