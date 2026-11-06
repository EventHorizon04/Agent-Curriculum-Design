from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import plos as plos_route
from curriculum_agent.models import (
    PLO,
    BloomLevel,
    FeedbackAction,
    KSECCategory,
    Need,
    ProgramMetadata,
    SMARTCheck,
    SupersededPLO,
)
from curriculum_agent.stages import plo_redraft
from curriculum_agent.stages import plo_synthesis as ps_module
from curriculum_agent.stages.need_grouping import PROVIDER_MARKER_TH, REVIEW_MARKER_TH
from tests.support.jobs import InMemoryJobs, SpawnRecorder

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


def _need(nid: str, *, in_scope: bool = True, statement_th: str | None = None) -> Need:
    return Need(
        need_id=nid,
        program_id="cs-test",
        statement_th=statement_th or f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
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


def test_from_needs_refuses_six_needs(
    merge_env: Callable[..., PLO], monkeypatch: pytest.MonkeyPatch
) -> None:
    needs = [_need(f"N{i}") for i in range(1, 7)]
    merge_env(needs, [])
    synth = AsyncMock()
    monkeypatch.setattr("curriculum_agent.stages.plo_synthesis.synthesize_from_needs", synth)
    program_get = AsyncMock(return_value=_program())
    monkeypatch.setattr(plos_route.ProgramRepository, "get", program_get)

    response = client.post(
        "/programs/cs-test/plos/from-needs", json={"need_ids": [n.need_id for n in needs]}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "เลือก Need 2-5 ข้อเพื่อรวมเป็น PLO"
    synth.assert_not_called()
    program_get.assert_not_called()
    plos_route.PLORepository.replace.assert_not_called()  # type: ignore[attr-defined]


def test_from_needs_accepts_five(merge_env: Callable[..., PLO]) -> None:
    needs = [_need(f"N{i}") for i in range(1, 6)]
    merge_env(needs, [])

    response = client.post(
        "/programs/cs-test/plos/from-needs", json={"need_ids": [n.need_id for n in needs]}
    )

    assert response.status_code == 200, response.text


def test_list_superseded_404_unknown_program(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=None))
    response = client.get("/programs/nope/plos/superseded")
    assert response.status_code == 404


def test_list_superseded_returns_repository_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    row = SupersededPLO(
        id="h-1",
        program_id="cs-test",
        superseded_by="PLO1",
        superseded_at=datetime(2026, 11, 3, 12, 0, 0),
        plo=_plo("PLO2", ["N1"]),
    )
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        plos_route.SupersededPLORepository, "list_by_program", AsyncMock(return_value=[row])
    )

    response = client.get("/programs/cs-test/plos/superseded")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [r["id"] for r in body] == ["h-1"]
    assert body[0]["superseded_by"] == "PLO1"
    assert body[0]["superseded_at"].endswith("+00:00")
    assert body[0]["plo"]["plo_id"] == "PLO2"


def test_list_feedback_404_unknown_program(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=None))
    response = client.get("/programs/nope/plos/feedback")
    assert response.status_code == 404


def test_list_feedback_returns_the_trail(monkeypatch: pytest.MonkeyPatch) -> None:
    row = FeedbackAction(
        id="f-1",
        program_id="cs-test",
        review_created_at=datetime(2026, 11, 3, 12, 0, 0),
        kind="bloom",
        outcome="skipped",
        outcome_reason_th="ไม่พบ PLO นี้ในชุดปัจจุบัน",
    )
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        plos_route.PLOFeedbackRepository, "list_by_program", AsyncMock(return_value=[row])
    )

    response = client.get("/programs/cs-test/plos/feedback")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [r["id"] for r in body] == ["f-1"]
    assert body[0]["review_created_at"].endswith("+00:00")


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

    with patch.object(plo_redraft, "logger") as mock_logger:
        client.post("/programs/cs-test/plos/from-needs", json={"need_ids": ["X1", "N1"]})

    warnings = [c.args[0] for c in mock_logger.warning.call_args_list]
    (line,) = [w for w in warnings if "out-of-scope" in w]
    assert "X1" in line
    assert "N1" not in line, "an in-scope Need must not be reported as out of scope"


