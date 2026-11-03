# tests/unit/test_evidence_routes.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import evidence as evidence_module

client = TestClient(app)


@pytest.fixture(autouse=True)
def _unlocked_program(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests are about the routes' own behaviour; the lock has its own file."""
    monkeypatch.setattr(evidence_module, "evidence_lock_reason", AsyncMock(return_value=None))


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


def _posted(stakeholder_type: str, classification: str) -> dict[str, object]:
    return {
        "evidence_id": "ev-1",
        "program_id": "cs-2025",
        "stakeholder_type": stakeholder_type,
        "source_name": "แหล่งทดสอบ",
        "raw_text_th": "ข้อความหลักฐานสำหรับการทดสอบเส้นทางบันทึก",
        "classification": classification,
    }


def test_upload_classifies_rather_than_storing_what_the_client_sent() -> None:
    """`classification` is derived from `stakeholder_type` in code, so it is this
    route's output and never its input.

    It used to be stored verbatim, and the field defaults to "general" on the
    model, so every item saved through the form landed as `general` whoever was
    speaking — on the demo programme all three institutional_direction items did.
    """
    mock_insert = AsyncMock()
    with patch.object(evidence_module._repo, "bulk_insert", new=mock_insert):
        resp = client.post(
            "/programs/cs-2025/evidence/",
            json=_posted("institutional_direction", "general"),
        )

    assert resp.status_code == 200, f"got {resp.status_code}: {resp.text}"
    assert resp.json()["classification"] == "requirement"
    stored = mock_insert.await_args.args[0][0]
    assert stored.classification == "requirement"


def test_upload_refuses_a_mandate_the_stakeholder_type_does_not_support() -> None:
    """The correction runs in both directions. A client claiming `requirement`
    for an employer is asserting a mandate the rule does not grant, and storing
    it would buy that Need a place the evidence never earned: `classify_skills`
    propagates `requirement` to the skill, and a Need holding one stops being
    optional."""
    mock_insert = AsyncMock()
    with patch.object(evidence_module._repo, "bulk_insert", new=mock_insert):
        resp = client.post(
            "/programs/cs-2025/evidence/",
            json=_posted("employer", "requirement"),
        )

    assert resp.json()["classification"] == "general"
    assert mock_insert.await_args.args[0][0].classification == "general"
