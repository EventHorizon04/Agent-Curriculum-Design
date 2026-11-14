"""Designer actions on a single program: merge, from-needs redraft, revalidate.

Every one of them goes through the single agent; the multi slots are never reached.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import needs as needs_route
from curriculum_agent.api.routes import plos as plos_route
from curriculum_agent.models import (
    PLO,
    BloomLevel,
    Need,
    ProgramMetadata,
    SMARTCheck,
    StakeholderEvidence,
    StakeholderType,
)
from curriculum_agent.stages import need_merge, plo_synthesis, single_needs, single_plos
from curriculum_agent.stages.single_agent_loop import (
    LoopOutcome,
    Note,
    SaveNeed,
    SavePLO,
    StopReason,
)
from curriculum_agent.stages.single_needs import MergeNeedHandler, merge_single_needs
from curriculum_agent.stages.single_plos import OnePloHandler, draft_single_plo
from tests.support.jobs import InMemoryJobs
from tests.unit.test_need_manual_merge import _install as _install_multi_merge
from tests.unit.test_need_manual_merge import _merge, _pool

client = TestClient(app)
PID = "p"
PROGRAM = ProgramMetadata(
    program_id=PID,
    university="ม",
    faculty="ค",
    field="การแปล",
    degree_level="bachelor",
    duration_years=4,
    agent_mode="single",
)


def _ev(i: str, t: StakeholderType) -> StakeholderEvidence:
    return StakeholderEvidence(
        evidence_id=i, program_id=PID, stakeholder_type=t, source_name="แหล่ง", raw_text_th="ข้อความ"
    )


EVIDENCE = [
    _ev("e1", StakeholderType.EMPLOYER),
    _ev("e2", StakeholderType.EMPLOYER),
    _ev("e3", StakeholderType.PROFESSIONAL_COUNCIL),
    _ev("e4", StakeholderType.ALUMNI),
]


def _need(nid: str, ksec: str, evidence: list[str], score: float = 0.5) -> Need:
    return Need(
        need_id=nid,
        program_id=PID,
        statement_th="ต้องการบัณฑิตที่แปลเอกสารธุรกิจได้",
        ksec_categories=[ksec],
        bloom_level=BloomLevel.APPLY,
        source_evidence_ids=evidence,
        freq=1,
        demand_score=score,
        origin="single",
    )


N1 = _need("n1", "S", ["e1", "e2"], 0.9)
N2 = _need("n2", "K", ["e2", "e3"], 0.8)
N3 = _need("n3", "S", ["e4"], 0.3)
ACTIVE = [N1, N2, N3]


def _save_need(**over: Any) -> SaveNeed:
    base: dict[str, Any] = {
        "kind": "save_need",
        "statement_th": "ต้องการบัณฑิตที่แปลและตรวจเอกสารธุรกิจได้",
        "rationale_th": "เหตุผล",
        "ksec_categories": ["E"],
        "bloom_level": "apply",
        "source_evidence_ids": ["e4"],
    }
    base.update(over)
    return SaveNeed.model_validate(base)


def _all_ok(**over: Any) -> dict[str, Any]:
    soft: dict[str, Any] = {
        k: True
        for k in (
            "specific_object_ok",
            "measurable_ok",
            "achievable_ok",
            "actor_ok",
            "scope_ok",
            "relevant_needs_ok",
            "time_bound_ok",
        )
    }
    soft["findings_th"] = {}
    soft.update(over)
    return soft


def _save_plo(**over: Any) -> SavePLO:
    base: dict[str, Any] = {
        "kind": "save_plo",
        "statement_th": "แปลเอกสารธุรกิจระหว่างประเทศ",
        "action_verb_th": "แปล",
        "bloom_level": "apply",
        "source_need_ids": ["zzz"],  # ignored: the given Needs are cited
        "rationale_th": "เหตุผล",
        "soft": _all_ok(),
    }
    base.update(over)
    return SavePLO.model_validate(base)


def _plo(plo_id: str = "PLO1", edited: bool = False) -> PLO:
    return PLO(
        plo_id=plo_id,
        program_id=PID,
        statement_th="แปลเอกสารกฎหมายตามที่ผู้ออกแบบเขียน",
        bloom_level=BloomLevel.APPLY,
        action_verb_th="แปล",
        smart_check=SMARTCheck(
            specific=True, measurable=True, achievable=True, relevant=True, timely=True
        ),
        source_need_ids=["n1"],
        source_evidence_ids=["e1", "e2"],
        rationale_th="เหตุผลเดิม",
        version=3,
        designer_edited_at=datetime(2026, 11, 14) if edited else None,
        smart_validated_by="stale" if edited else "single_agent",
    )


@pytest.fixture
def fake_loop(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Script the loop for both modules: `.actions(...)` are fed to the handler."""

    class Loop:
        def __init__(self) -> None:
            self.script: list[Any] = []
            self.observations: list[str] = []
            self.reason: StopReason = "finished"

        def actions(self, *acts: Any) -> None:
            self.script = list(acts)

    loop = Loop()

    async def fake(handler: Any) -> LoopOutcome:
        loop.observations = [handler.handle(a) for a in loop.script]
        return LoopOutcome(
            stop_reason=loop.reason, turns=2, dropped_evidence_count=0, opened_evidence_ids=[]
        )

    monkeypatch.setattr(single_needs, "run_single_agent", fake)
    monkeypatch.setattr(single_plos, "run_single_agent", fake)
    return loop


