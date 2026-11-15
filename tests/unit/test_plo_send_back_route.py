from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import plos as plos_route
from curriculum_agent.stages.plo_send_back import PloSendBackResult
from tests.support.jobs import InMemoryJobs, SpawnRecorder
from tests.unit.test_api_plos import _program

client = TestClient(app)
URL = "/programs/cs-test/plos/send-back"
BODY = {"items": [{"plo_id": "PLO1", "reason_th": "ปรับให้เจาะจง"}]}


def _mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    prog = _program().model_copy(update={"agent_mode": mode})
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=prog))


def test_unknown_program_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=None))
    assert client.post(URL, json=BODY).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"items": []},
        {"items": [{"plo_id": "PLO1", "reason_th": "   "}]},
        {"items": [{"plo_id": "PLO1", "reason_th": "ก"}, {"plo_id": "PLO1", "reason_th": "ข"}]},
    ],
)
def test_bad_bodies_are_422_and_start_no_job(
    body: dict, monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs
) -> None:
    _mode(monkeypatch, "single")
    assert client.post(URL, json=body).status_code == 422
    assert jobs_store.rows == {}


def test_single_program_job_never_reaches_multi_synthesis(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    _mode(monkeypatch, "single")
    synth = AsyncMock(side_effect=AssertionError("multi synthesis reached"))
    monkeypatch.setattr("curriculum_agent.stages.plo_synthesis.synthesize_from_needs", synth)
    single = AsyncMock()
    monkeypatch.setattr(plos_route, "_single_drafter", AsyncMock(return_value=single))
    seen: dict[str, object] = {}

    async def fake_send(program, program_id, items, *, drafter):  # noqa: ANN001
        seen["drafter"] = drafter
        seen["ids"] = [i.plo_id for i in items]
        return PloSendBackResult(outcomes=[])

    monkeypatch.setattr(plos_route, "send_back_plos", fake_send)
    r = client.post(URL, json=BODY)
    assert r.status_code == 202, r.text
    assert r.json()["kind"] == "plo_send_back"
    assert r.json()["params"] == {"plo_ids": ["PLO1"]}
    spawned.drain()
    job = jobs_store.rows[r.json()["job_id"]]
    assert job.status == "succeeded", job.error_th
    assert seen["drafter"] is single
    synth.assert_not_awaited()


def test_multi_program_uses_synthesize_from_needs(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    _mode(monkeypatch, "multi")
    synth = AsyncMock()
    monkeypatch.setattr("curriculum_agent.stages.plo_synthesis.synthesize_from_needs", synth)
    seen: dict[str, object] = {}

    async def fake_send(program, program_id, items, *, drafter):  # noqa: ANN001
        seen["drafter"] = drafter
        return PloSendBackResult(outcomes=[])

    monkeypatch.setattr(plos_route, "send_back_plos", fake_send)
    assert client.post(URL, json=BODY).status_code == 202
    spawned.drain()
    assert seen["drafter"] is synth


def test_busy_program_is_409(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    _mode(monkeypatch, "single")
    monkeypatch.setattr(plos_route, "_single_drafter", AsyncMock())
    assert client.post(URL, json=BODY).status_code == 202
    assert client.post(URL, json=BODY).status_code == 409
