from __future__ import annotations

import io
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from curriculum_agent.api.main import app
from curriculum_agent.exporters.excel_matrix import MATRIX_HEADERS
from curriculum_agent.models import PLO, BloomLevel, KSECCategory, Need, SMARTCheck

client = TestClient(app)

_MATRIX_URL = "/programs/cs-test/plos/export/matrix.xlsx"


def _need(need_id: str = "N1", ksec: KSECCategory = KSECCategory.S) -> Need:
    return Need(
        need_id=need_id,
        program_id="cs-test",
        statement_th=f"ตลาดต้องการ {need_id}",
        ksec_category=ksec,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=[f"S-{need_id}"],
        source_evidence_ids=[f"E-{need_id}"],
        freq=1,
        demand_score=0.7,
    )


def _plo(plo_id: str = "PLO1", need_ids: list[str] | None = None) -> PLO:
    needs = need_ids or ["N1"]
    return PLO(
        plo_id=plo_id,
        program_id="cs-test",
        statement_th=f"วิเคราะห์งาน {plo_id} เพื่อเสนอแนวทางแก้ปัญหาได้",
        bloom_level=BloomLevel.ANALYZE,
        action_verb_th="วิเคราะห์",
        smart_check=SMARTCheck(
            specific=True, measurable=True, achievable=True, relevant=True, timely=True
        ),
        source_need_ids=needs,
        source_evidence_ids=[f"E-{n}" for n in needs],
        rationale_th="ตรงกับความต้องการของตลาด",
    )


def test_matrix_export_returns_a_readable_workbook() -> None:
    with (
        patch("curriculum_agent.api.routes.plos._repo") as mock_repo,
        patch("curriculum_agent.api.routes.plos.NeedRepository") as mock_needs,
    ):
        mock_repo.list_by_program = AsyncMock(return_value=[_plo()])
        mock_needs.return_value.list_active_by_program = AsyncMock(return_value=[_need()])
        resp = client.get(_MATRIX_URL)

    assert resp.status_code == 200
    sheet = load_workbook(io.BytesIO(resp.content)).active
    assert sheet is not None
    rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    assert rows[0] == list(MATRIX_HEADERS)
    assert rows[1][0] == "PLO1"


def test_matrix_export_sends_a_spreadsheet_content_type() -> None:
    with (
        patch("curriculum_agent.api.routes.plos._repo") as mock_repo,
        patch("curriculum_agent.api.routes.plos.NeedRepository") as mock_needs,
    ):
        mock_repo.list_by_program = AsyncMock(return_value=[_plo()])
        mock_needs.return_value.list_active_by_program = AsyncMock(return_value=[_need()])
        resp = client.get(_MATRIX_URL)

    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_matrix_export_names_the_file_after_the_program() -> None:
    """Without a filename the browser saves it as the endpoint path, so a designer
    exporting two programs cannot tell the downloads apart."""
    with (
        patch("curriculum_agent.api.routes.plos._repo") as mock_repo,
        patch("curriculum_agent.api.routes.plos.NeedRepository") as mock_needs,
    ):
        mock_repo.list_by_program = AsyncMock(return_value=[_plo()])
        mock_needs.return_value.list_active_by_program = AsyncMock(return_value=[_need()])
        resp = client.get(_MATRIX_URL)

    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition
    assert "cs-test" in disposition


def test_matrix_export_resolves_ksec_from_the_needs_repository() -> None:
    """The route must load the Needs, not just the PLOs — the competency domain
    lives on the Need, and a PLO alone cannot supply it."""
    with (
        patch("curriculum_agent.api.routes.plos._repo") as mock_repo,
        patch("curriculum_agent.api.routes.plos.NeedRepository") as mock_needs,
    ):
        mock_repo.list_by_program = AsyncMock(return_value=[_plo()])
        mock_needs.return_value.list_active_by_program = AsyncMock(
            return_value=[_need("N1", KSECCategory.EC)]
        )
        resp = client.get(_MATRIX_URL)

    sheet = load_workbook(io.BytesIO(resp.content)).active
    assert sheet is not None
    rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    assert rows[1][MATRIX_HEADERS.index("หมวดสมรรถนะ")] == "EC"


def test_matrix_export_without_plos_is_422_not_an_empty_file() -> None:
    with patch("curriculum_agent.api.routes.plos._repo") as mock_repo:
        mock_repo.list_by_program = AsyncMock(return_value=[])
        resp = client.get(_MATRIX_URL)

    assert resp.status_code == 422
    assert "PLO" in resp.json()["detail"]


def test_checo_export_reports_not_implemented() -> None:
    """export_checo is a stub that raises NotImplementedError. The route says so
    with a 501 rather than surfacing a 500 the designer cannot act on."""
    resp = client.get("/programs/cs-test/plos/export/checo")

    assert resp.status_code == 501
    assert resp.json()["detail"]


def test_mko2_export_reports_not_implemented() -> None:
    resp = client.get("/programs/cs-test/plos/export/mko2")

    assert resp.status_code == 501
    assert resp.json()["detail"]


def test_export_paths_do_not_shadow_the_plo_id_routes() -> None:
    """`/export/...` must not be captured by a `/{plo_id}/...` route. If it were,
    the trace endpoint would try to look up a PLO literally named "export"."""
    with (
        patch("curriculum_agent.api.routes.plos._repo") as mock_repo,
        patch("curriculum_agent.api.routes.plos.NeedRepository") as mock_needs,
    ):
        mock_repo.list_by_program = AsyncMock(return_value=[_plo()])
        mock_needs.return_value.list_active_by_program = AsyncMock(return_value=[_need()])
        resp = client.get(_MATRIX_URL)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats")
