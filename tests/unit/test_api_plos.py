from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import plos as plos_route
from curriculum_agent.models import (
    PLO,
    BloomLevel,
    KSECCategory,
    Need,
    ProgramMetadata,
    SMARTCheck,
)

client = TestClient(app)


def test_list_plos_uses_path_not_query() -> None:
    """GET /programs/cs-test/plos/ must not require ?program_id= query param."""
    with patch("curriculum_agent.api.routes.plos._repo") as mock_repo:
        mock_repo.list_by_program = AsyncMock(return_value=[])
        resp = client.get("/programs/cs-test/plos/")
    assert resp.status_code != 422, f"Got 422 — program_id treated as query param: {resp.json()}"
    assert resp.status_code == 200


# --------------------------- merge route, scope guard ---------------------------
#
# POST /plos/from-needs is the one path by which an out-of-scope Need can still
# reach a PLO, and that is deliberate rather than an oversight: it is the whole
# override mechanism, which is why no separate override control exists. These
# tests pin that the route acquires no opinion about scope, and that the count
# policy it already enforced is untouched.


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
        program_goals_th=["เป้าหมายหลักสูตรที่ 1"],
        program_objectives_th=["ผลิตบัณฑิตที่มีทักษะด้านซอฟต์แวร์"],
    )


def _need(nid: str, *, in_scope: bool = True) -> Need:
    return Need(
        need_id=nid,
        program_id="cs-test",
        statement_th=f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=0.7,
        in_field_skill_count=1 if in_scope else 0,
        graduate_capability_skill_count=1 if in_scope else 0,
    )


def _plo(plo_id: str, need_ids: list[str]) -> PLO:
    return PLO(
        plo_id=plo_id,
        program_id="cs-test",
        statement_th="ออกแบบและพัฒนาซอฟต์แวร์ที่มีคุณภาพได้",
        bloom_level=BloomLevel.CREATE,
        action_verb_th="ออกแบบ",
        smart_check=SMARTCheck(
            specific=True, measurable=True, achievable=True, relevant=True, timely=True
        ),
        source_need_ids=need_ids,
        source_evidence_ids=[f"E-{nid}" for nid in need_ids],
        rationale_th="ทักษะหลักที่นายจ้างต้องการ",
    )


@pytest.fixture
def merge_env(monkeypatch: pytest.MonkeyPatch) -> Callable[..., PLO]:
    """Stub everything the merge route reaches, and hand back the PLO synthesis
    is rigged to return so a test can assert on what came out."""

    def _install(needs: list[Need], existing: list[PLO]) -> PLO:
        merged = _plo("PLO1", [n.need_id for n in needs])
        monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
        monkeypatch.setattr(
            plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=needs)
        )
        # On the class, never on the module-level `_repo` instance. Patching the
        # instance leaves a bound method sitting in its __dict__ once monkeypatch
        # restores it, and that shadow survives the test: every later test that
        # patches the class method still reaches the real one through `_repo`, and
        # the suite starts trying to open a Postgres connection.
        monkeypatch.setattr(
            plos_route.PLORepository, "list_by_program", AsyncMock(return_value=existing)
        )
        monkeypatch.setattr(plos_route.PLORepository, "replace", AsyncMock(return_value=0))
        monkeypatch.setattr(
            "curriculum_agent.stages.plo_synthesis.synthesize_from_needs",
            AsyncMock(return_value=merged),
        )
        return merged

    return _install


def test_merging_out_of_scope_needs_is_allowed_rather_than_refused(
    merge_env: Callable[..., PLO],
) -> None:
    """Not a 422.

    Three reasons, in order of weight. The graduate-capability flag was never
    observed on its own — every Need carrying it failed the field axis too — so
    refusing on it would refuse exactly what the field axis lets through, one
    policy contradicting itself inside a single request. A PLO of the wrong shape
    already has the SMART gate waiting for it, which judges the sentence rather
    than a flag set two stages earlier. And the flag catches barely half of what it
    should, so a 422 built on it blocks correct work with no way around it.
    """
    merge_env([_need("X1", in_scope=False), _need("X2", in_scope=False)], [])

    with patch.object(plos_route, "logger"):
        response = client.post("/programs/cs-test/plos/from-needs", json={"need_ids": ["X1", "X2"]})

    assert response.status_code == 200, response.text
    assert response.json()["plo_id"] == "PLO1"


