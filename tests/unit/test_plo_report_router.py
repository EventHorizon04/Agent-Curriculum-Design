from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from curriculum_agent.api.routes.plos import router
from curriculum_agent.models import PLO, BloomLevel, SMARTCheck

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


def test_report_run_422_when_no_plos():
    with patch("curriculum_agent.api.routes.plos._repo") as mock_repo:
        mock_repo.list_by_program = AsyncMock(return_value=[])
        resp = client.post("/programs/p1/plos/report/run")
    assert resp.status_code == 422


def test_report_run_returns_the_assembled_plos():
    """The stage no longer classifies; the route still returns the PLO set it
    assembled, unchanged, for the designer's checkpoint."""
    plo = _plo()

    async def fake_run(state):
        return {"plos": state["plos"]}

    with (
        patch("curriculum_agent.api.routes.plos._repo") as mock_repo,
        patch("curriculum_agent.stages.plo_report.run", side_effect=fake_run),
    ):
        mock_repo.list_by_program = AsyncMock(return_value=[plo])
        resp = client.post("/programs/p1/plos/report/run")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["plo_id"] == "PLO1"
    assert "classification" not in body[0]
