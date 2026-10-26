from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import plos as plos_route
from curriculum_agent.models import PLO, BloomLevel, KSECCategory, Need, SMARTCheck
from curriculum_agent.stages import need_dedup
from curriculum_agent.stages import plo_report as pr
from curriculum_agent.stages import plo_synthesis as ps
from tests.unit.test_plo_synthesis_guard import _METADATA, _patch_llm

client = TestClient(app)


def _need(nid: str, *, demand: float = 0.7, merged_into: str | None = None) -> Need:
    return Need(
        need_id=nid,
        program_id="test",
        statement_th=f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=demand,
        in_field_skill_count=1,
        graduate_capability_skill_count=1,
        merged_into=merged_into,
    )


async def test_synthesis_one_slot_per_active_need(monkeypatch: pytest.MonkeyPatch) -> None:
    active = [_need("A1", demand=0.9), _need("A2", demand=0.8), _need("A3", demand=0.7)]
    originals = [_need("O1", demand=0.99, merged_into="A1"), _need("O2", merged_into="A1")]
    _patch_llm(monkeypatch, active)

    state = await ps.run(
        {
            "program_id": "test",
            "metadata": _METADATA,
            "needs": [n.model_dump(mode="json") for n in originals + active],
        }
    )

    assert [p["plo_id"] for p in state["plos"]] == ["PLO1", "PLO2", "PLO3"]
    cited = {nid for p in state["plos"] for nid in p["source_need_ids"]}
    assert cited == {"A1", "A2", "A3"}


async def test_synthesis_loads_only_active_needs_when_entered_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    needs = [_need("A1")]
    _patch_llm(monkeypatch, needs)
    loader = AsyncMock(return_value=needs)
    monkeypatch.setattr(ps.NeedRepository, "list_active_by_program", loader)

    result = await ps.run({"program_id": "test", "metadata": _METADATA})

    loader.assert_awaited_once_with("test")
    assert len(result["plos"]) == 1


async def test_synthesis_makes_no_dedup_call(monkeypatch: pytest.MonkeyPatch) -> None:
    needs = [_need("A1", demand=0.9), _need("A2", demand=0.8)]
    _patch_llm(monkeypatch, needs)
    boom = AsyncMock(side_effect=RuntimeError("dedup must not be called"))
    monkeypatch.setattr(need_dedup, "complete_need_dedup", boom)

    state = await ps.run(
        {
            "program_id": "test",
            "metadata": _METADATA,
            "needs": [n.model_dump(mode="json") for n in needs],
        }
    )

    assert len(state["plos"]) == 2
    boom.assert_not_awaited()


def test_from_needs_refuses_merged_away_need(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit.test_api_plos import _program  # noqa: PLC0415

    needs = [_need("A1"), _need("O1", merged_into="A1")]
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=needs))
    monkeypatch.setattr(plos_route.PLORepository, "list_by_program", AsyncMock(return_value=[]))
    replace = AsyncMock(return_value=0)
    monkeypatch.setattr(plos_route.PLORepository, "replace", replace)

    response = client.post("/programs/test/plos/from-needs", json={"need_ids": ["A1", "O1"]})

    assert response.status_code == 422
    assert response.json()["detail"] == ("Need นี้ถูกรวมเข้ากับ Need อื่นแล้ว — เลือก Need ที่รวมแล้วแทน")
    replace.assert_not_awaited()


async def test_report_unused_needs_exclude_merged_away(monkeypatch: pytest.MonkeyPatch) -> None:
    active = [_need("A1"), _need("A2")]
    # The stub honours the repository contract: active reads drop merged rows.
    monkeypatch.setattr(pr.NeedRepository, "list_active_by_program", AsyncMock(return_value=active))
    monkeypatch.setattr(
        pr.NeedRepository,
        "list_by_program",
        AsyncMock(return_value=[*active, _need("O1", merged_into="A1")]),
    )
    monkeypatch.setattr(pr.PLORepository, "bulk_insert", AsyncMock())
    plo = PLO(
        plo_id="PLO1",
        program_id="test",
        statement_th="วิเคราะห์งาน A1 เพื่อเสนอแนวทางแก้ปัญหาได้",
        bloom_level=BloomLevel.ANALYZE,
        action_verb_th="วิเคราะห์",
        smart_check=SMARTCheck(
            specific=True, measurable=True, achievable=True, relevant=True, timely=True
        ),
        source_need_ids=["A1"],
        source_evidence_ids=["E-A1"],
        rationale_th="ตรงกับความต้องการของตลาด",
    )

    state = await pr.run({"program_id": "test", "plos": [plo.model_dump(mode="json")]})

    assert state["report"]["needs_not_synthesized"] == ["A2"]