def test_the_merge_response_says_nothing_about_scope(merge_env: Callable[..., PLO]) -> None:
    """A response that argues back is second-guessing a decision the designer has
    already made. The record of it belongs in the log instead."""
    merge_env([_need("X1", in_scope=False), _need("X2", in_scope=False)], [])

    with patch.object(plos_route, "logger"):
        response = client.post("/programs/cs-test/plos/from-needs", json={"need_ids": ["X1", "X2"]})

    assert "ขอบเขต" not in response.text
    assert "out-of-scope" not in response.text


def test_merging_out_of_scope_needs_leaves_a_trace_in_the_log(
    merge_env: Callable[..., PLO],
) -> None:
    """Not filtering is a decision, not the absence of one — so the PLO it
    produces has to be traceable back to the request that asked for it, naming
    which of the selected Needs were out of scope and which were not."""
    merge_env([_need("X1", in_scope=False), _need("N1")], [])

    with patch.object(plos_route, "logger") as mock_logger:
        client.post("/programs/cs-test/plos/from-needs", json={"need_ids": ["X1", "N1"]})

    warnings = [c.args[0] for c in mock_logger.warning.call_args_list]
    (line,) = [w for w in warnings if "out-of-scope" in w]
    assert "X1" in line
    assert "N1" not in line, "an in-scope Need must not be reported as out of scope"


def test_an_all_in_scope_merge_logs_no_scope_warning(merge_env: Callable[..., PLO]) -> None:
    merge_env([_need("N1"), _need("N2")], [])

    with patch.object(plos_route, "logger") as mock_logger:
        client.post("/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "N2"]})

    warnings = [c.args[0] for c in mock_logger.warning.call_args_list]
    assert [w for w in warnings if "out-of-scope" in w] == []


def test_the_ceiling_still_refuses_a_merge_that_would_exceed_it(
    merge_env: Callable[..., PLO],
) -> None:
    """The 6-10 bounds are a property of the stored set, and the scope warning was
    not allowed to move either of them. Ten core PLOs already exist and this merge
    cites two Needs none of them cite, so it would add an eleventh."""
    needs = [_need(f"N{i:02d}") for i in range(1, 13)]
    existing = [_plo(f"PLO{i}", [f"N{i + 2:02d}"]) for i in range(1, 11)]
    merge_env(needs, existing)

    with patch.object(plos_route, "logger"):
        response = client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["N01", "N02"]}
        )

    assert response.status_code == 422
    assert "เกินเพดาน" in response.json()["detail"]


def test_the_floor_still_refuses_a_merge_that_causes_the_shortfall(
    merge_env: Callable[..., PLO],
) -> None:
    """Six core PLOs, three of them folded into one, leaves four. The floor fires
    because this merge is what caused the shortfall."""
    needs = [_need(f"N{i}") for i in range(1, 7)]
    existing = [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, 7)]
    merge_env(needs, existing)

    with patch.object(plos_route, "logger"):
        response = client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "N2", "N3"]}
        )

    assert response.status_code == 422
    assert "ต่ำกว่านโยบายขั้นต่ำ" in response.json()["detail"]


def test_out_of_scope_needs_do_not_change_which_bound_applies(
    merge_env: Callable[..., PLO],
) -> None:
    """Same shortfall, same refusal, whether the Needs being merged are in scope or
    not. The guard does not get to relax the count policy in either direction, and
    the override path does not get to bypass it."""
    needs = [_need(f"X{i}", in_scope=False) for i in range(1, 7)]
    existing = [_plo(f"PLO{i}", [f"X{i}"]) for i in range(1, 7)]
    merge_env(needs, existing)

    with patch.object(plos_route, "logger"):
        response = client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["X1", "X2", "X3"]}
        )

    assert response.status_code == 422
    assert "ต่ำกว่านโยบายขั้นต่ำ" in response.json()["detail"]
