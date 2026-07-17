# tests/unit/test_rate_limit.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from curriculum_agent.api.deps import RateLimiter
from curriculum_agent.api.main import app
from curriculum_agent.models import IscedSuggestion, SuggestedName

client = TestClient(app)


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# --- RateLimiter unit ---


def test_allows_requests_up_to_limit() -> None:
    limiter = RateLimiter(limit=3, time_func=FakeClock())
    for _ in range(3):
        limiter.check("1.2.3.4")  # must not raise


def test_blocks_over_limit_with_retry_after() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=2, time_func=clock)
    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")
    with pytest.raises(HTTPException) as exc_info:
        limiter.check("1.2.3.4")
    assert exc_info.value.status_code == 429
    assert int(exc_info.value.headers["Retry-After"]) >= 1


def test_window_slides_frees_slot() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=1, window_seconds=60.0, time_func=clock)
    limiter.check("1.2.3.4")
    clock.advance(61.0)
    limiter.check("1.2.3.4")  # must not raise


def test_ips_tracked_independently() -> None:
    limiter = RateLimiter(limit=1, time_func=FakeClock())
    limiter.check("1.2.3.4")
    limiter.check("5.6.7.8")  # must not raise


# --- route wiring ---

_SUGGESTION = IscedSuggestion(
    isced_code="0613",
    field_name_en="Software and applications development and analysis",
    field_name_th="การพัฒนาและวิเคราะห์ซอฟต์แวร์และแอปพลิเคชัน",
    rationale_th="เหตุผลทดสอบ",
    suggested_names=[SuggestedName(name_th="วิทยาการคอมพิวเตอร์", name_en="Computer Science")],
)

_REQ = {"name_th": "วิทยาการคอมพิวเตอร์", "name_en": "Computer Science", "field": "CS"}


def test_suggest_isced_returns_429_over_limit(monkeypatch) -> None:
    import curriculum_agent.api.deps as deps

    monkeypatch.setattr(deps, "llm_rate_limiter", RateLimiter(limit=1))
    with patch(
        "curriculum_agent.api.routes.programs.suggest_isced",
        new=AsyncMock(return_value=_SUGGESTION),
    ):
        first = client.post("/programs/suggest-isced", json=_REQ)
        second = client.post("/programs/suggest-isced", json=_REQ)
    assert first.status_code == 200, f"got {first.status_code}: {first.json()}"
    assert second.status_code == 429, f"got {second.status_code}: {second.json()}"
    assert "Retry-After" in second.headers


def test_extract_metadata_shares_the_limiter(monkeypatch) -> None:
    """Both LLM endpoints sit behind the same limiter instance."""
    import curriculum_agent.api.deps as deps

    monkeypatch.setattr(deps, "llm_rate_limiter", RateLimiter(limit=1))
    with patch(
        "curriculum_agent.api.routes.programs.suggest_isced",
        new=AsyncMock(return_value=_SUGGESTION),
    ):
        first = client.post("/programs/suggest-isced", json=_REQ)
    second = client.post(
        "/programs/extract-metadata",
        files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/octet-stream")},
    )
    assert first.status_code == 200
    assert second.status_code == 429, f"got {second.status_code}: {second.json()}"
