# tests/unit/test_api_programs.py
from __future__ import annotations

from fastapi.testclient import TestClient

from curriculum_agent.api.main import app

client = TestClient(app)

VALID_PROGRAM = {
    "program_id": "cs-test",
    "name_th": "วิทยาการคอมพิวเตอร์",
    "name_en": "Computer Science",
    "field": "CS",
    "degree_level": "bachelor",
    "duration_years": 4,
    "faculty": "Engineering",
    "university": "Test University",
    "vision_th": "ผลิตบัณฑิต",
    "mission_th": "พันธกิจของหลักสูตร",
    "philosophy_th": "ปรัชญาของหลักสูตร",
    "program_goals_th": ["เป้าหมายหลักสูตรที่ 1"],
    "program_objectives_th": ["objective 1"],
}


def test_create_program_requires_api_key_when_configured(monkeypatch) -> None:
    """POST /programs/ returns 401 without X-API-Key when api_key is set."""
    import curriculum_agent.config as cfg

    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")

    resp = client.post("/programs/", json=VALID_PROGRAM)
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.json()}"


def test_create_program_passes_with_valid_api_key(monkeypatch) -> None:
    """POST /programs/ accepts request when correct X-API-Key is provided."""
    from unittest.mock import AsyncMock, MagicMock, patch

    import curriculum_agent.config as cfg
    from curriculum_agent.api.main import app as _app

    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})

    # The route reads request.app.state.graph; patch it directly.
    with (
        patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls,
        patch.object(_app.state, "graph", mock_graph, create=True),
    ):
        mock_repo = AsyncMock()
        mock_repo.upsert = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        resp = client.post(
            "/programs/",
            json=VALID_PROGRAM,
            headers={"X-API-Key": "secret-key"},
        )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
