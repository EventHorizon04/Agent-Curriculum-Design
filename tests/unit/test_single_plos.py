from __future__ import annotations

import itertools
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from curriculum_agent.models import (
    BloomLevel,
    Need,
    ProgramMetadata,
    StakeholderEvidence,
    StakeholderType,
)
from curriculum_agent.stages import single_plos
from curriculum_agent.stages.single_agent_loop import (
    DropPLO,
    LoopOutcome,
    Note,
    SaveNeed,
    SavePLO,
    StopReason,
)
from curriculum_agent.stages.single_plos import (
    PlosHandler,
    build_single_plo,
    run_single_plos,
    select_single_input,
)

PROGRAM = ProgramMetadata(
    program_id="p",
    university="ม",
    faculty="ค",
    field="การแปล",
    degree_level="bachelor",
    duration_years=4,
)

_ids = itertools.count(1)


def _need(
    need_id: str | None = None,
    *,
    score: float = 0.5,
    optional: bool = False,
    evidence: list[str] | None = None,
    statement: str = "ต้องการบัณฑิตที่แปลเอกสารธุรกิจได้",
    **extra: Any,
) -> Need:
    nid = need_id or f"auto{next(_ids)}"
    return Need(
        need_id=nid,
        program_id="p",
        statement_th=statement,
        ksec_categories=["S"],
        bloom_level=BloomLevel.APPLY,
        source_evidence_ids=evidence or [f"ev-{nid}"],
        freq=1,
        demand_score=score,
        is_optional=optional,
        origin="single",
        **extra,
    )


N1 = _need("n1", score=0.9, evidence=["e1", "e2"])
N2 = _need("n2", score=0.8, evidence=["e2", "e3"])
N3 = _need("n3", score=0.3, optional=True, evidence=["e4"])
NEEDS = {n.need_id: n for n in (N1, N2, N3)}
EVIDENCE = [
    StakeholderEvidence(
        evidence_id=i,
        program_id="p",
        stakeholder_type=StakeholderType.EMPLOYER,
        source_name="แหล่ง",
        raw_text_th="ข้อความ",
    )
    for i in ("e1", "e2", "e3", "e4")
]


def _all_ok(**over: Any) -> dict[str, Any]:
    soft: dict[str, Any] = {
        "specific_object_ok": True,
        "measurable_ok": True,
        "achievable_ok": True,
        "actor_ok": True,
        "scope_ok": True,
        "relevant_needs_ok": True,
        "time_bound_ok": True,
        "findings_th": {},
    }
    soft.update(over)
    return soft


def _save_plo(
    *,
    plo_ref: str | None = None,
    statement_th: str = "แปลเอกสารธุรกิจระหว่างประเทศ",
    action_verb_th: str = "แปล",
    source_need_ids: list[str] | None = None,
    soft: dict[str, Any] | None = None,
) -> SavePLO:
    return SavePLO.model_validate(
        {
            "kind": "save_plo",
            "plo_ref": plo_ref,
            "statement_th": statement_th,
            "action_verb_th": action_verb_th,
            "bloom_level": "apply",
            "source_need_ids": source_need_ids or ["n1"],
            "rationale_th": "เหตุผล",
            "soft": soft or _all_ok(),
        }
    )


def _handler(
    core: list[Need] | None = None,
    optional: list[Need] | None = None,
    unused: list[Need] | None = None,
) -> PlosHandler:
    return PlosHandler(
        PROGRAM,
        core if core is not None else [N1, N2],
        optional if optional is not None else [N3],
        unused or [],
        EVIDENCE,
        None,
    )


# ---- selection ----------------------------------------------------------


def test_select_takes_ten_highest_core_and_names_the_rest() -> None:
    core, optional, unused = select_single_input(
        [_need(score=i / 20) for i in range(12)] + [_need(optional=True)]
    )
    assert len(core) == 10 and len(unused) == 2 and len(optional) == 1
    assert min(n.demand_score for n in core) > max(n.demand_score for n in unused)


