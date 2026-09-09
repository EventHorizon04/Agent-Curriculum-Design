from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from curriculum_agent.api.routes.plos import router
from curriculum_agent.models import PLO, BloomLevel, Need, SMARTCheck

app = FastAPI()
app.include_router(router, prefix="/programs/{program_id}/plos")
client = TestClient(app)

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)


def _plo(**overrides) -> PLO:
    base = dict(
        plo_id="PLO1",
        program_id="p1",
        statement_th="ออกแบบและพัฒนาระบบซอฟต์แวร์",
        bloom_level=BloomLevel.CREATE,
        action_verb_th="ออกแบบ",
        smart_check=_SMART,
        source_need_ids=["c1"],
        source_evidence_ids=["e1"],
        rationale_th="เหตุผล",
    )
    base.update(overrides)
    return PLO(**base)


def _need(**overrides) -> Need:
    base = dict(
        need_id="c1",
        program_id="p1",
        statement_th="ตลาดต้องการความสามารถนี้",
        ksec_category="S",
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=["s1"],
        source_evidence_ids=["e1"],
        freq=1,
        demand_score=0.5,
    )
    base.update(overrides)
    return Need(**base)


def test_report_run_422_when_no_plos():
    with patch("curriculum_agent.api.routes.plos._repo") as mock_repo:
        mock_repo.list_by_program = AsyncMock(return_value=[])
        resp = client.post("/programs/p1/plos/report/run")
    assert resp.status_code == 422


def test_report_run_returns_the_full_report_payload():
    """The route used to return a bare `list[PLO]`, discarding the `counts` and
    `needs_by_id` plo_report.py assembles alongside it — the report's only
    consumers (a future drill-down page) had no route to read them from. This
    pins the route surfacing the whole `state["report"]` shape instead."""
    plo = _plo()
    need = _need()

    with (
        patch("curriculum_agent.api.routes.plos._repo") as mock_repo,
        patch(
            "curriculum_agent.stages.plo_report.NeedRepository.list_by_program",
            new=AsyncMock(return_value=[need]),
        ),
        patch(
            "curriculum_agent.stages.plo_report.PLORepository.bulk_insert",
            new=AsyncMock(),
        ),
    ):
        mock_repo.list_by_program = AsyncMock(return_value=[plo])
        resp = client.post("/programs/p1/plos/report/run")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"plos", "counts", "needs_by_id", "needs_not_synthesized"}

    assert len(body["plos"]) == 1
    assert body["plos"][0]["plo_id"] == "PLO1"
    assert "classification" not in body["plos"][0]

    # counts must agree with the plos list it describes: one PLO, not optional,
    # not escalated.
    assert body["counts"] == {
        "total": 1,
        "core": 1,
        "optional": 0,
        "escalated": 0,
        "stale": 0,
        "code_only": 0,
        "needs_not_synthesized": 0,
    }

    assert body["needs_by_id"]["c1"]["need_id"] == "c1"
    assert body["needs_by_id"]["c1"]["ksec_category"] == "S"
