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
        "list_by_program",
        AsyncMock(return_value=[_need(nid) for nid in cited]),
    )
    insert = AsyncMock()
    monkeypatch.setattr(plos_route.PLORepository, "bulk_insert", insert)
    return insert


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
    insert = _stored(monkeypatch, [stored])

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

    written = insert.await_args.args[0][0]
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
    insert = _stored(monkeypatch, [escalated])

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
    written = insert.await_args.args[0][0]
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


def test_revalidate_rejudges_the_stored_statement(monkeypatch: pytest.MonkeyPatch) -> None:
    """The only way a hand-edited statement gets a verdict. It re-judges what is
    stored rather than drafting anything new — the designer's sentence is the
    input, and no synthesis call happens unless the validator asks for one."""
    stale = _plo("PLO1", ["N1"]).model_copy(update={"smart_validated_by": "stale"})
    other = _plo("PLO2", ["N2"])
    insert = _stored(monkeypatch, [stale, other])
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        plos_route.NeedRepository,
        "list_by_program",
        AsyncMock(return_value=[_need("N1"), _need("N2")]),
    )

    seen: dict[str, object] = {}

    async def fake_validate(draft, **kwargs):  # noqa: ANN001, ANN003
        seen["statement_th"] = draft.statement_th
        seen["sibling_ids"] = [s.plo_id for s in kwargs["siblings"]]
        return stale.model_copy(
            update={"smart_validated_by": "agent", "smart_diagnosis_th": "ตรวจแล้วผ่าน"}
        )

    with patch(
        "curriculum_agent.stages.plo_synthesis.validate_and_build", side_effect=fake_validate
    ):
        resp = client.post("/programs/cs-test/plos/PLO1/revalidate")

    assert resp.status_code == 200, resp.text
    assert seen["statement_th"] == stale.statement_th
    # Its siblings are the other stored outcomes, never itself.
    assert seen["sibling_ids"] == ["PLO2"]
    body = resp.json()
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
    monkeypatch.setattr(plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=[]))

    resp = client.post("/programs/cs-test/plos/PLO1/revalidate")

    assert resp.status_code == 422
    assert "Need" in resp.json()["detail"]


def test_revalidate_404s_for_an_unknown_plo(monkeypatch: pytest.MonkeyPatch) -> None:
    _stored(monkeypatch, [])
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))

    resp = client.post("/programs/cs-test/plos/PLO9/revalidate")

    assert resp.status_code == 404
