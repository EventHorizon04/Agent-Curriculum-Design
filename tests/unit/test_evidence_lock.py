# tests/unit/test_evidence_lock.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import evidence as evidence_module
from curriculum_agent.api.routes.evidence import EVIDENCE_LOCKED_TH, evidence_lock_reason
from curriculum_agent.models import StakeholderEvidence

client = TestClient(app)
BASE = "/programs/cs-2025/evidence"


def _stored(stakeholder_type: str = "employer") -> StakeholderEvidence:
    return StakeholderEvidence(
        evidence_id="ev-1",
        program_id="cs-2025",
        stakeholder_type=stakeholder_type,  # type: ignore[arg-type]
        source_name="เดิม",
        raw_text_th="ข้อความเดิมของหลักฐาน",
    )


_PUT_BODY = {
    "stakeholder_type": "professional_council",
    "source_name": "สภาวิชาชีพ",
    "raw_text_th": "ข้อความใหม่ของหลักฐาน",
}


def _state(
    monkeypatch: pytest.MonkeyPatch,
    *,
    busy: str | None = None,
    skills: bool = False,
    needs: bool = False,
) -> None:
    monkeypatch.setattr(evidence_module, "program_busy", AsyncMock(return_value=busy))
    monkeypatch.setattr(evidence_module.SkillRepository, "has_any", AsyncMock(return_value=skills))
    monkeypatch.setattr(evidence_module.NeedRepository, "has_any", AsyncMock(return_value=needs))


def test_put_edits_before_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(monkeypatch)
    insert = AsyncMock()
    with (
        patch.object(evidence_module._repo, "get", new=AsyncMock(return_value=_stored())),
        patch.object(evidence_module._repo, "bulk_insert", new=insert),
    ):
        resp = client.put(f"{BASE}/ev-1", json=_PUT_BODY)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["evidence_id"] == "ev-1"
    assert body["classification"] == "requirement"
    assert body["raw_text_th"] == "ข้อความใหม่ของหลักฐาน"
    assert insert.await_args.args[0][0].stakeholder_type == "professional_council"


def test_put_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(monkeypatch)
    with patch.object(evidence_module._repo, "get", new=AsyncMock(return_value=None)):
        resp = client.put(f"{BASE}/nope", json=_PUT_BODY)
    assert resp.status_code == 404


def test_put_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    import curriculum_agent.config as cfg

    monkeypatch.setattr(cfg.settings, "api_key", SecretStr("secret-key"))
    assert client.put(f"{BASE}/ev-1", json=_PUT_BODY).status_code == 401


def _each_mutation() -> list[tuple[str, str, dict[str, object] | None]]:
    post_body = _stored().model_dump(mode="json")
    return [
        ("post", f"{BASE}/", post_body),
        ("put", f"{BASE}/ev-1", _PUT_BODY),
        ("delete", f"{BASE}/ev-1", None),
        ("get", f"{BASE}/classify-stream", None),
    ]


@pytest.mark.parametrize(("method", "url", "body"), _each_mutation())
def test_mutation_409_when_skills_exist(
    monkeypatch: pytest.MonkeyPatch, method: str, url: str, body: dict[str, object] | None
) -> None:
    _state(monkeypatch, skills=True)
    resp = client.request(method.upper(), url, json=body)
    assert resp.status_code == 409
    assert resp.json()["detail"] == EVIDENCE_LOCKED_TH


def test_post_with_existing_id_is_also_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(monkeypatch, skills=True)
    insert = AsyncMock()
    with patch.object(evidence_module._repo, "bulk_insert", new=insert):
        resp = client.post(f"{BASE}/", json=_stored().model_dump(mode="json"))
    assert resp.status_code == 409
    insert.assert_not_awaited()


@pytest.mark.parametrize(("method", "url", "body"), _each_mutation())
def test_mutation_409_while_busy(
    monkeypatch: pytest.MonkeyPatch, method: str, url: str, body: dict[str, object] | None
) -> None:
    _state(monkeypatch, busy="หลักสูตรนี้มีงานทดสอบ กำลังทำอยู่ — รอให้เสร็จก่อน")
    resp = client.request(method.upper(), url, json=body)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "หลักสูตรนี้มีงานทดสอบ กำลังทำอยู่ — รอให้เสร็จก่อน"


async def test_lock_with_needs_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(monkeypatch, needs=True)
    assert await evidence_lock_reason("cs-2025") == EVIDENCE_LOCKED_TH


async def test_unlocked_with_no_skills_or_needs(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(monkeypatch)
    assert await evidence_lock_reason("cs-2025") is None


def test_lock_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(monkeypatch)
    assert client.get(f"{BASE}/lock").json() == {"locked": False, "reason_th": None}
    _state(monkeypatch, skills=True)
    assert client.get(f"{BASE}/lock").json() == {"locked": True, "reason_th": EVIDENCE_LOCKED_TH}
