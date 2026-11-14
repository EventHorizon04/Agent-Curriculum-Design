from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from curriculum_agent.models import (
    BloomLevel,
    ProgramMetadata,
    StakeholderEvidence,
    StakeholderType,
)
from curriculum_agent.stages import single_needs
from curriculum_agent.stages.demand import compute_demand_score
from curriculum_agent.stages.single_agent_loop import (
    DropNeed,
    LoopOutcome,
    Note,
    SaveNeed,
    SavePLO,
    StopReason,
)
from curriculum_agent.stages.single_need_stats import scoring_corpus_for
from curriculum_agent.stages.single_needs import (
    NeedsHandler,
    build_single_needs,
    run_single_needs,
)

PROGRAM = ProgramMetadata(
    program_id="p",
    university="ม",
    faculty="ค",
    field="การแปล",
    degree_level="bachelor",
    duration_years=4,
)


def _ev(evidence_id: str, stakeholder: StakeholderType) -> StakeholderEvidence:
    return StakeholderEvidence(
        evidence_id=evidence_id,
        program_id="p",
        stakeholder_type=stakeholder,
        source_name="แหล่ง",
        raw_text_th="ข้อความหลักฐาน " * 10,
    )


E1 = _ev("e1", StakeholderType.EMPLOYER)
E2 = _ev("e2", StakeholderType.ALUMNI)
E3 = _ev("e3", StakeholderType.EMPLOYER)
COUNCIL = _ev("council", StakeholderType.PROFESSIONAL_COUNCIL)
EMP1 = _ev("emp1", StakeholderType.EMPLOYER)
EMP2 = _ev("emp2", StakeholderType.EMPLOYER)
EVIDENCE = [COUNCIL, EMP1, EMP2]
CORPUS = scoring_corpus_for(
    ["council", "emp1", "emp2"], {e.evidence_id: e.stakeholder_type for e in EVIDENCE}
)


def _save_need(
    need_id: str | None = None,
    source_evidence_ids: list[str] | None = None,
    statement_th: str = "ต้องการบัณฑิตที่แปลเอกสารธุรกิจได้",
) -> SaveNeed:
    return SaveNeed(
        kind="save_need",
        need_id=need_id,
        statement_th=statement_th,
        rationale_th="เหตุผล",
        ksec_categories=["S"],
        bloom_level=BloomLevel.APPLY,
        source_evidence_ids=source_evidence_ids or ["e1"],
    )


def _draft(ids: list[str]) -> SaveNeed:
    return _save_need(need_id=f"n-{'-'.join(ids)}", source_evidence_ids=ids)


def test_save_with_unknown_evidence_is_refused_and_keeps_no_draft() -> None:
    h = NeedsHandler(PROGRAM, [E1, E2])
    obs = h.handle(_save_need(source_evidence_ids=["e1", "ghost"]))
    assert "ghost" in obs and h.drafts() == []


def test_save_mints_an_id_and_states_it() -> None:
    h = NeedsHandler(PROGRAM, [E1, E2])
    obs = h.handle(_save_need())
    (draft,) = h.drafts()
    assert draft.need_id and draft.need_id in obs
    assert draft.need_id in h.tool_ctx.needs_by_id


def test_save_again_with_the_same_id_replaces() -> None:
    h = NeedsHandler(PROGRAM, [E1, E2])
    h.handle(_save_need())
    need_id = h.drafts()[0].need_id
    h.handle(_save_need(need_id=need_id, statement_th="ต้องการบัณฑิตที่ล่ามได้"))
    (draft,) = h.drafts()
    assert draft.statement_th == "ต้องการบัณฑิตที่ล่ามได้"
    assert h.tool_ctx.needs_by_id[need_id or ""].statement_th == "ต้องการบัณฑิตที่ล่ามได้"


def test_unknown_need_id_is_refused_on_save_and_drop() -> None:
    h = NeedsHandler(PROGRAM, [E1])
    assert "ระบบปฏิเสธ" in h.handle(_save_need(need_id="nope"))
    assert "ระบบปฏิเสธ" in h.handle(DropNeed(kind="drop_need", need_id="nope"))
    assert h.drafts() == []


def test_drop_removes_draft_and_brief() -> None:
    h = NeedsHandler(PROGRAM, [E1])
    h.handle(_save_need())
    need_id = h.drafts()[0].need_id or ""
    h.handle(DropNeed(kind="drop_need", need_id=need_id))
    assert h.drafts() == [] and h.tool_ctx.needs_by_id == {}


def test_note_is_stored_last_wins_and_unknown_evidence_refused() -> None:
    h = NeedsHandler(PROGRAM, [E1])
    h.handle(Note(kind="note", evidence_id="e1", points_th="หนึ่ง"))
    h.handle(Note(kind="note", evidence_id="e1", points_th="สอง"))
    assert h.note_for("e1") == "สอง"
    assert "ระบบปฏิเสธ" in h.handle(Note(kind="note", evidence_id="ghost", points_th="x"))
    assert h.note_for("ghost") is None