def test_select_skips_merged_away_excluded_and_unwritten_needs() -> None:
    good = _need("good")
    core, optional, unused = select_single_input(
        [
            good,
            _need("merged", merged_into="x"),
            _need("excluded", excluded_at=datetime(2026, 1, 1, tzinfo=UTC)),
            _need("marker", statement="[ต้องทบทวน] รายการทักษะ"),
        ]
    )
    assert [n.need_id for n in core] == ["good"] and optional == [] and unused == []


# ---- handler ------------------------------------------------------------


def test_need_behind_two_plos_is_refused() -> None:
    h = _handler()
    h.handle(_save_plo(source_need_ids=["n1"]))
    obs = h.handle(_save_plo(source_need_ids=["n1", "n2"]))
    assert "n1" in obs and "อยู่เบื้องหลัง PLO อื่นแล้ว" in obs and len(h.drafts()) == 1


def test_need_outside_the_input_is_refused() -> None:
    h = _handler(unused=[_need("lost")])
    assert "ระบบปฏิเสธ" in h.handle(_save_plo(source_need_ids=["lost"]))
    assert "ghost" in h.handle(_save_plo(source_need_ids=["ghost"]))
    assert h.drafts() == []


def test_save_observation_reports_hard_failures() -> None:
    obs = _handler().handle(
        _save_plo(statement_th="มีความสามารถวิเคราะห์ข้อมูล", action_verb_th="วิเคราะห์")
    )
    assert "S_verb" in obs


def test_a_draft_the_plo_model_rejects_is_refused_and_drafts_kept() -> None:
    # A Need with no evidence trail makes PLO.check_evidence fail for real.
    bare = Need.model_construct(**{**N2.model_dump(), "source_evidence_ids": []})
    h = PlosHandler(PROGRAM, [N1, bare], [N3], [], EVIDENCE, None)
    h.handle(_save_plo(source_need_ids=["n1"]))
    before = h.drafts()
    obs = h.handle(_save_plo(source_need_ids=["n2"]))
    assert "ระบบปฏิเสธ" in obs and "ไม่ผ่านการตรวจรูปแบบ" in obs
    assert h.drafts() == before and len(h.tool_ctx.plos) == 1


def test_forbidden_word_draft_is_accepted_and_the_hard_failure_reported() -> None:
    h = _handler()
    obs = h.handle(_save_plo(statement_th="เข้าใจหลักการแปล", action_verb_th="เข้าใจ"))
    assert "ระบบปฏิเสธ" not in obs and "M_forbidden" in obs
    assert len(h.drafts()) == 1 and len(h.tool_ctx.plos) == 1


def test_repeated_need_ids_in_one_draft_are_deduplicated() -> None:
    h = _handler()
    h.handle(_save_plo(source_need_ids=["n1", "n1", "n2"]))
    assert h.drafts()[0].source_need_ids == ["n1", "n2"]


def test_save_observation_says_when_the_hard_check_passes() -> None:
    assert "ผ่าน hard check" in _handler().handle(_save_plo())


def test_save_mints_refs_and_resave_replaces() -> None:
    h = _handler()
    h.handle(_save_plo(source_need_ids=["n1"]))
    h.handle(_save_plo(source_need_ids=["n2"]))
    assert [d.plo_ref for d in h.drafts()] == ["d1", "d2"]
    h.handle(_save_plo(plo_ref="d1", statement_th="แปลสัญญาธุรกิจ", source_need_ids=["n1"]))
    assert len(h.drafts()) == 2 and h.drafts()[0].statement_th == "แปลสัญญาธุรกิจ"


def test_unknown_ref_is_refused() -> None:
    h = _handler()
    assert "ระบบปฏิเสธ" in h.handle(_save_plo(plo_ref="zz"))
    assert h.drafts() == []


def test_resave_with_own_ref_may_keep_its_needs() -> None:
    h = _handler()
    h.handle(_save_plo(source_need_ids=["n1"]))
    obs = h.handle(_save_plo(plo_ref="d1", source_need_ids=["n1", "n2"]))
    assert "ระบบปฏิเสธ" not in obs and h.drafts()[0].source_need_ids == ["n1", "n2"]


def test_drop_removes_the_draft_and_the_sibling_row() -> None:
    h = _handler()
    h.handle(_save_plo())
    assert [s.plo_id for s in h.tool_ctx.plos] == ["d1"]
    h.handle(DropPLO(kind="drop_plo", plo_ref="d1"))
    assert h.drafts() == [] and h.tool_ctx.plos == []
    assert "ระบบปฏิเสธ" in h.handle(DropPLO(kind="drop_plo", plo_ref="d1"))


