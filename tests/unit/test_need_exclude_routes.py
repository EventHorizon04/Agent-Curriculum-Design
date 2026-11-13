"""`POST /needs/{id}/exclude` and `/restore`, and what exclusion does to split,
the checkpoint reload and the manual merge."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import needs as needs_route
from curriculum_agent.data.repositories import NeedRepository
from curriculum_agent.graph import review_needs
from curriculum_agent.models import BloomLevel, JobInfo, KSECCategory, Need
from tests.support.jobs import InMemoryJobs

client = TestClient(app)
_NOW = datetime(2026, 11, 3, 3, 0, 0)
_STAMP = datetime(2026, 11, 3, 4, 0, 0)


def _need(
    nid: str,
    *,
    merged_from: list[str] | None = None,
    merged_into: str | None = None,
    excluded_at: datetime | None = None,
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
        excluded_at=excluded_at,
    )


def _plo(source_need_ids: list[str]) -> SimpleNamespace:
    """Only `source_need_ids` is read by the routes."""
    return SimpleNamespace(source_need_ids=source_need_ids)


class _FakeNeeds:
    """A stored Need table honouring the repository contract: the active read drops
    merged and excluded rows, and `set_excluded` writes the stamp."""

    def __init__(self, rows: list[Need]) -> None:
        self.rows = {n.need_id: n for n in rows}
        self.set_excluded = AsyncMock(side_effect=self._set_excluded)

    async def _set_excluded(self, program_id: str, need_id: str, at: datetime | None) -> Need:
        self.rows[need_id] = self.rows[need_id].model_copy(update={"excluded_at": at})
        return self.rows[need_id]

    async def list_by_program(self, program_id: str) -> list[Need]:
        return list(self.rows.values())

    async def list_active_by_program(self, program_id: str) -> list[Need]:
        return [n for n in self.rows.values() if n.merged_into is None and n.excluded_at is None]


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> _FakeNeeds:
    fake = _FakeNeeds(
        [
            _need("A1"),
            _need("A2"),
            _need("M1", merged_from=["O1", "O2"]),
            _need("O1", merged_into="M1"),
            _need("O2", merged_into="M1"),
            _need("X1", excluded_at=_STAMP),
            _need("XM", merged_from=["O3"], excluded_at=_STAMP),
        ]
    )
    monkeypatch.setattr(needs_route.NeedRepository, "list_by_program", fake.list_by_program)
    monkeypatch.setattr(
        needs_route.NeedRepository, "list_active_by_program", fake.list_active_by_program
    )
    monkeypatch.setattr(needs_route.NeedRepository, "set_excluded", fake.set_excluded)
    monkeypatch.setattr(needs_route.PLORepository, "list_by_program", AsyncMock(return_value=[]))
    return fake


def _active_ids() -> list[str]:
    response = client.get("/programs/p/needs/", params={"active_only": "true"})
    return [n["need_id"] for n in response.json()]


def test_exclude_then_restore(stored: _FakeNeeds, jobs_store: InMemoryJobs) -> None:
    assert "A1" in _active_ids()

    excluded = client.post("/programs/p/needs/A1/exclude")

    assert excluded.status_code == 200
    assert excluded.json()["excluded_at"] is not None
    # Naive UTC, as the column stores it.
    assert stored.set_excluded.await_args.args[2].tzinfo is None
    assert (
        abs((datetime.now(UTC).replace(tzinfo=None) - stored.rows["A1"].excluded_at).seconds) < 60
    )
    assert "A1" not in _active_ids()

    restored = client.post("/programs/p/needs/A1/restore")

    assert restored.status_code == 200
    assert restored.json()["excluded_at"] is None
    assert "A1" in _active_ids()


def test_exclude_busy_409(stored: _FakeNeeds, jobs_store: InMemoryJobs) -> None:
    jobs_store.rows["j1"] = JobInfo(
        job_id="j1", program_id="p", kind="plo_synthesis", status="running", created_at=_NOW
    )

    for route in ("exclude", "restore"):
        response = client.post(f"/programs/p/needs/NOPE/{route}")
        assert response.status_code == 409
        assert "รอให้เสร็จก่อน" in response.json()["detail"]
    stored.set_excluded.assert_not_awaited()


@pytest.mark.parametrize("route", ["exclude", "restore"])
def test_unknown_need_404(stored: _FakeNeeds, jobs_store: InMemoryJobs, route: str) -> None:
    response = client.post(f"/programs/p/needs/NOPE/{route}")

    assert response.status_code == 404
    assert response.json()["detail"] == "ไม่พบ Need นี้"
    stored.set_excluded.assert_not_awaited()


@pytest.mark.parametrize("route", ["exclude", "restore"])
def test_merged_away_need_422(stored: _FakeNeeds, jobs_store: InMemoryJobs, route: str) -> None:
    response = client.post(f"/programs/p/needs/O1/{route}")

    assert response.status_code == 422
    assert response.json()["detail"] == "Need นี้ถูกรวมเข้ากับ Need อื่นแล้ว — ตัด Need ที่รวมแล้วแทน"
    stored.set_excluded.assert_not_awaited()


def test_exclude_already_excluded_422(stored: _FakeNeeds, jobs_store: InMemoryJobs) -> None:
    response = client.post("/programs/p/needs/X1/exclude")

    assert response.status_code == 422
    assert response.json()["detail"] == "Need นี้ถูกตัดออกอยู่แล้ว"
    stored.set_excluded.assert_not_awaited()


def test_restore_not_excluded_422(stored: _FakeNeeds, jobs_store: InMemoryJobs) -> None:
    response = client.post("/programs/p/needs/A1/restore")

    assert response.status_code == 422
    assert response.json()["detail"] == "Need นี้ไม่ได้ถูกตัดออก"
    stored.set_excluded.assert_not_awaited()


def test_exclude_cited_need_409(
    stored: _FakeNeeds, jobs_store: InMemoryJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        needs_route.PLORepository, "list_by_program", AsyncMock(return_value=[_plo(["A1"])])
    )

    response = client.post("/programs/p/needs/A1/exclude")

    assert response.status_code == 409
    assert response.json()["detail"] == "มี PLO อ้างถึง Need นี้ — ลบหรือรวม PLO ก่อนตัด Need"
    stored.set_excluded.assert_not_awaited()


def test_restore_has_no_plo_check(
    stored: _FakeNeeds, jobs_store: InMemoryJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    plos = AsyncMock(return_value=[_plo(["X1"])])
    monkeypatch.setattr(needs_route.PLORepository, "list_by_program", plos)

    response = client.post("/programs/p/needs/X1/restore")

    assert response.status_code == 200
    plos.assert_not_awaited()


def test_split_excluded_merged_need_422(
    stored: _FakeNeeds, jobs_store: InMemoryJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    split = AsyncMock()
    monkeypatch.setattr(needs_route.NeedRepository, "split", split)

    response = client.post("/programs/p/needs/XM/split")

    assert response.status_code == 422
    assert response.json()["detail"] == "คืน Need ก่อนแยก"
    split.assert_not_awaited()


def test_from_needs_refuses_excluded(monkeypatch: pytest.MonkeyPatch) -> None:
    from curriculum_agent.api.routes import plos as plos_route  # noqa: PLC0415
    from tests.unit.test_api_plos import _program  # noqa: PLC0415

    needs = [_need("A1"), _need("X1", excluded_at=_STAMP)]
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=needs))
    monkeypatch.setattr(plos_route.PLORepository, "list_by_program", AsyncMock(return_value=[]))
    replace = AsyncMock(return_value=0)
    monkeypatch.setattr(plos_route.PLORepository, "replace", replace)

    response = client.post("/programs/p/plos/from-needs", json={"need_ids": ["A1", "X1"]})

    assert response.status_code == 422
    assert response.json()["detail"] == "Need นี้ถูกตัดออกแล้ว — คืน Need ก่อนนำมารวมเป็น PLO"
    replace.assert_not_awaited()


async def test_resume_reload_drops_excluded(
    stored: _FakeNeeds, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Need excluded while a session is paused is gone when the checkpoint resumes."""
    monkeypatch.setattr(NeedRepository, "list_active_by_program", stored.list_active_by_program)
    state = {
        "program_id": "p",
        "needs": [_need("A1").model_dump(mode="json"), _need("X1").model_dump(mode="json")],
    }

    with patch("curriculum_agent.graph.interrupt", return_value={"designer_note": "x"}):
        result = await review_needs(state)  # type: ignore[arg-type]

    ids = [n["need_id"] for n in result["needs"]]
    assert "X1" not in ids
    assert "A1" in ids
