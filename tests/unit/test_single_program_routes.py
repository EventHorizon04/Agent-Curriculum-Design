"""Program create/copy/edit carry `agent_mode`; the mode is fixed at creation."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import programs as programs_route
from curriculum_agent.data.program_copy import build_copy
from curriculum_agent.models import ProgramMetadata
from tests.unit.test_program_copy_build import NOW, _new_uuid_factory, _source

client = TestClient(app)

_EDIT = {
    "field": "การท่องเที่ยว",
    "degree_level": "bachelor",
    "duration_years": 4,
    "faculty": "คณะ",
    "university": "มหาวิทยาลัย",
}


def _stored(mode: str) -> ProgramMetadata:
    return ProgramMetadata(
        program_id="program-2",
        created_at=datetime(2026, 9, 1),
        agent_mode=mode,  # type: ignore[arg-type]
        **_EDIT,
    )


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    state = {"stored": _stored("multi")}

    async def exists(self, program_id: str) -> bool:  # noqa: ANN001
        return program_id == "program-2"

    async def get(self, program_id: str) -> ProgramMetadata:  # noqa: ANN001
        return state["stored"]

    copy = AsyncMock(return_value=True)
    upsert = AsyncMock()
    monkeypatch.setattr(programs_route.ProgramRepository, "exists", exists)
    monkeypatch.setattr(programs_route.ProgramRepository, "get", get)
    monkeypatch.setattr(programs_route.ProgramRepository, "upsert", upsert)
    monkeypatch.setattr(programs_route, "copy_program", copy)
    graph = MagicMock(aupdate_state=AsyncMock())
    monkeypatch.setattr(app.state, "graph", graph, raising=False)
    return {"copy": copy, "upsert": upsert, "state": state}  # type: ignore[dict-item]


def test_put_keeps_the_stored_mode(env) -> None:  # noqa: ANN001
    env["state"]["stored"] = _stored("single")
    r = client.put("/programs/program-2", json=_EDIT)
    assert r.status_code == 200 and r.json()["agent_mode"] == "single"
    assert env["upsert"].await_args.args[0].agent_mode == "single"


def test_put_ignores_a_mode_in_the_body(env) -> None:  # noqa: ANN001
    r = client.put("/programs/program-2", json={**_EDIT, "agent_mode": "single"})
    assert r.status_code == 200 and r.json()["agent_mode"] == "multi"


def test_full_copy_that_changes_mode_is_refused(env) -> None:  # noqa: ANN001
    r = client.post("/programs/program-2/copy", json={"mode": "full", "agent_mode": "single"})
    assert r.status_code == 422
    assert "สำเนาเฉพาะหลักฐาน" in r.json()["detail"]
    env["copy"].assert_not_awaited()


def test_full_copy_naming_the_same_mode_is_accepted(env) -> None:  # noqa: ANN001
    r = client.post("/programs/program-2/copy", json={"mode": "full", "agent_mode": "multi"})
    assert r.status_code == 200
    assert env["copy"].await_args.kwargs["agent_mode"] == "multi"


def test_evidence_only_copy_passes_the_mode_through(env) -> None:  # noqa: ANN001
    r = client.post(
        "/programs/program-2/copy", json={"mode": "evidence_only", "agent_mode": "single"}
    )
    assert r.status_code == 200
    assert env["copy"].await_args.kwargs["agent_mode"] == "single"


def test_copy_without_a_body_passes_no_mode(env) -> None:  # noqa: ANN001
    assert client.post("/programs/program-2/copy").status_code == 200
    assert env["copy"].await_args.kwargs["agent_mode"] is None


def test_evidence_only_copy_can_change_mode() -> None:
    src = _source()
    src.program.agent_mode = "multi"
    copy = build_copy(
        src,
        "p-run-1",
        now=NOW,
        new_uuid=_new_uuid_factory(),
        mode="evidence_only",
        agent_mode="single",
    )
    assert copy.program.agent_mode == "single"
    assert src.program.agent_mode == "multi"


def test_copy_without_agent_mode_keeps_the_source_mode() -> None:
    src = _source()
    src.program.agent_mode = "single"
    copy = build_copy(src, "p-run-1", now=NOW, new_uuid=_new_uuid_factory())
    assert copy.program.agent_mode == "single"