def test_save_plo_in_the_needs_half_is_refused() -> None:
    h = NeedsHandler(PROGRAM, [E1])
    plo = SavePLO.model_validate(
        {
            "kind": "save_plo",
            "statement_th": "แปลเอกสาร",
            "action_verb_th": "แปล",
            "bloom_level": "apply",
            "source_need_ids": ["x"],
            "rationale_th": "r",
            "soft": {
                "specific_object_ok": True,
                "measurable_ok": True,
                "achievable_ok": True,
                "actor_ok": True,
                "scope_ok": True,
                "relevant_needs_ok": True,
                "time_bound_ok": True,
            },
        }
    )
    assert "ขั้นนี้ยังไม่ใช่ขั้นเขียน PLO" in h.handle(plo)


def test_opening_message_lists_evidence_and_program_duration() -> None:
    msg = NeedsHandler(PROGRAM, [E1, E2]).opening_message()
    assert "e1" in msg and "e2" in msg and "4 ปี" in msg and "การแปล" in msg


def test_built_needs_are_single_origin_with_code_derived_statistics() -> None:
    needs = build_single_needs("p", [_draft(["council", "emp1"]), _draft(["emp2"])], EVIDENCE)
    a, b = needs
    assert a.origin == "single" and a.member_skill_ids == [] and a.top_skill_ids == []
    assert a.freq == 2 and a.in_field_skill_count == 0
    assert a.is_optional is False and a.classification_coverage == {"requirement": 1}
    assert b.is_optional is True and b.classification_coverage == {"want": 1}
    assert a.demand_score == compute_demand_score(["council", "emp1"], dict(CORPUS))


# ---- the runner ---------------------------------------------------------


class _Repos:
    def __init__(self) -> None:
        self.replace = AsyncMock()


@pytest.fixture
def repos(monkeypatch: pytest.MonkeyPatch) -> _Repos:
    r = _Repos()
    monkeypatch.setattr(single_needs.ProgramRepository, "get", AsyncMock(return_value=PROGRAM))
    monkeypatch.setattr(
        single_needs.EvidenceRepository, "list_by_program", AsyncMock(return_value=[E1, E2, E3])
    )
    monkeypatch.setattr(single_needs.NeedRepository, "replace_by_program", r.replace)
    return r


Script = Callable[[NeedsHandler], None]


def _fake_loop(
    monkeypatch: pytest.MonkeyPatch, script: Script, reason: StopReason, opened: list[str]
) -> None:
    async def fake(handler: Any) -> LoopOutcome:
        script(handler)
        return LoopOutcome(
            stop_reason=reason, turns=3, dropped_evidence_count=0, opened_evidence_ids=opened
        )

    monkeypatch.setattr(single_needs, "run_single_agent", fake)


def _write_one(h: NeedsHandler) -> None:
    h.handle(Note(kind="note", evidence_id="e1", points_th="จุด"))
    h.handle(_save_need(source_evidence_ids=["e1", "e2"]))


async def test_run_stores_and_reports_unread_and_uncited(
    monkeypatch: pytest.MonkeyPatch, repos: _Repos
) -> None:
    _fake_loop(monkeypatch, _write_one, "finished", ["e1", "e2"])
    res = await run_single_needs("p")
    assert res.stop_reason == "finished" and res.unread_evidence_ids == ["e3"]
    assert "e3" in res.uncited_evidence_ids and "e1" not in res.uncited_evidence_ids
    assert res.unnoted_evidence_ids == ["e2"]
    repos.replace.assert_awaited_once()
    assert repos.replace.await_args.args[0] == "p"
    assert len(res.needs) == 1


async def test_turn_cap_with_drafts_still_stores(
    monkeypatch: pytest.MonkeyPatch, repos: _Repos
) -> None:
    _fake_loop(monkeypatch, _write_one, "turn_cap", ["e1"])
    res = await run_single_needs("p")
    assert res.stop_reason == "turn_cap"
    repos.replace.assert_awaited_once()


async def test_no_drafts_fails_and_touches_nothing(
    monkeypatch: pytest.MonkeyPatch, repos: _Repos
) -> None:
    _fake_loop(monkeypatch, lambda h: None, "malformed", [])
    with pytest.raises(HTTPException) as exc:
        await run_single_needs("p")
    assert exc.value.status_code == 502 and "malformed" in exc.value.detail
    repos.replace.assert_not_awaited()


async def test_no_evidence_refuses_before_the_loop(
    monkeypatch: pytest.MonkeyPatch, repos: _Repos
) -> None:
    monkeypatch.setattr(
        single_needs.EvidenceRepository, "list_by_program", AsyncMock(return_value=[])
    )
    loop = AsyncMock()
    monkeypatch.setattr(single_needs, "run_single_agent", loop)
    with pytest.raises(HTTPException) as exc:
        await run_single_needs("p")
    assert exc.value.status_code == 422
    loop.assert_not_awaited()
    repos.replace.assert_not_awaited()