# ---- merge ----------------------------------------------------------------


async def test_single_merge_uses_evidence_union_and_ignores_the_agents_trail(
    fake_loop: Any,
) -> None:
    fake_loop.actions(_save_need(source_evidence_ids=["e1"], ksec_categories=["C"]))
    merged = await merge_single_needs(PROGRAM, [N1, N2], ACTIVE, EVIDENCE, reason_th="ซ้ำกัน")
    assert set(merged.source_evidence_ids) == {"e1", "e2", "e3"}
    assert [c.value for c in merged.ksec_categories] == ["K", "S"]
    assert merged.merged_from == ["n1", "n2"] and merged.origin == "single"
    assert merged.merged_by == "designer" and merged.merge_reason_th == "ซ้ำกัน"
    assert merged.member_skill_ids == [] and merged.demand_score > 0


async def test_merge_with_no_save_is_502(fake_loop: Any) -> None:
    fake_loop.actions()
    with pytest.raises(HTTPException) as exc:
        await merge_single_needs(PROGRAM, [N1, N2], ACTIVE, EVIDENCE, reason_th=None)
    assert exc.value.status_code == 502


def test_merge_handler_accepts_notes_replaces_saves_and_refuses_the_rest() -> None:
    h = MergeNeedHandler(PROGRAM, [N1, N2], ACTIVE, EVIDENCE, None)
    assert "รับโน้ต" in h.handle(Note(kind="note", evidence_id="e1", points_th="x"))
    assert h.handle(Note(kind="note", evidence_id="e4", points_th="x")).startswith("ระบบปฏิเสธ")
    h.handle(_save_need(statement_th="ต้องการบัณฑิตที่แปลเอกสารได้ข้อแรก"))
    h.handle(_save_need(statement_th="ต้องการบัณฑิตที่แปลเอกสารได้ข้อสอง"))
    draft = h.draft()
    assert draft is not None and draft.statement_th.endswith("ข้อสอง")
    assert h.handle(_save_plo()).startswith("ระบบปฏิเสธ")


def test_merge_opening_message_lists_only_the_originals() -> None:
    msg = MergeNeedHandler(PROGRAM, [N1, N2], ACTIVE, EVIDENCE, "เหตุ").opening_message()
    assert "[n1]" in msg and "[n2]" in msg and "[n3]" not in msg