def test_siblings_follow_saves() -> None:
    h = _handler()
    h.handle(_save_plo(source_need_ids=["n1"]))
    h.handle(_save_plo(source_need_ids=["n3"]))
    rows = {s.plo_id: s for s in h.tool_ctx.plos}
    assert rows["d1"].is_optional is False and rows["d2"].is_optional is True
    assert rows["d1"].source_need_ids == ["n1"]


def test_need_actions_are_refused_and_note_is_accepted() -> None:
    h = _handler()
    need = SaveNeed.model_validate(
        {
            "kind": "save_need",
            "statement_th": "x",
            "ksec_categories": ["S"],
            "bloom_level": "apply",
            "source_evidence_ids": ["e1"],
        }
    )
    assert "ระบบปฏิเสธ" in h.handle(need)
    assert "ระบบปฏิเสธ" not in h.handle(Note(kind="note", evidence_id="e1", points_th="x"))


def test_opening_message_lists_needs_and_the_note() -> None:
    h = PlosHandler(PROGRAM, [N1], [N3], [_need("lost")], EVIDENCE, "ขอให้กระชับ")
    msg = h.opening_message()
    assert "n1" in msg and "n3" in msg and "lost" in msg and "ขอให้กระชับ" in msg
    assert "4 ปี" in msg


# ---- build_single_plo ---------------------------------------------------


def test_hard_failure_escalates_whatever_the_agent_claimed() -> None:
    plo = build_single_plo(
        "p",
        "PLO1",
        _save_plo(statement_th="เข้าใจหลักการแปล", action_verb_th="เข้าใจ", soft=_all_ok()),
        NEEDS,
        is_optional=False,
    )
    assert plo.smart_escalated is True and plo.smart_validated_by == "single_agent"
    assert plo.smart_check.specific is True  # opens with the declared verb
    assert plo.smart_check.measurable is False
    assert {f.criterion.value for f in plo.smart_check.hard_findings} == {"M_forbidden"}


def test_soft_verdicts_become_flags_and_findings() -> None:
    plo = build_single_plo(
        "p",
        "PLO1",
        _save_plo(soft=_all_ok(actor_ok=False, findings_th={"A_actor": "ผู้กระทำคือสถาบัน"})),
        NEEDS,
        is_optional=False,
    )
    assert plo.soft_flags == ["A_actor"]
    assert plo.smart_check.achievable is False and plo.smart_escalated is False
    (finding,) = plo.smart_check.findings
    assert finding.note_th == "ผู้กระทำคือสถาบัน" and finding.severity == "soft"


def test_soft_finding_falls_back_to_the_label() -> None:
    plo = build_single_plo(
        "p", "PLO1", _save_plo(soft=_all_ok(time_bound_ok=False)), NEEDS, is_optional=False
    )
    assert plo.soft_flags == ["T_horizon"] and plo.smart_check.timely is False
    assert plo.smart_check.findings[0].note_th


def test_evidence_trail_is_the_union_of_the_cited_needs() -> None:
    plo = build_single_plo(
        "p", "PLO1", _save_plo(source_need_ids=["n1", "n2"]), NEEDS, is_optional=False
    )
    assert sorted(plo.source_evidence_ids) == ["e1", "e2", "e3"]
    assert plo.source_need_ids == ["n1", "n2"] and plo.smart_retry_count == 0


def test_subject_prefix_is_stripped_but_a_designer_edit_is_kept() -> None:
    draft = _save_plo(statement_th="บัณฑิตสามารถแปลเอกสาร")
    assert build_single_plo("p", "PLO1", draft, NEEDS, is_optional=False).statement_th == (
        "แปลเอกสาร"
    )
    kept = build_single_plo(
        "p",
        "PLO1",
        draft,
        NEEDS,
        is_optional=False,
        designer_edited_at=datetime(2026, 1, 1),
    )
    assert kept.statement_th == "บัณฑิตสามารถแปลเอกสาร" and kept.designer_edited_at is not None


# ---- the runner ---------------------------------------------------------


