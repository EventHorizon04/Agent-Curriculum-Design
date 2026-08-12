# tests/unit/test_evidence_routes.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import evidence as evidence_module

client = TestClient(app)


def test_delete_evidence_success() -> None:
    mock_delete = AsyncMock(return_value=True)
    with patch.object(evidence_module._repo, "delete", new=mock_delete):
        resp = client.delete("/programs/cs-2025/evidence/ev-1")
    assert resp.status_code == 204, f"got {resp.status_code}: {resp.text}"
    mock_delete.assert_awaited_once_with("cs-2025", "ev-1")


def test_delete_evidence_not_found_returns_404() -> None:
    mock_delete = AsyncMock(return_value=False)
    with patch.object(evidence_module._repo, "delete", new=mock_delete):
        resp = client.delete("/programs/cs-2025/evidence/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "ไม่พบหลักฐานนี้"
    mock_delete.assert_awaited_once_with("cs-2025", "does-not-exist")


def test_delete_evidence_wrong_program_returns_404() -> None:
    """Route must still 404 when delete() returns False for ANY reason,
    including the program-mismatch case added by the scoping fix."""
    mock_delete = AsyncMock(return_value=False)
    with patch.object(evidence_module._repo, "delete", new=mock_delete):
        resp = client.delete("/programs/wrong-program/evidence/ev-belongs-to-other-program")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "ไม่พบหลักฐานนี้"
    mock_delete.assert_awaited_once_with("wrong-program", "ev-belongs-to-other-program")


def test_delete_evidence_blocked_by_fk_returns_409() -> None:
    fk_error = IntegrityError("DELETE FROM evidence ...", {}, Exception("FK violation"))
    with patch.object(evidence_module._repo, "delete", new=AsyncMock(side_effect=fk_error)):
        resp = client.delete("/programs/cs-2025/evidence/ev-used-by-skill")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "ลบไม่ได้ — หลักฐานนี้ถูกใช้ในการสกัดทักษะแล้ว"


def test_delete_evidence_requires_api_key_when_configured(monkeypatch) -> None:
    import curriculum_agent.config as cfg

    monkeypatch.setattr(cfg.settings, "api_key", SecretStr("secret-key"))
    resp = client.delete("/programs/cs-2025/evidence/ev-1")
    assert resp.status_code == 401


# A repository-level, live-DB test proving EvidenceRepository.delete's
# `row.program_id != program_id` scoping check (cross-program delete blocked,
# same-program delete succeeds and removes the row) was written and run
# manually against ca-postgres — see the fix report for the script and its
# output. It isn't part of this automated file because this suite mixes
# asyncio_mode="auto" (pytest-asyncio) with @pytest.mark.anyio tests in
# tests/integration; adding a live asyncpg-engine test here passes alone and
# alongside all other unit tests, but the full `uv run pytest` run tears down
# a pooled connection against an already-closed event loop — a pre-existing
# test-infra conflict unrelated to this fix.


async def test_classify_stream_sets_anti_buffering_headers() -> None:
    """Calling the route builds the StreamingResponse without touching the DB —
    the generator body does not run until something iterates it."""
    from curriculum_agent.api.routes.evidence import classify_evidence_stream

    resp = await classify_evidence_stream("cs-1")

    assert resp.media_type == "text/event-stream"
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"