def test_merge_route_on_a_single_program_never_touches_skills_or_the_need_combination_slot(
    monkeypatch: pytest.MonkeyPatch, fake_loop: Any
) -> None:
    store, _ = _install_multi_merge(monkeypatch, _pool())
    forbidden = AsyncMock(side_effect=AssertionError("multi slot called"))
    monkeypatch.setattr(need_merge, "complete_need_combination", forbidden)
    monkeypatch.setattr(needs_route.SkillRepository, "list_by_program", AsyncMock(return_value=[]))
    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=PROGRAM))
    monkeypatch.setattr(
        needs_route.EvidenceRepository,
        "list_by_program",
        AsyncMock(
            return_value=[
                _ev(e, StakeholderType.EMPLOYER)
                for e in ("E-A", "E-B", "E-C", "E-F0", "E-F1", "E-F2", "E-F3")
            ]
        ),
    )
    fake_loop.actions(_save_need(source_evidence_ids=["E-A"], ksec_categories=["S"]))

    response = _merge(["A", "B"], "งานเดียวกัน")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["origin"] == "single" and body["merged_by"] == "designer"
    assert body["merged_from"] == ["A", "B"]
    assert store.rows["A"].merged_into == body["need_id"]
    forbidden.assert_not_awaited()


# ---- one PLO ---------------------------------------------------------------


async def test_revalidating_a_hand_edited_plo_keeps_the_designers_statement(
    fake_loop: Any,
) -> None:
    edited = _plo(edited=True)
    fake_loop.actions(
        _save_plo(
            statement_th="ถ้อยคำใหม่ของตัวแทน",
            action_verb_th="เขียน",
            soft=_all_ok(measurable_ok=False),
        )
    )
    plo = await draft_single_plo(
        PROGRAM,
        [N1],
        EVIDENCE,
        plo_id="PLO1",
        known_need_ids={"n1"},
        siblings=[],
        note_th=None,
        current=edited,
    )
    assert plo.statement_th == edited.statement_th and plo.action_verb_th == "แปล"
    assert plo.soft_flags == ["M_assessable"] and plo.smart_validated_by == "single_agent"
    assert plo.designer_edited_at == edited.designer_edited_at and plo.version == 3
    assert plo.rationale_th == "เหตุผลเดิม" and plo.source_need_ids == ["n1"]


async def test_revalidating_an_unedited_plo_takes_the_agents_revision(fake_loop: Any) -> None:
    fake_loop.actions(_save_plo(statement_th="แปลเอกสารกฎหมายและธุรกิจ"))
    plo = await draft_single_plo(
        PROGRAM,
        [N1],
        EVIDENCE,
        plo_id="PLO1",
        known_need_ids={"n1"},
        siblings=[],
        note_th=None,
        current=_plo(),
    )
    assert plo.statement_th == "แปลเอกสารกฎหมายและธุรกิจ" and plo.designer_edited_at is None


async def test_new_plo_cites_the_given_needs_not_the_agents_list(fake_loop: Any) -> None:
    fake_loop.actions(_save_plo())
    plo = await draft_single_plo(
        PROGRAM,
        [N1, N2],
        EVIDENCE,
        plo_id="PLO4",
        known_need_ids={"n1", "n2"},
        siblings=[],
        note_th="โน้ต",
    )
    assert plo.plo_id == "PLO4" and plo.source_need_ids == ["n1", "n2"]
    assert plo.source_evidence_ids == ["e1", "e2", "e3"] and plo.version == 1


async def test_one_plo_with_no_save_is_502(fake_loop: Any) -> None:
    fake_loop.actions()
    with pytest.raises(HTTPException) as exc:
        await draft_single_plo(
            PROGRAM,
            [N1],
            EVIDENCE,
            plo_id="PLO1",
            known_need_ids={"n1"},
            siblings=[],
            note_th=None,
        )
    assert exc.value.status_code == 502


def test_one_plo_handler_refuses_need_actions_and_accepts_notes() -> None:
    h = OnePloHandler(PROGRAM, [N1], EVIDENCE, [], None, None)
    assert "รับโน้ต" in h.handle(Note(kind="note", evidence_id="e1", points_th="x"))
    assert h.handle(_save_need()).startswith("ระบบปฏิเสธ")
    assert h.draft() is None


