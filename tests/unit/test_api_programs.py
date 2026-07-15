# tests/unit/test_api_programs.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

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
        mock_repo.upsert = AsyncMock()
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
        mock_repo.upsert = AsyncMock()
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
