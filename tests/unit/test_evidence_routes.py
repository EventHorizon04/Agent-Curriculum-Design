# tests/unit/test_evidence_routes.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import evidence as evidence_module

client = TestClient(app)


def test_delete_evidence_success() -> None:
    with patch.object(evidence_module._repo, "delete", new=AsyncMock(return_value=True)):
        resp = client.delete("/programs/cs-2025/evidence/ev-1")
    assert resp.status_code == 204, f"got {resp.status_code}: {resp.text}"


def test_delete_evidence_not_found_returns_404() -> None:
    with patch.object(evidence_module._repo, "delete", new=AsyncMock(return_value=False)):
        resp = client.delete("/programs/cs-2025/evidence/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "ไม่พบหลักฐานนี้"


def test_delete_evidence_blocked_by_fk_returns_409() -> None:
    fk_error = IntegrityError("DELETE FROM evidence ...", {}, Exception("FK violation"))
    with patch.object(evidence_module._repo, "delete", new=AsyncMock(side_effect=fk_error)):
        resp = client.delete("/programs/cs-2025/evidence/ev-used-by-skill")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "ลบไม่ได้ — หลักฐานนี้ถูกใช้ในการสกัดทักษะแล้ว"


def test_delete_evidence_requires_api_key_when_configured(monkeypatch) -> None:
    import curriculum_agent.config as cfg

    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")
    resp = client.delete("/programs/cs-2025/evidence/ev-1")
    assert resp.status_code == 401