def test_keep_wording_opening_only_for_a_hand_edited_plo() -> None:
    edited = OnePloHandler(PROGRAM, [N1], EVIDENCE, [], None, _plo(edited=True))
    plain = OnePloHandler(PROGRAM, [N1], EVIDENCE, [], None, _plo())
    assert "ห้ามแก้ถ้อยคำ" in edited.opening_message()
    assert "ห้ามแก้ถ้อยคำ" not in plain.opening_message()


# ---- routes: from-needs and revalidate -------------------------------------


def _patch_plo_routes(monkeypatch: pytest.MonkeyPatch, mode: str, existing: list[PLO]) -> Any:
    program = PROGRAM.model_copy(update={"agent_mode": mode})
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=program))
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=ACTIVE)
    )
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_active_by_program", AsyncMock(return_value=ACTIVE)
    )
    monkeypatch.setattr(
        plos_route.PLORepository, "list_by_program", AsyncMock(return_value=existing)
    )
    replace = AsyncMock(return_value=len(existing))
    monkeypatch.setattr(plos_route.PLORepository, "replace", replace)
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(plos_route.PLORepository, "update_if_version", update)
    monkeypatch.setattr(
        plos_route.EvidenceRepository, "list_by_program", AsyncMock(return_value=EVIDENCE)
    )
    return replace, update


def test_from_needs_on_a_single_program_uses_the_single_drafter_and_keeps_the_bounds(
    monkeypatch: pytest.MonkeyPatch, fake_loop: Any
) -> None:
    replace, _ = _patch_plo_routes(monkeypatch, "single", [_plo("PLO1")])
    boom = AsyncMock(side_effect=AssertionError("multi path called"))
    monkeypatch.setattr(plo_synthesis, "synthesize_from_needs", boom)
    monkeypatch.setattr(plo_synthesis, "validate_and_build", boom)
    fake_loop.actions(_save_plo())

    ok = client.post(f"/programs/{PID}/plos/from-needs", json={"need_ids": ["n1", "n2"]})

    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["source_need_ids"] == ["n1", "n2"] and body["smart_validated_by"] == "single_agent"
    replace.assert_awaited_once()
    assert replace.await_args.args[1] == ["PLO1"]  # the PLO citing n1 is superseded
    boom.assert_not_awaited()

    # The bounds stay shared: an unknown Need is refused before any draft.
    bad = client.post(f"/programs/{PID}/plos/from-needs", json={"need_ids": ["n1", "nope"]})
    assert bad.status_code == 422


def test_from_needs_on_a_multi_program_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_plo_routes(monkeypatch, "multi", [])
    synth = AsyncMock(return_value=_plo("PLO1"))
    monkeypatch.setattr(plo_synthesis, "synthesize_from_needs", synth)
    single = AsyncMock(side_effect=AssertionError("single drafter called"))
    monkeypatch.setattr(single_plos, "draft_single_plo", single)

    response = client.post(f"/programs/{PID}/plos/from-needs", json={"need_ids": ["n1", "n2"]})

    assert response.status_code == 200, response.text
    synth.assert_awaited_once()
    single.assert_not_awaited()


def test_revalidate_on_a_single_program_runs_the_single_agent_and_stores_it(
    monkeypatch: pytest.MonkeyPatch, fake_loop: Any, jobs_store: InMemoryJobs
) -> None:
    _, update = _patch_plo_routes(monkeypatch, "single", [_plo("PLO1", edited=True)])
    boom = AsyncMock(side_effect=AssertionError("multi path called"))
    monkeypatch.setattr(plo_synthesis, "validate_and_build", boom)
    fake_loop.actions(_save_plo(statement_th="ถ้อยคำอื่น", soft=_all_ok(scope_ok=False)))

    response = client.post(f"/programs/{PID}/plos/PLO1/revalidate")
    assert response.status_code == 202, response.text
    jobs_store.recorder.drain()  # type: ignore[attr-defined]

    update.assert_awaited_once()
    stored = update.await_args.args[0]
    assert stored.statement_th == _plo().statement_th  # the designer's sentence stands
    assert stored.version == 4 and stored.soft_flags == ["A_scope"]
    assert update.await_args.kwargs["expected_version"] == 3
    boom.assert_not_awaited()
