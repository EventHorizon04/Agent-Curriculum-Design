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


VISION = _ev("vision", StakeholderType.INSTITUTIONAL_DIRECTION)


def test_first_finish_is_refused_while_requirement_evidence_is_uncited() -> None:
    h = NeedsHandler(PROGRAM, [VISION, COUNCIL, E1, E2])
    _six_core(h)
    h.handle(_save_need(source_evidence_ids=["e1", "council"]))
    refusal = h.finish_refusal()
    assert refusal is not None
    assert "vision" in refusal and "council" not in refusal and "e1" not in refusal
    # Said once: the second finish is accepted with the item still uncited.
    assert h.finish_refusal() is None
    assert h.uncited_requirement_ids() == ["vision"]


def test_finish_is_accepted_when_every_requirement_item_is_cited() -> None:
    h = NeedsHandler(PROGRAM, [VISION, COUNCIL, EMP1])
    h.handle(_save_need(source_evidence_ids=["emp1", "council"]))
    h.handle(
        _save_need(source_evidence_ids=["vision"], statement_th="ต้องการบัณฑิตที่ล่ามการเจรจาธุรกิจได้")
    )
    assert h.uncited_requirement_ids() == []
    # Two core Needs is still under the floor, but the requirement gate is silent.
    refusal = h.finish_refusal()
    assert refusal is not None and "หลักฐานประเภท requirement" not in refusal


def _six_core(h: NeedsHandler) -> None:
    for n in range(6):
        h.handle(
            _save_need(
                source_evidence_ids=["e1", "e2"], statement_th=f"ต้องการบัณฑิตที่แปลเอกสารธุรกิจได้ {n}"
            )
        )


def test_six_core_needs_on_general_evidence_finish_at_once() -> None:
    h = NeedsHandler(PROGRAM, [E1, E2])
    _six_core(h)
    assert h.finish_refusal() is None


def test_every_finish_is_refused_below_six_core_needs_and_says_what_to_recheck() -> None:
    h = NeedsHandler(PROGRAM, [E1, E2, E3])
    h.handle(_save_need(source_evidence_ids=["e1"]))  # one general item: optional
    h.handle(_save_need(source_evidence_ids=["e1", "e2"], statement_th="ต้องการบัณฑิตที่ล่ามการเจรจาได้"))
    one_item_id = h.drafts()[0].need_id or ""
    two_item_id = h.drafts()[1].need_id or ""
    refusal = h.finish_refusal()
    assert refusal is not None
    assert "Need หลักมี 1 ข้อ ต่ำกว่าขั้นต่ำ 6 ข้อ" in refusal
    assert f"- {one_item_id} (อ้าง e1)" in refusal and two_item_id not in refusal
    assert "- e3 (แหล่ง)" in refusal and "- e2 (" not in refusal
    # Not once-only: a run refused once finished again with three Needs (2026-11-15).
    assert h.finish_refusal() == refusal
    _six_core(h)
    assert h.finish_refusal() is None


def test_core_gate_still_speaks_after_the_requirement_gate_spoke_alone() -> None:
    h = NeedsHandler(PROGRAM, [VISION, E1, E2])
    _six_core(h)
    first = h.finish_refusal()
    assert first is not None and "vision" in first and "Need หลักมี" not in first
    for d in h.drafts()[1:]:
        h.handle(DropNeed(kind="drop_need", need_id=d.need_id or ""))
    second = h.finish_refusal()
    assert second is not None and "Need หลักมี 1 ข้อ" in second
    assert "หลักฐานประเภท requirement" not in second


def test_finish_with_no_need_at_all_is_refused() -> None:
    h = NeedsHandler(PROGRAM, [E1, E2])
    refusal = h.finish_refusal()
    assert refusal is not None and "Need หลักมี 0 ข้อ" in refusal


async def test_run_reports_requirement_evidence_left_uncited(
    monkeypatch: pytest.MonkeyPatch, repos: _Repos
) -> None:
    monkeypatch.setattr(
        single_needs.EvidenceRepository,
        "list_by_program",
        AsyncMock(return_value=[VISION, E1, E2]),
    )
    _fake_loop(monkeypatch, _write_one, "finished", ["e1", "e2"])
    res = await run_single_needs("p")
    assert res.uncited_requirement_evidence_ids == ["vision"]


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
    h.tool_ctx.read_parts.update({("e1", 1), ("e2", 1)})
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


def test_opening_message_names_the_degree_level() -> None:
    assert "ปริญญาตรี" in NeedsHandler(PROGRAM, [E1]).opening_message()


def test_a_draft_that_fails_need_validation_is_refused_and_old_drafts_kept() -> None:
    h = NeedsHandler(PROGRAM, [E1, E2])
    h.handle(_save_need())
    before = h.drafts()
    obs = h.handle(_save_need(statement_th=""))
    assert "ระบบปฏิเสธ" in obs
    assert h.drafts() == before
    assert len(h.tool_ctx.needs_by_id) == 1


def _long_evidence() -> StakeholderEvidence:
    return StakeholderEvidence(
        evidence_id="long",
        program_id="p",
        stakeholder_type=StakeholderType.EMPLOYER,
        source_name="ยาว",
        raw_text_th="ก" * 7000,  # two parts at the default 6000-char window
    )


async def test_multi_part_item_is_unread_until_every_part_is_read(
    monkeypatch: pytest.MonkeyPatch, repos: _Repos
) -> None:
    long_ev = _long_evidence()
    monkeypatch.setattr(
        single_needs.EvidenceRepository, "list_by_program", AsyncMock(return_value=[long_ev])
    )

    def read(parts: set[int]) -> Script:
        def script(h: NeedsHandler) -> None:
            assert len(single_needs.evidence_parts(long_ev.raw_text_th, h.tool_ctx.part_chars)) == 2
            h.tool_ctx.read_parts.update(("long", p) for p in parts)
            h.handle(Note(kind="note", evidence_id="long", points_th="จุด"))
            h.handle(_save_need(source_evidence_ids=["long"]))

        return script

    _fake_loop(monkeypatch, read({1}), "finished", ["long"])
    assert (await run_single_needs("p")).unread_evidence_ids == ["long"]
    _fake_loop(monkeypatch, read({1, 2}), "finished", ["long"])
    assert (await run_single_needs("p")).unread_evidence_ids == []


def test_opening_message_carries_the_designer_note_only_when_given() -> None:
    plain = NeedsHandler(PROGRAM, [E1]).opening_message()
    assert plain == NeedsHandler(PROGRAM, [E1], note_th=None).opening_message()
    noted = NeedsHandler(PROGRAM, [E1], note_th="เน้นภาคปฏิบัติ").opening_message()
    assert noted.startswith(plain) and noted.endswith("เน้นภาคปฏิบัติ")


@pytest.mark.asyncio
async def test_run_single_needs_hands_the_note_to_the_opening_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    async def fake(handler: object, *a: object, **k: object) -> object:
        seen.append(handler.opening_message())  # type: ignore[attr-defined]
        raise RuntimeError("stop")

    monkeypatch.setattr(single_needs.ProgramRepository, "get", AsyncMock(return_value=PROGRAM))
    monkeypatch.setattr(
        single_needs.EvidenceRepository, "list_by_program", AsyncMock(return_value=[E1])
    )
    monkeypatch.setattr(single_needs, "run_single_agent", fake)
    with pytest.raises(RuntimeError):
        await run_single_needs("p", note_th="เน้นภาคปฏิบัติ")
    assert seen and seen[0].endswith("เน้นภาคปฏิบัติ")