def test_an_all_in_scope_merge_logs_no_scope_warning(merge_env: Callable[..., PLO]) -> None:
    merge_env([_need("N1"), _need("N2")], [])

    with patch.object(plo_redraft, "logger") as mock_logger:
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


def test_a_merge_may_take_the_set_below_the_policy_band(
    merge_env: Callable[..., PLO],
) -> None:
    """Six core PLOs, three folded into one, leaves four: under the 6-10 band,
    at the merge floor. Two PLOs that say one thing are not two outcomes."""
    needs = [_need(f"N{i}") for i in range(1, 7)]
    existing = [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, 7)]
    merge_env(needs, existing)

    with patch.object(plos_route, "logger"):
        response = client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "N2", "N3"]}
        )

    assert response.status_code == 200, response.text


def test_the_merge_floor_refuses_a_merge_that_causes_the_shortfall(
    merge_env: Callable[..., PLO],
) -> None:
    """Four core PLOs, two folded into one, leaves three — below the merge floor,
    and this merge is what caused it."""
    needs = [_need(f"N{i}") for i in range(1, 5)]
    existing = [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, 5)]
    merge_env(needs, existing)

    with patch.object(plos_route, "logger"):
        response = client.post("/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "N2"]})

    assert response.status_code == 422
    assert "ต่ำกว่าขั้นต่ำของการรวม" in response.json()["detail"]
    assert "4" in response.json()["detail"]


def test_a_set_already_below_the_floor_can_still_grow(
    merge_env: Callable[..., PLO],
) -> None:
    """Two core PLOs, and a merge of two Needs nothing cites adds a third: still
    below the floor, but this merge did not cause the shortfall."""
    needs = [_need(f"N{i}") for i in range(1, 5)]
    existing = [_plo("PLO1", ["N1"]), _plo("PLO2", ["N2"])]
    merge_env(needs, existing)

    with patch.object(plos_route, "logger"):
        response = client.post("/programs/cs-test/plos/from-needs", json={"need_ids": ["N3", "N4"]})

    assert response.status_code == 200, response.text


def test_out_of_scope_needs_do_not_change_which_bound_applies(
    merge_env: Callable[..., PLO],
) -> None:
    """Same shortfall, same refusal, whether the Needs being merged are in scope or
    not. The guard does not get to relax the count policy in either direction, and
    the override path does not get to bypass it."""
    needs = [_need(f"X{i}", in_scope=False) for i in range(1, 5)]
    existing = [_plo(f"PLO{i}", [f"X{i}"]) for i in range(1, 5)]
    merge_env(needs, existing)

    with patch.object(plos_route, "logger"):
        response = client.post("/programs/cs-test/plos/from-needs", json={"need_ids": ["X1", "X2"]})

    assert response.status_code == 422
    assert "ต่ำกว่าขั้นต่ำของการรวม" in response.json()["detail"]


# --------------------------- merge route, unwritten-need guard ---------------------------
#
# A fallback Need's statement is a marker plus a comma-joined skill list, not a
# requirement. Unlike scope, this is not an override a designer gets to make by
# selecting it anyway: rewording cannot supply a requirement nobody wrote, so
# the route refuses rather than logging and proceeding the way it does for
# scope above.


def test_merging_an_unwritten_need_is_refused_with_422(merge_env: Callable[..., PLO]) -> None:
    merge_env(
        [_need("N1"), _need("U1", statement_th=f"{REVIEW_MARKER_TH} ทักษะ A, ทักษะ B")],
        [],
    )

    response = client.post("/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "U1"]})

    assert response.status_code == 422
    assert "U1" in response.json()["detail"]


def test_merging_an_unwritten_need_calls_no_llm_and_writes_nothing(
    merge_env: Callable[..., PLO],
) -> None:
    merge_env(
        [_need("N1"), _need("U1", statement_th=f"{PROVIDER_MARKER_TH} ทักษะ C, ทักษะ D")],
        [],
    )

    response = client.post("/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "U1"]})

    assert response.status_code == 422
    ps_module.synthesize_from_needs.assert_not_called()
    plos_route.PLORepository.replace.assert_not_called()


def test_an_all_written_merge_is_unaffected(merge_env: Callable[..., PLO]) -> None:
    merge_env([_need("N1"), _need("N2")], [])

    response = client.post("/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "N2"]})

    assert response.status_code == 200, response.text


# --------------------------- PUT and revalidate ---------------------------
#
# PUT had no test coverage at all, which is how it kept accepting a
# client-supplied verdict: the hole in the gate was also a hole in the suite.


def _stored(monkeypatch: pytest.MonkeyPatch, plos: list[PLO]) -> AsyncMock:
    monkeypatch.setattr(plos_route.PLORepository, "list_by_program", AsyncMock(return_value=plos))
    # PUT resolves the Needs its stored PLO cites, so R has something to check
    # against. Stubbed rather than reached: without this the route opened a real
    # connection and these tests passed only on a machine with the dev database
    # up, which is how a wrong R verdict could look like a green suite.
    cited = [nid for plo in plos for nid in plo.source_need_ids]
    monkeypatch.setattr(
        plos_route.NeedRepository,
        "list_active_by_program",
        AsyncMock(return_value=[_need(nid) for nid in cited]),
    )
    insert = AsyncMock()
    monkeypatch.setattr(plos_route.PLORepository, "bulk_insert", insert)
    # PUT writes through the version-checked update, never the upsert.
    monkeypatch.setattr(plos_route.PLORepository, "update_if_version", AsyncMock(return_value=True))
    return insert


def _stored_put(monkeypatch: pytest.MonkeyPatch, plos: list[PLO]) -> AsyncMock:
    """`_stored` for a PUT test: returns the `update_if_version` mock."""
    _stored(monkeypatch, plos)
    return cast(AsyncMock, plos_route.PLORepository.update_if_version)


def test_put_runs_the_code_gate_so_an_edited_row_can_be_read_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug this pins: `model_copy` skips validators, so a forbidden word
    edited in through PUT was stored with `smart_escalated=False` — and every
    later read goes through `PLO.model_validate`, whose forbidden-word check
    only stands down for an escalated row. One PUT therefore made
    `GET /plos/` raise for the whole program, `revalidate` included: the way
    back was behind the same read that was failing.

    Asserting the escalation is not enough on its own — the assertion that
    encodes the defect is that the written row survives being read."""
    stored = _plo("PLO1", ["N1"]).model_copy(
        update={"smart_escalated": False, "smart_validated_by": "agent"}
    )
    insert = _stored_put(monkeypatch, [stored])

    resp = client.put(
        "/programs/cs-test/plos/PLO1",
        json={
            "statement_th": "อธิบายและเข้าใจหลักการออกแบบซอฟต์แวร์ได้",
            "bloom_level": "understand",
            "action_verb_th": "อธิบาย",
            "rationale_th": "เหตุผล",
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["smart_escalated"] is True
    assert body["smart_validated_by"] == "stale"
    assert body["smart_check"]["measurable"] is False
    assert "M_forbidden" in {f["criterion"] for f in body["smart_check"]["findings"]}

    written = insert.await_args.args[0]
    # The row a repository would read back. Raises before the fix.
    assert PLO.model_validate(written.model_dump(mode="json")).smart_escalated is True


def test_put_does_not_escalate_a_statement_using_an_allowed_compound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """รักษา holds รัก and จำแนก holds จำ. The pure gate PUT now runs is the
    same one as everywhere else, so the compound fix has to hold here too —
    otherwise every hand edit using a legitimate Thai verb escalates."""
    stored = _plo("PLO1", ["N1"])
    _stored(monkeypatch, [stored])

    resp = client.put(
        "/programs/cs-test/plos/PLO1",
        json={
            "statement_th": "จำแนกและรักษามาตรฐานคุณภาพซอฟต์แวร์ตามข้อกำหนดได้",
            "bloom_level": "understand",
            "action_verb_th": "จำแนก",
            "rationale_th": "เหตุผล",
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["smart_escalated"] is False
    assert body["smart_check"]["measurable"] is True
    assert body["smart_check"]["findings"] == []
    assert body["smart_validated_by"] == "stale"


def test_put_ignores_a_client_supplied_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """The hole this closes: a caller with the API key could set
    smart_escalated=False with an all-true smart_check on a statement no
    validator ever passed — immutable rule 5 with the gate removed."""
    escalated = _plo("PLO1", ["N1"]).model_copy(
        update={
            "smart_escalated": True,
            "smart_validated_by": "agent",
            "smart_check": SMARTCheck(
                specific=False, measurable=True, achievable=True, relevant=True, timely=True
            ),
        }
    )
    insert = _stored_put(monkeypatch, [escalated])

    resp = client.put(
        "/programs/cs-test/plos/PLO1",
        json={
            "statement_th": escalated.statement_th,
            "bloom_level": "create",
            "action_verb_th": "ออกแบบ",
            "rationale_th": "เหตุผล",
            # A client trying to clear its own escalation.
            "smart_escalated": False,
            "smart_check": {
                "specific": True,
                "measurable": True,
                "achievable": True,
                "relevant": True,
                "timely": True,
            },
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["smart_escalated"] is True
    assert resp.json()["smart_check"]["specific"] is False
    written = insert.await_args.args[0]
    assert written.smart_escalated is True


def test_put_marks_an_edited_statement_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Editing the text must not silently inherit the old verdict — but it must
    not block on a multi-turn validation the designer did not ask for either."""
    stored = _plo("PLO1", ["N1"]).model_copy(update={"smart_validated_by": "agent"})
    _stored(monkeypatch, [stored])

    resp = client.put(
        "/programs/cs-test/plos/PLO1",
        json={
            "statement_th": "ประเมินคุณภาพซอฟต์แวร์ตามมาตรฐานได้",
            "bloom_level": "evaluate",
            "action_verb_th": "ประเมิน",
            "rationale_th": "เหตุผล",
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["smart_validated_by"] == "stale"
    assert body["statement_th"] == "ประเมินคุณภาพซอฟต์แวร์ตามมาตรฐานได้"
    assert body["version"] == stored.version + 1


def test_put_leaves_the_provenance_alone_when_the_text_did_not_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _plo("PLO1", ["N1"]).model_copy(update={"smart_validated_by": "agent"})
    _stored(monkeypatch, [stored])

    resp = client.put(
        "/programs/cs-test/plos/PLO1",
        json={
            "statement_th": stored.statement_th,
            "bloom_level": "create",
            "action_verb_th": "ออกแบบ",
            "rationale_th": "เหตุผลใหม่",
        },
    )

    assert resp.json()["smart_validated_by"] == "agent"


def _put(statement: str, plo_id: str = "PLO1") -> dict[str, object]:
    return client.put(
        f"/programs/cs-test/plos/{plo_id}",
        json={
            "statement_th": statement,
            "bloom_level": "create",
            "action_verb_th": "ออกแบบ",
            "rationale_th": "เหตุผล",
        },
    ).json()


def test_put_changed_statement_sets_designer_edited_at(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = _plo("PLO1", ["N1"])
    insert = _stored_put(monkeypatch, [stored])
    before = datetime.utcnow()
    body = _put("ออกแบบระบบฐานข้อมูลสำหรับองค์กรได้")
    assert str(body["designer_edited_at"]).endswith("+00:00")
    written = insert.await_args.args[0]
    assert written.designer_edited_at is not None
    assert written.designer_edited_at.tzinfo is None
    assert before <= written.designer_edited_at <= datetime.utcnow()


def test_put_same_statement_keeps_designer_edited_at_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _plo("PLO1", ["N1"])
    _stored(monkeypatch, [stored])
    assert _put(stored.statement_th)["designer_edited_at"] is None


def test_put_same_statement_keeps_an_earlier_designer_edited_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    earlier = datetime(2026, 11, 4, 8, 0, 0)
    stored = _plo("PLO1", ["N1"]).model_copy(update={"designer_edited_at": earlier})
    insert = _stored_put(monkeypatch, [stored])
    _put(stored.statement_th)
    assert insert.await_args.args[0].designer_edited_at == earlier


_PUT_BODY = {
    "statement_th": "ออกแบบระบบฐานข้อมูลสำหรับองค์กรได้",
    "bloom_level": "create",
    "action_verb_th": "ออกแบบ",
    "rationale_th": "เหตุผล",
}
_CHANGED_DURING_EDIT = "PLO นี้ถูกเปลี่ยนระหว่างแก้ไข — โหลดใหม่แล้วลองอีกครั้ง"


def test_put_conflicting_version_answers_409_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two PUTs raced: the second finds the version moved, so its UPDATE matches no row."""
    stored = _plo("PLO1", ["N1"]).model_copy(update={"version": 3})
    insert = _stored(monkeypatch, [stored])
    update = AsyncMock(return_value=False)
    monkeypatch.setattr(plos_route.PLORepository, "update_if_version", update)

    resp = client.put("/programs/cs-test/plos/PLO1", json=_PUT_BODY)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == _CHANGED_DURING_EDIT
    update.assert_awaited_once()
    assert update.await_args.kwargs == {"expected_version": 3}
    assert update.await_args.args[0].version == 4
    insert.assert_not_awaited()


def test_put_on_row_deleted_between_read_and_write_answers_409_no_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A redraft merged the PLO away after PUT read it: no row matches, nothing is
    re-inserted (the old upsert resurrected it)."""
    insert = _stored(monkeypatch, [_plo("PLO1", ["N1"])])
    monkeypatch.setattr(
        plos_route.PLORepository, "update_if_version", AsyncMock(return_value=False)
    )

    resp = client.put("/programs/cs-test/plos/PLO1", json=_PUT_BODY)

    assert resp.status_code == 409, resp.text
    insert.assert_not_awaited()


def test_put_success_bumps_version_once(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = _plo("PLO1", ["N1"]).model_copy(update={"version": 2})
    insert = _stored(monkeypatch, [stored])
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(plos_route.PLORepository, "update_if_version", update)

    resp = client.put("/programs/cs-test/plos/PLO1", json=_PUT_BODY)

    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 3
    update.assert_awaited_once()
    assert update.await_args.kwargs == {"expected_version": 2}
    insert.assert_not_awaited()


def test_put_unchanged_statement_is_version_checked_too(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = _plo("PLO1", ["N1"])
    insert = _stored(monkeypatch, [stored])
    monkeypatch.setattr(
        plos_route.PLORepository, "update_if_version", AsyncMock(return_value=False)
    )
    resp = client.put(
        "/programs/cs-test/plos/PLO1", json={**_PUT_BODY, "statement_th": stored.statement_th}
    )
    assert resp.status_code == 409
    insert.assert_not_awaited()


def test_revalidate_keeps_designer_edited_at(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    edited_at = datetime(2026, 11, 4, 8, 0, 0)
    stale = _plo("PLO1", ["N1"]).model_copy(
        update={"smart_validated_by": "stale", "designer_edited_at": edited_at}
    )
    insert = _stored(monkeypatch, [stale])
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))

    allow_repair_seen: list[bool] = []

    async def fake_validate(draft, **kwargs):  # noqa: ANN001, ANN003
        allow_repair_seen.append(kwargs["allow_repair"])
        # validate_and_build builds a fresh PLO, which knows nothing of the edit.
        return _plo("PLO1", ["N1"]).model_copy(update={"smart_validated_by": "agent"})

    with patch(
        "curriculum_agent.stages.plo_synthesis.validate_and_build", side_effect=fake_validate
    ):
        resp = client.post("/programs/cs-test/plos/PLO1/revalidate")
        assert resp.status_code == 202, resp.text
        spawned.drain()

    job = jobs_store.rows[resp.json()["job_id"]]
    assert job.status == "succeeded", job.error_th
    assert insert.await_args.args[0][0].designer_edited_at == edited_at
    # The designer's own sentence is judged, never rewritten by a repair.
    assert allow_repair_seen == [False]


def test_revalidate_rejudges_the_stored_statement(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    """The only way a hand-edited statement gets a verdict. It re-judges what is
    stored rather than drafting anything new — the designer's sentence is the
    input, and no synthesis call happens unless the validator asks for one."""
    stale = _plo("PLO1", ["N1"]).model_copy(update={"smart_validated_by": "stale"})
    other = _plo("PLO2", ["N2"])
    insert = _stored(monkeypatch, [stale, other])
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        plos_route.NeedRepository,
        "list_active_by_program",
        AsyncMock(return_value=[_need("N1"), _need("N2")]),
    )

    seen: dict[str, object] = {}

    async def fake_validate(draft, **kwargs):  # noqa: ANN001, ANN003
        seen["statement_th"] = draft.statement_th
        seen["sibling_ids"] = [s.plo_id for s in kwargs["siblings"]]
        seen["allow_repair"] = kwargs["allow_repair"]
        return stale.model_copy(
            update={"smart_validated_by": "agent", "smart_diagnosis_th": "ตรวจแล้วผ่าน"}
        )

    with patch(
        "curriculum_agent.stages.plo_synthesis.validate_and_build", side_effect=fake_validate
    ):
        resp = client.post("/programs/cs-test/plos/PLO1/revalidate")
        # The judging is a job body: nothing has been judged or stored yet, and the
        # body has to run inside the patch above.
        assert resp.status_code == 202, resp.text
        assert seen == {}
        assert insert.await_count == 0
        spawned.drain()

    job = jobs_store.rows[resp.json()["job_id"]]
    assert job.status == "succeeded", job.error_th
    assert seen["statement_th"] == stale.statement_th
    # Its siblings are the other stored outcomes, never itself.
    assert seen["sibling_ids"] == ["PLO2"]
    # Never hand-edited, so the agent may still repair it.
    assert seen["allow_repair"] is True
    body = job.result
    assert body["smart_validated_by"] == "agent"
    assert body["version"] == stale.version + 1
    assert insert.await_count == 1


def test_revalidate_refuses_a_plo_whose_needs_are_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing to judge it against. The trace endpoint reports the same
    condition as missing_need_ids."""
    orphan = _plo("PLO1", ["N-GONE"])
    _stored(monkeypatch, [orphan])
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_active_by_program", AsyncMock(return_value=[])
    )

    resp = client.post("/programs/cs-test/plos/PLO1/revalidate")

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "Need" in detail
    # plo_id already reads "PLO1"; a "PLO " prefix showed "PLO PLO1".
    assert detail.startswith("PLO1 ")
    assert "PLO PLO1" not in detail


def test_revalidate_404s_for_an_unknown_plo(monkeypatch: pytest.MonkeyPatch) -> None:
    _stored(monkeypatch, [])
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))

    resp = client.post("/programs/cs-test/plos/PLO9/revalidate")

    assert resp.status_code == 404
