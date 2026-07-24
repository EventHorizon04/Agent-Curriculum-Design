# tests/unit/test_api_programs.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from curriculum_agent.api.main import app
from curriculum_agent.api.routes.programs import _slugify

client = TestClient(app)

VALID_PROGRAM = {
    "name_th": "วิทยาการคอมพิวเตอร์",
    "name_en": "Computer Science",
    "field": "CS",
    "degree_level": "bachelor",
    "duration_years": 4,
    "faculty": "Engineering",
    "university": "Test University",
    "vision_th": "ผลิตบัณฑิต",
    "mission_th": "พันธกิจ",
    "philosophy_th": "ปรัชญา",
    "program_goals_th": ["เป้าหมาย 1"],
    "program_objectives_th": ["objective 1"],
}


def test_slugify_basic() -> None:
    assert _slugify("Computer Science") == "computer-science"


def test_slugify_strips_symbols_and_case() -> None:
    assert _slugify("  B.Sc. (Data Science)!! ") == "b-sc-data-science"


def test_slugify_empty_fallback() -> None:
    assert _slugify("ภาษาไทยล้วน") == "program"


def test_create_program_requires_api_key_when_configured(monkeypatch) -> None:
    import curriculum_agent.config as cfg

    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")
    resp = client.post("/programs/", json=VALID_PROGRAM)
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.json()}"
    assert resp.json()["detail"] == "API key ไม่ถูกต้องหรือไม่ได้ระบุ"


def test_create_program_generates_slug_id(monkeypatch) -> None:
    import curriculum_agent.config as cfg
    from curriculum_agent.api.main import app as _app

    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})

    with (
        patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls,
        patch.object(_app.state, "graph", mock_graph, create=True),
    ):
        mock_repo = AsyncMock()
        mock_repo.insert = AsyncMock()
        mock_repo.exists = AsyncMock(return_value=False)
        mock_repo_cls.return_value = mock_repo

        resp = client.post(
            "/programs/",
            json=VALID_PROGRAM,
            headers={"X-API-Key": "secret-key"},
        )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
    assert resp.json()["program_id"] == "computer-science"


def test_create_program_collision_appends_suffix(monkeypatch) -> None:
    import curriculum_agent.config as cfg
    from curriculum_agent.api.main import app as _app

    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})

    with (
        patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls,
        patch.object(_app.state, "graph", mock_graph, create=True),
    ):
        mock_repo = AsyncMock()
        mock_repo.insert = AsyncMock()
        # "computer-science" taken, "computer-science-2" free
        mock_repo.exists = AsyncMock(side_effect=[True, False])
        mock_repo_cls.return_value = mock_repo

        resp = client.post(
            "/programs/",
            json=VALID_PROGRAM,
            headers={"X-API-Key": "secret-key"},
        )
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.json()}"
    assert resp.json()["program_id"] == "computer-science-2"


def test_create_program_insert_conflict_retries_with_suffix(monkeypatch) -> None:
    """Concurrent-insert race: exists() said free, but INSERT hits a duplicate
    PK. The route must regenerate (now seeing the winner row) and succeed."""
    import curriculum_agent.config as cfg
    from curriculum_agent.api.main import app as _app

    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})

    with (
        patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls,
        patch.object(_app.state, "graph", mock_graph, create=True),
    ):
        mock_repo = AsyncMock()
        # attempt 1: exists("computer-science") -> False, insert -> conflict
        # attempt 2: exists("computer-science") -> True (winner visible),
        #            exists("computer-science-2") -> False, insert -> ok
        mock_repo.exists = AsyncMock(side_effect=[False, True, False])
        mock_repo.insert = AsyncMock(
            side_effect=[IntegrityError("stmt", {}, Exception("duplicate key")), None]
        )
        mock_repo_cls.return_value = mock_repo

        resp = client.post(
            "/programs/",
            json=VALID_PROGRAM,
            headers={"X-API-Key": "secret-key"},
        )
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.json()}"
    assert resp.json()["program_id"] == "computer-science-2"
    assert mock_repo.insert.await_count == 2


def test_create_program_returns_409_when_attempts_exhausted(monkeypatch) -> None:
    import curriculum_agent.config as cfg
    from curriculum_agent.api.main import app as _app

    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})

    with (
        patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls,
        patch.object(_app.state, "graph", mock_graph, create=True),
    ):
        mock_repo = AsyncMock()
        mock_repo.exists = AsyncMock(return_value=False)
        mock_repo.insert = AsyncMock(
            side_effect=IntegrityError("stmt", {}, Exception("duplicate key"))
        )
        mock_repo_cls.return_value = mock_repo

        resp = client.post(
            "/programs/",
            json=VALID_PROGRAM,
            headers={"X-API-Key": "secret-key"},
        )
    assert resp.status_code == 409, f"got {resp.status_code}: {resp.json()}"
    assert mock_repo.insert.await_count == 5
    mock_graph.ainvoke.assert_not_awaited()


def test_list_programs_empty() -> None:
    with patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.list_all = AsyncMock(return_value=[])
        mock_repo_cls.return_value = mock_repo
        resp = client.get("/programs/")
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.json()}"
    assert resp.json() == []


def test_list_programs_returns_summaries_without_api_key() -> None:
    from datetime import datetime

    from curriculum_agent.models import ProgramSummary

    summaries = [
        ProgramSummary(
            program_id="computer-science",
            name_th="วิทยาการคอมพิวเตอร์",
            name_en="Computer Science",
            degree_level="bachelor",
            created_at=datetime(2026, 7, 2, 9, 0, 0),
            current_stage="plo_synthesis",
            session_status="suspended",
        ),
        ProgramSummary(
            program_id="data-science",
            name_th="วิทยาการข้อมูล",
            name_en="Data Science",
            degree_level="master",
            created_at=datetime(2026, 7, 1, 9, 0, 0),
        ),
    ]
    with patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.list_all = AsyncMock(return_value=summaries)
        mock_repo_cls.return_value = mock_repo
        resp = client.get("/programs/")
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.json()}"
    body = resp.json()
    assert [p["program_id"] for p in body] == ["computer-science", "data-science"]
    assert body[0]["current_stage"] == "plo_synthesis"
    assert body[1]["current_stage"] is None


def test_delete_program_success() -> None:
    with patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.delete_cascade = AsyncMock(return_value=True)
        mock_repo_cls.return_value = mock_repo
        resp = client.delete("/programs/computer-science")
    assert resp.status_code == 204, f"got {resp.status_code}"


def test_delete_program_not_found() -> None:
    with patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.delete_cascade = AsyncMock(return_value=False)
        mock_repo_cls.return_value = mock_repo
        resp = client.delete("/programs/missing-program")
    assert resp.status_code == 404, f"got {resp.status_code}: {resp.json()}"
    assert resp.json()["detail"] == "ไม่พบหลักสูตรนี้"


def test_delete_program_requires_api_key_when_configured(monkeypatch) -> None:
    import curriculum_agent.config as cfg

    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")
    resp = client.delete("/programs/computer-science")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.json()}"
    assert resp.json()["detail"] == "API key ไม่ถูกต้องหรือไม่ได้ระบุ"
