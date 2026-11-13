"""`POST /needs/{id}/split` and the checkpoint reload that follows it."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api import jobs as jobs_mod
from curriculum_agent.api.main import app
from curriculum_agent.api.routes import needs as needs_route
from curriculum_agent.graph import review_needs
from curriculum_agent.models import BloomLevel, JobInfo, KSECCategory, Need
from tests.support.jobs import InMemoryJobs

client = TestClient(app)
# The autouse jobs_store fixture replaces this; keep the real one for the suspended test.
_REAL_RUNNING_SESSION = jobs_mod._running_session
_NOW = datetime(2026, 10, 27, 3, 0, 0)


def _need(
    nid: str, *, merged_from: list[str] | None = None, merged_into: str | None = None
) -> Need:
    return Need(
        need_id=nid,
        program_id="p",
        statement_th=f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=0.7,
        in_field_skill_count=1,
        graduate_capability_skill_count=1,
        merged_from=merged_from or [],
        merged_into=merged_into,
    )


def _plo(source_need_ids: list[str]) -> SimpleNamespace:
    """Only `source_need_ids` is read by the route."""
    return SimpleNamespace(source_need_ids=source_need_ids)


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    merged = _need("M1", merged_from=["O1", "O2"])
    originals = [_need("O1", merged_into="M1"), _need("O2", merged_into="M1")]
    freed = [n.model_copy(update={"merged_into": None}) for n in originals]
    mocks = {
        "list_by_program": AsyncMock(return_value=[merged, *originals]),
        "split": AsyncMock(return_value=freed),
        "list_active_by_program": AsyncMock(return_value=[merged]),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(needs_route.NeedRepository, name, mock)
    monkeypatch.setattr(needs_route.PLORepository, "list_by_program", AsyncMock(return_value=[]))
    return mocks


def test_split_restores_originals_and_deletes_merged(
    stored: dict[str, AsyncMock], jobs_store: InMemoryJobs
) -> None:
    response = client.post("/programs/p/needs/M1/split")

    assert response.status_code == 200
    assert [n["need_id"] for n in response.json()] == ["O1", "O2"]
    assert all(n["merged_into"] is None for n in response.json())
    stored["split"].assert_awaited_once_with("p", "M1")


def test_split_404_for_unknown_need(stored: dict[str, AsyncMock], jobs_store: InMemoryJobs) -> None:
    response = client.post("/programs/p/needs/NOPE/split")

    assert response.status_code == 404
    assert response.json()["detail"] == "ไม่พบ Need นี้"
    stored["split"].assert_not_awaited()


def test_split_refused_for_unmerged_need(
    stored: dict[str, AsyncMock], jobs_store: InMemoryJobs
) -> None:
    response = client.post("/programs/p/needs/O1/split")

    assert response.status_code == 422
    assert response.json()["detail"] == "Need นี้ไม่ได้มาจากการรวม จึงแยกไม่ได้"
    stored["split"].assert_not_awaited()


def test_split_refused_when_plo_cites_it(
    stored: dict[str, AsyncMock], jobs_store: InMemoryJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        needs_route.PLORepository, "list_by_program", AsyncMock(return_value=[_plo(["M1"])])
    )

    response = client.post("/programs/p/needs/M1/split")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Need นี้ถูกใช้สร้าง PLO แล้ว — แยกก่อนสร้าง PLO หรือรันสังเคราะห์ PLO ใหม่หลังแยก"
    )
    stored["split"].assert_not_awaited()


def test_split_refused_while_job_running(
    stored: dict[str, AsyncMock], jobs_store: InMemoryJobs
) -> None:
    jobs_store.rows["j1"] = JobInfo(
        job_id="j1", program_id="p", kind="plo_synthesis", status="running", created_at=_NOW
    )

    response = client.post("/programs/p/needs/M1/split")

    assert response.status_code == 409
    assert "รอให้เสร็จก่อน" in response.json()["detail"]
    stored["split"].assert_not_awaited()


def test_split_busy_409_comes_before_the_need_checks(
    stored: dict[str, AsyncMock], jobs_store: InMemoryJobs
) -> None:
    """The guard is the first thing the route does, so a busy program answers 409
    even for an id that would otherwise be a 404."""
    jobs_store.rows["j1"] = JobInfo(
        job_id="j1", program_id="p", kind="plo_synthesis", status="running", created_at=_NOW
    )

    response = client.post("/programs/p/needs/NOPE/split")

    assert response.status_code == 409
    stored["list_by_program"].assert_not_awaited()


def test_split_not_blocked_by_suspended_session(
    stored: dict[str, AsyncMock], jobs_store: InMemoryJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session paused at a checkpoint is not a running writer."""
    suspended = SimpleNamespace(status="suspended")
    sessions = SimpleNamespace(list_by_program=AsyncMock(return_value=[suspended]))
    monkeypatch.setattr(jobs_mod, "SessionRepository", lambda: sessions)
    monkeypatch.setattr(jobs_mod, "_running_session", _REAL_RUNNING_SESSION)

    response = client.post("/programs/p/needs/M1/split")

    assert response.status_code == 200
    sessions.list_by_program.assert_awaited()
    stored["split"].assert_awaited_once_with("p", "M1")


def test_list_needs_active_only_hides_originals(
    stored: dict[str, AsyncMock], jobs_store: InMemoryJobs
) -> None:
    everything = client.get("/programs/p/needs/")
    active = client.get("/programs/p/needs/", params={"active_only": "true"})

    assert [n["need_id"] for n in everything.json()] == ["M1", "O1", "O2"]
    assert [n["need_id"] for n in active.json()] == ["M1"]


async def test_review_needs_reloads_active_needs_on_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import patch  # noqa: PLC0415

    from curriculum_agent.data.repositories import NeedRepository  # noqa: PLC0415

    restored = [_need("O1"), _need("O2")]
    monkeypatch.setattr(NeedRepository, "list_active_by_program", AsyncMock(return_value=restored))
    state = {
        "program_id": "p",
        "needs": [_need("M1", merged_from=["O1", "O2"]).model_dump(mode="json")],
    }

    with patch("curriculum_agent.graph.interrupt", return_value={"designer_note": "x"}):
        result = await review_needs(state)  # type: ignore[arg-type]

    assert [n["need_id"] for n in result["needs"]] == ["O1", "O2"]
    assert result["designer_note"] == "x"
