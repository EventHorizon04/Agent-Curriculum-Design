from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from curriculum_agent.api.routes import needs as needs_route
from curriculum_agent.api.routes import plos as plos_route
from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    Need,
    ProgramMetadata,
)


def _need() -> Need:
    return Need(
        need_id="N1",
        program_id="cs-test",
        statement_th="สามารถวิเคราะห์ข้อมูลขนาดใหญ่เพื่อหา insight ทางธุรกิจ",
        ksec_category=KSECCategory.SS,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=["S1"],
        source_evidence_ids=["E1"],
        freq=1,
        demand_score=0.7,
    )


def _skill() -> ExtractedSkill:
    return ExtractedSkill(
        skill_id="S1",
        program_id="cs-test",
        skill_name_th="วิเคราะห์ข้อมูลขนาดใหญ่",
        ksec_category=KSECCategory.SS,
        bloom_level=BloomLevel.ANALYZE,
        evidence_span_th="ต้องวิเคราะห์ข้อมูลขนาดใหญ่ได้",
        source_evidence_id="E1",
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.75,
    )


def _program() -> ProgramMetadata:
    return ProgramMetadata(
        program_id="cs-test",
        name_th="วิทยาการคอมพิวเตอร์",
        name_en="Computer Science",
        field="Computer Science",
        degree_level="bachelor",
        duration_years=4,
        faculty="วิศวกรรมศาสตร์",
        university="มหาวิทยาลัยทดสอบ",
        vision_th="มุ่งผลิตบัณฑิตที่มีความเชี่ยวชาญด้านเทคโนโลยี",
        mission_th="พันธกิจของหลักสูตร",
        philosophy_th="ปรัชญาของหลักสูตร",
        program_goals_th=["เป้าหมายหลักสูตรที่ 1"],
        program_objectives_th=["ผลิตบัณฑิตที่มีทักษะด้านซอฟต์แวร์"],
    )


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(needs_route.router, prefix="/programs/{program_id}/needs")
    app.include_router(plos_route.router, prefix="/programs/{program_id}/plos")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_list_needs_returns_repository_rows(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        needs_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need()])
    )
    response = await client.get("/programs/cs-test/needs/")
    assert response.status_code == 200
    body = response.json()
    assert [n["need_id"] for n in body] == ["N1"]
    assert body[0]["ksec_category"] == "SS"


async def test_list_skills_exposes_span_and_importance(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        needs_route.SkillRepository, "list_by_program", AsyncMock(return_value=[_skill()])
    )
    response = await client.get("/programs/cs-test/needs/skills")
    assert response.status_code == 200
    row = response.json()[0]
    assert row["evidence_span_th"] == "ต้องวิเคราะห์ข้อมูลขนาดใหญ่ได้"
    assert row["importance_score"] == 0.75


async def test_trace_returns_404_for_unknown_need(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        needs_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need()])
    )
    response = await client.get("/programs/cs-test/needs/does-not-exist/trace")
    assert response.status_code == 404


async def test_run_rejects_program_without_evidence(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        needs_route.EvidenceRepository, "list_by_program", AsyncMock(return_value=[])
    )
    response = await client.post("/programs/cs-test/needs/run")
    assert response.status_code == 422
    assert "evidence" in response.json()["detail"]


async def test_from_needs_rejects_fewer_than_two_needs(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    # One Need already becomes a PLO through the normal 1:1 path.
    #
    # N1 is mocked as a real, known Need so that if the min_length=2 guard were
    # dropped, request validation would let this single id through the handler,
    # the need-lookup would find it, and the response would NOT be 422 with a
    # "too_short" body error — proving this 422 comes from the count guard, not
    # from an unrelated failure (e.g. an unknown-need or missing-program error).
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need()])
    )
    response = await client.post("/programs/cs-test/plos/from-needs", json={"need_ids": ["N1"]})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert detail[0]["type"] == "too_short"


async def test_from_needs_rejects_unknown_need_ids(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need()])
    )
    response = await client.post(
        "/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "ghost"]}
    )
    assert response.status_code == 422
    assert "ghost" in response.json()["detail"]


async def test_from_needs_returns_404_for_missing_program(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    # When program does not exist, endpoint returns 404, not 422 blaming the Needs.
    # This test pins the correct check order: program lookup first.
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=None))
    response = await client.post(
        "/programs/unknown-program/plos/from-needs", json={"need_ids": ["N1", "N2"]}
    )
    assert response.status_code == 404
    assert "หลักสูตร" in response.json()["detail"]
