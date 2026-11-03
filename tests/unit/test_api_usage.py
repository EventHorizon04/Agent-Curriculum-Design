from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import programs as programs_route
from curriculum_agent.models import SlotUsage, UsageSummary, UsageTotals

client = TestClient(app)


def test_usage_404_unknown_program(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(programs_route.ProgramRepository, "exists", AsyncMock(return_value=False))
    response = client.get("/programs/nope/usage")
    assert response.status_code == 404
    assert response.json()["detail"] == "Program not found"


def test_usage_returns_repository_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = UsageSummary(
        total=UsageTotals(calls=2, failed_calls=1, prompt_tokens=17),
        by_slot=[SlotUsage(slot="clustering", calls=1)],
    )
    monkeypatch.setattr(programs_route.ProgramRepository, "exists", AsyncMock(return_value=True))
    monkeypatch.setattr(
        programs_route.LLMUsageRepository, "summary", AsyncMock(return_value=summary)
    )
    response = client.get("/programs/cs-test/usage")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"]["calls"] == 2
    assert body["by_slot"][0]["slot"] == "clustering"
    assert body["by_job"] == []