class _Repos:
    def __init__(self) -> None:
        self.replace = AsyncMock(return_value=0)


@pytest.fixture
def repos(monkeypatch: pytest.MonkeyPatch) -> _Repos:
    r = _Repos()
    monkeypatch.setattr(single_plos.ProgramRepository, "get", AsyncMock(return_value=PROGRAM))
    monkeypatch.setattr(
        single_plos.EvidenceRepository, "list_by_program", AsyncMock(return_value=EVIDENCE)
    )
    monkeypatch.setattr(
        single_plos.NeedRepository,
        "list_active_by_program",
        AsyncMock(return_value=[N1, N2, N3]),
    )
    monkeypatch.setattr(single_plos.PLORepository, "replace_by_program", r.replace)
    return r


def _fake_loop(
    monkeypatch: pytest.MonkeyPatch, script: Callable[[PlosHandler], None], reason: StopReason
) -> None:
    async def fake(handler: Any) -> LoopOutcome:
        script(handler)
        return LoopOutcome(
            stop_reason=reason, turns=4, dropped_evidence_count=2, opened_evidence_ids=["e1"]
        )

    monkeypatch.setattr(single_plos, "run_single_agent", fake)


async def test_run_numbers_core_and_optional_separately_and_stores(
    monkeypatch: pytest.MonkeyPatch, repos: _Repos
) -> None:
    def script(h: PlosHandler) -> None:
        # Saved lower-demand first: numbering follows demand, not save order.
        h.handle(_save_plo(source_need_ids=["n2"], statement_th="แปลสัญญา"))
        h.handle(_save_plo(source_need_ids=["n3"], statement_th="แปลบทคัดย่อ"))
        h.handle(_save_plo(source_need_ids=["n1"], statement_th="แปลรายงาน"))

    _fake_loop(monkeypatch, script, "finished")
    res = await run_single_plos("p")
    by_id = {p.plo_id: p for p in res.plos}
    assert set(by_id) == {"PLO1", "PLO2", "OPT1"}
    assert by_id["PLO1"].source_need_ids == ["n1"] and by_id["PLO2"].source_need_ids == ["n2"]
    assert by_id["OPT1"].is_optional is True and by_id["PLO1"].is_optional is False
    assert res.stop_reason == "finished" and res.turns == 4 and res.uncited_core_need_ids == []
    assert res.dropped_evidence_count == 2 and res.opened_evidence_ids == ["e1"]
    repos.replace.assert_awaited_once()
    assert repos.replace.await_args.args == ("p", res.plos)


async def test_partial_result_is_stored_on_any_stop_reason(
    monkeypatch: pytest.MonkeyPatch, repos: _Repos
) -> None:
    _fake_loop(monkeypatch, lambda h: h.handle(_save_plo(source_need_ids=["n1"])), "malformed")
    res = await run_single_plos("p")
    assert res.stop_reason == "malformed" and res.uncited_core_need_ids == ["n2"]
    repos.replace.assert_awaited_once()


async def test_no_drafts_fails_and_touches_nothing(
    monkeypatch: pytest.MonkeyPatch, repos: _Repos
) -> None:
    _fake_loop(monkeypatch, lambda h: None, "timeout")
    with pytest.raises(HTTPException) as exc:
        await run_single_plos("p")
    assert exc.value.status_code == 502 and "timeout" in exc.value.detail
    repos.replace.assert_not_awaited()


async def test_no_active_needs_is_422_before_the_loop(
    monkeypatch: pytest.MonkeyPatch, repos: _Repos
) -> None:
    monkeypatch.setattr(
        single_plos.NeedRepository, "list_active_by_program", AsyncMock(return_value=[])
    )
    loop = AsyncMock()
    monkeypatch.setattr(single_plos, "run_single_agent", loop)
    with pytest.raises(HTTPException) as exc:
        await run_single_plos("p")
    assert exc.value.status_code == 422
    loop.assert_not_awaited()


async def test_missing_program_is_404(monkeypatch: pytest.MonkeyPatch, repos: _Repos) -> None:
    monkeypatch.setattr(single_plos.ProgramRepository, "get", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as exc:
        await run_single_plos("p")
    assert exc.value.status_code == 404
