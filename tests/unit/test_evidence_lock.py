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
    monkeypatch.setattr(evidence_module._repo, "program_of", AsyncMock(return_value=None))


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


def test_put_clears_rationale_and_english_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(monkeypatch)
    old = _stored().model_copy(
        update={"classification_rationale_th": "เหตุผลเดิม", "raw_text_en": "old text"}
    )
    with (
        patch.object(evidence_module._repo, "get", new=AsyncMock(return_value=old)),
        patch.object(evidence_module._repo, "bulk_insert", new=AsyncMock()),
    ):
        body = client.put(f"{BASE}/ev-1", json=_PUT_BODY).json()
    assert body["classification_rationale_th"] is None
    assert body["raw_text_en"] is None


async def test_mutations_wait_for_the_program_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Check and write share program_lock; without it a job could start between them."""
    import asyncio

    from curriculum_agent.api.jobs import program_lock

    _state(monkeypatch)
    insert = AsyncMock()
    delete = AsyncMock(return_value=True)
    monkeypatch.setattr(evidence_module._repo, "bulk_insert", insert)
    monkeypatch.setattr(evidence_module._repo, "get", AsyncMock(return_value=_stored()))
    monkeypatch.setattr(evidence_module._repo, "delete", delete)
    update = evidence_module.EvidenceUpdate(
        stakeholder_type="professional_council", source_name="x", raw_text_th="y"
    )
    calls = [
        lambda: evidence_module.upload_evidence("cs-2025", _stored()),
        lambda: evidence_module.update_evidence("cs-2025", "ev-1", update),
        lambda: evidence_module.delete_evidence("cs-2025", "ev-1"),
    ]
    for call in calls:
        insert.reset_mock()
        delete.reset_mock()
        async with program_lock("cs-2025"):
            task = asyncio.create_task(call())
            await asyncio.sleep(0.05)
            assert not task.done()
            insert.assert_not_awaited()
            delete.assert_not_awaited()
        await task


async def test_classify_stream_registers_as_writer_while_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from curriculum_agent.api.jobs import program_busy

    monkeypatch.setattr(evidence_module, "program_busy", AsyncMock(return_value=None))
    monkeypatch.setattr(evidence_module.SkillRepository, "has_any", AsyncMock(return_value=False))
    monkeypatch.setattr(evidence_module.NeedRepository, "has_any", AsyncMock(return_value=False))
    monkeypatch.setattr(
        evidence_module.EvidenceRepository, "list_by_program", AsyncMock(return_value=[_stored()])
    )
    monkeypatch.setattr(evidence_module.EvidenceRepository, "bulk_insert", AsyncMock())
    resp = await evidence_module.classify_evidence_stream("cs-busy")
    it = resp.body_iterator.__aiter__()
    await it.__anext__()  # "started": registered now
    assert await program_busy("cs-busy") is not None
    async for _ in it:
        pass
    assert await program_busy("cs-busy") is None


def test_post_refuses_a_body_for_another_program(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lock is the path program's, so the body may not name a different one."""
    _state(monkeypatch)
    insert = AsyncMock()
    body = _stored().model_copy(update={"program_id": "locked-prog"}).model_dump(mode="json")
    with patch.object(evidence_module._repo, "bulk_insert", new=insert):
        resp = client.post(f"{BASE}/", json=body)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "program_id ใน body ไม่ตรงกับหลักสูตรที่ระบุ"
    insert.assert_not_awaited()


def test_post_refuses_an_evidence_id_owned_by_another_program(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`evidence_id` is global and bulk_insert upserts by it, so a POST to an
    unlocked program could otherwise rewrite a locked program's row."""
    _state(monkeypatch)
    monkeypatch.setattr(evidence_module._repo, "program_of", AsyncMock(return_value="locked-prog"))
    insert = AsyncMock()
    with patch.object(evidence_module._repo, "bulk_insert", new=insert):
        resp = client.post(f"{BASE}/", json=_stored().model_dump(mode="json"))
    assert resp.status_code == 409
    assert resp.json()["detail"] == "evidence_id นี้เป็นของหลักสูตรอื่น"
    insert.assert_not_awaited()


def test_post_still_upserts_an_id_of_the_same_program(monkeypatch: pytest.MonkeyPatch) -> None:
    _state(monkeypatch)
    monkeypatch.setattr(evidence_module._repo, "program_of", AsyncMock(return_value="cs-2025"))
    insert = AsyncMock()
    body = _stored().model_copy(update={"raw_text_th": "ข้อความที่แก้แล้ว"}).model_dump(mode="json")
    with patch.object(evidence_module._repo, "bulk_insert", new=insert):
        resp = client.post(f"{BASE}/", json=body)
    assert resp.status_code == 200, resp.text
    stored = insert.await_args.args[0][0]
    assert stored.evidence_id == "ev-1"
    assert stored.raw_text_th == "ข้อความที่แก้แล้ว"
