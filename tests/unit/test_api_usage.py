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


def test_usage_fills_the_thai_label_of_each_job_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime

    from curriculum_agent.models import JobUsage

    started = datetime(2026, 11, 3, tzinfo=UTC)
    summary = UsageSummary(
        total=UsageTotals(calls=2),
        by_job=[
            JobUsage(job_id="a", kind="plo_synthesis", started=started),
            JobUsage(job_id="b", kind="no_such_kind", started=started),
            JobUsage(job_id="c", kind="", started=started),
        ],
    )
    monkeypatch.setattr(programs_route.ProgramRepository, "exists", AsyncMock(return_value=True))
    monkeypatch.setattr(
        programs_route.LLMUsageRepository, "summary", AsyncMock(return_value=summary)
    )
    body = client.get("/programs/cs-test/usage").json()
    labels = [j["label_th"] for j in body["by_job"]]
    assert labels == ["สังเคราะห์ PLO", "", ""]


def test_usage_route_returns_session_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime

    from curriculum_agent.models import SessionUsage

    summary = UsageSummary(
        total=UsageTotals(calls=3),
        by_session=[
            SessionUsage(
                session_id="s1",
                started=datetime(2026, 11, 3, tzinfo=UTC),
                total=UsageTotals(calls=3),
                by_slot=[SlotUsage(slot="extraction", calls=3)],
            )
        ],
    )
    monkeypatch.setattr(programs_route.ProgramRepository, "exists", AsyncMock(return_value=True))
    monkeypatch.setattr(
        programs_route.LLMUsageRepository, "summary", AsyncMock(return_value=summary)
    )
    body = client.get("/programs/cs-test/usage").json()
    assert body["by_job"] == []
    [block] = body["by_session"]
    assert block["session_id"] == "s1" and block["total"]["calls"] == 3
    assert block["started"].endswith("+00:00")
    assert block["by_slot"][0]["slot"] == "extraction"
