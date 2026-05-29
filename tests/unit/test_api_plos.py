from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from curriculum_agent.api.main import app

client = TestClient(app)


def test_list_plos_uses_path_not_query() -> None:
    """GET /programs/cs-test/plos/ must not require ?program_id= query param."""
    with patch("curriculum_agent.api.routes.plos._repo") as mock_repo:
        mock_repo.list_by_program = AsyncMock(return_value=[])
        resp = client.get("/programs/cs-test/plos/")
    assert resp.status_code != 422, f"Got 422 — program_id treated as query param: {resp.json()}"
    assert resp.status_code == 200
