# tests/unit/test_plo_synthesis_guard.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from curriculum_agent.graph import AgentState
from curriculum_agent.models import BloomLevel, KSECCategory, Need
from curriculum_agent.stages import plo_synthesis as ps
from curriculum_agent.stages.plo_synthesis import run
from tests.support.smart_agent import set_soft_judge

_METADATA = {
    "program_id": "test",
    "name_th": "วิทยาการคอมพิวเตอร์",
    "name_en": "Computer Science",
    "field": "CS",
    "degree_level": "bachelor",
    "duration_years": 4,
    "faculty": "Engineering",
    "university": "Test University",
    "program_goals_th": ["เป้าหมายหลักสูตรที่ 1"],
    "program_objectives_th": ["objective 1"],
}


async def test_run_raises_when_needs_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty list is need_combination's answer, and the message says so.

    It must not send the designer to re-run need_combination — that stage ran and
    reported honestly — and it must not fall back to the stored Needs, which
    would synthesise PLOs from rows this run did not produce.
    """
    loader = AsyncMock(return_value=[_need("N1")])
    monkeypatch.setattr(ps.NeedRepository, "list_by_program", loader)

    state: AgentState = {
        "program_id": "test",
        "needs": [],
        "metadata": _METADATA,
    }
    with pytest.raises(ValueError, match="need_combination"):
        await run(state)

    loader.assert_not_awaited()


async def test_run_reads_stored_needs_when_the_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing key means the stage was entered directly, not that there is
    nothing to synthesise — the stored set is what POST /plos/run would have
    handed over, so the graph reads the same thing."""
    needs = [_need("N1")]
    _patch_llm(monkeypatch, needs)
    loader = AsyncMock(return_value=needs)
    monkeypatch.setattr(ps.NeedRepository, "list_by_program", loader)

    state: AgentState = {"program_id": "test", "metadata": _METADATA}
    result = await run(state)

    loader.assert_awaited_once_with("test")
    assert len(result["plos"]) == 1


async def test_run_raises_when_nothing_is_stored_either(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing in state and nothing on record: the Needs stage has to run."""
    monkeypatch.setattr(ps.NeedRepository, "list_by_program", AsyncMock(return_value=[]))

    state: AgentState = {"program_id": "test", "metadata": _METADATA}
    with pytest.raises(ValueError, match="ยังไม่มี Need"):
        await run(state)


# --------------------------- scope filter ---------------------------
#
# The filter sits before the series split and before the ceiling. Both positions
# are load-bearing and neither shows up in the output of a single-Need run, so
# these drive the whole stage.


def _need(
    nid: str,
    *,
    demand: float = 0.7,
    optional: bool = False,
    in_scope: bool = True,
) -> Need:
    return Need(
        need_id=nid,
        program_id="test",
        statement_th=f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=demand,
        is_optional=optional,
        in_field_skill_count=1 if in_scope else 0,
        graduate_capability_skill_count=1 if in_scope else 0,
    )


def _patch_llm(monkeypatch: pytest.MonkeyPatch, needs: list[Need]) -> None:
    drafts = {
        n.need_id: ps._PLODraft(
            statement_th=f"วิเคราะห์งาน {n.need_id} เพื่อเสนอแนวทางแก้ปัญหาได้",
            bloom_level=BloomLevel.ANALYZE,
            action_verb_th="วิเคราะห์",
            source_need_ids=[n.need_id],
            rationale_th="ตรงกับความต้องการของตลาด",
        )
        for n in needs
    }

    async def fake_synthesis(model, messages, **kw):  # noqa: ANN001, ANN003
        # Match the whole "need_id: <id>" line: "N1" is a substring of "N10", and
        # a substring match would hand N10's prompt N1's draft.
        body = messages[-1]["content"]
        nid = next(n.need_id for n in needs if f"need_id: {n.need_id}\n" in body)
        return ps._SingleDraftResponse(plo=drafts[nid])

    monkeypatch.setattr(ps, "complete_plo_synthesis", fake_synthesis)
    set_soft_judge(monkeypatch)
    monkeypatch.setattr(ps.PLORepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(ps.PLORepository, "bulk_insert", AsyncMock())


async def _run(needs: list[Need], monkeypatch: pytest.MonkeyPatch) -> AgentState:
    _patch_llm(monkeypatch, needs)
    return await ps.run(
        {
            "program_id": "test",
            "metadata": _METADATA,
            "needs": [n.model_dump(mode="json") for n in needs],
        }
    )


async def test_out_of_scope_needs_do_not_occupy_slots_under_the_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single most important consequence of filtering before the ceiling.

    Twelve Needs, the two highest-scoring of them out of scope. Filter first and
    the ceiling picks ten out of ten survivors. Filter after the ceiling and the
    top ten still contains those two, they are dropped afterwards, and the program
    ends up with eight PLOs while in-scope Needs sat unused at the back of the
    queue — under the floor, for a reason no log line would explain.
    """
    needs = [_need(f"N{i:02d}", demand=i / 100) for i in range(1, 11)]
    needs += [_need(f"X{i}", demand=0.99, in_scope=False) for i in (1, 2)]

    state = await _run(needs, monkeypatch)

    assert len(state["plos"]) == 10
    used = {nid for p in state["plos"] for nid in p["source_need_ids"]}
    assert used == {n.need_id for n in needs if n.need_id.startswith("N")}


async def test_the_ceiling_then_picks_the_highest_demand_survivors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With more in-scope Needs than the ceiling allows, the cut is made among the
    survivors by demand — the out-of-scope pair is not what the ceiling counts,
    even though it scores highest of all."""
    needs = [_need(f"N{i:02d}", demand=i / 100) for i in range(1, 13)]
    needs += [_need(f"X{i}", demand=0.99, in_scope=False) for i in (1, 2)]

    state = await _run(needs, monkeypatch)

    assert len(state["plos"]) == ps.MAX_CORE_PLOS == 10
    used = {nid for p in state["plos"] for nid in p["source_need_ids"]}
    assert used == {f"N{i:02d}" for i in range(3, 13)}  # N01 and N02 score lowest


async def test_a_filtered_need_does_not_leave_a_gap_in_the_numbering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gap already means "this Need was drafted and the model failed". Giving it
    a second meaning makes both unreadable. A filtered Need is in the same
    position as one that lost the ceiling cut — not chosen, not broken — and the
    ceiling does not consume numbers either."""
    needs = [
        _need("N1", demand=0.5),
        _need("X1", demand=0.9, in_scope=False),
        _need("N2", demand=0.4),
        _need("X2", demand=0.8, in_scope=False),
        _need("N3", demand=0.3),
    ]

    state = await _run(needs, monkeypatch)

    assert [p["plo_id"] for p in state["plos"]] == ["PLO1", "PLO2", "PLO3"]


async def test_an_out_of_scope_optional_need_is_filtered_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off-field is off-field whether the outcome is core or supplementary, which
    is why the filter sits before the two series are split rather than inside the
    core branch."""
    needs = [
        _need("N1"),
        _need("O1", optional=True),
        _need("O2", optional=True, in_scope=False),
    ]

    state = await _run(needs, monkeypatch)

    optional = [p for p in state["plos"] if p["is_optional"]]
    assert [p["source_need_ids"] for p in optional] == [["O1"]]
    assert [p["plo_id"] for p in optional] == ["OPT1"]


async def test_the_filter_warning_reports_the_two_axes_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two figures will usually be equal, which sounds like a reason to print
    one. It is the reverse: the day they disagree is the day the two axes have
    started measuring different things, and this line is the only place that shows
    up without running an eval. One combined number loses the signal for good.
    """
    off_field_only = _need("X1").model_copy(update={"in_field_skill_count": 0})
    off_grad_only = _need("X2").model_copy(update={"graduate_capability_skill_count": 0})
    needs = [_need("N1"), off_field_only, off_grad_only]

    with patch.object(ps, "logger") as mock_logger:
        await _run(needs, monkeypatch)

    (line,) = [
        c.args[0] for c in mock_logger.warning.call_args_list if c.args[0].startswith("Stage 4: ")
    ]
    assert "นอกสาขา 1" in line
    assert "ไม่ใช่สมรรถนะบัณฑิต 1" in line
    assert "X1" in line and "X2" in line


async def test_filtering_past_the_floor_still_synthesizes_and_says_why_on_one_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Topping the set back up with out-of-scope Needs would be manufacturing PLOs
    already known to be wrong so that a count looks right.

    The cause belongs on the floor warning itself: "not enough in-scope evidence"
    and "too few Needs to begin with" are different problems with different fixes,
    and need_combination's own warning about the second one is somewhere else
    entirely in the log.
    """
    needs = [_need(f"N{i}") for i in range(1, 4)]
    needs += [_need(f"X{i}", in_scope=False) for i in range(1, 6)]

    with patch.object(ps, "logger") as mock_logger:
        state = await _run(needs, monkeypatch)

    assert len(state["plos"]) == 3
    (floor,) = [c.args[0] for c in mock_logger.warning.call_args_list if "core PLOs" in c.args[0]]
    assert "3 core PLOs" in floor
    assert "หลักฐานในขอบเขตไม่พอ" in floor
    assert "5" in floor


async def test_the_floor_warning_keeps_its_old_cause_when_nothing_was_filtered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A program that simply produced too few Needs must not be told its evidence
    was out of scope."""
    needs = [_need(f"N{i}") for i in range(1, 4)]

    with patch.object(ps, "logger") as mock_logger:
        await _run(needs, monkeypatch)

    (floor,) = [c.args[0] for c in mock_logger.warning.call_args_list if "core PLOs" in c.args[0]]
    assert "need_combination should have enforced this" in floor
    assert "หลักฐานในขอบเขตไม่พอ" not in floor


async def test_a_filtered_need_is_left_stored_rather_than_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not chosen, not removed. It still traces to its evidence, it is still there
    for the designer to look at, and the merge route can still be pointed at it."""
    needs = [_need("N1"), _need("X1", in_scope=False)]

    state = await _run(needs, monkeypatch)

    assert [n["need_id"] for n in state["needs"]] == ["N1", "X1"]


async def test_a_program_that_wrote_no_scope_statement_loses_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard has no "does this program have a scope statement?" branch and
    must not need one: with no statement every skill row keeps its default flags,
    every counter equals the member count, and the filter passes everything."""
    needs = [
        Need(
            need_id=f"N{i}",
            program_id="test",
            statement_th=f"ต้องการบัณฑิตที่ทำงาน N{i} ในสถานประกอบการจริงได้",
            ksec_category=KSECCategory.S,
            bloom_level=BloomLevel.ANALYZE,
            member_skill_ids=[f"S-N{i}"],
            source_evidence_ids=[f"E-N{i}"],
            freq=1,
            demand_score=0.7,
        )
        for i in range(1, 7)
    ]

    with patch.object(ps, "logger") as mock_logger:
        state = await _run(needs, monkeypatch)

    assert len(state["plos"]) == 6
    assert [c.args[0] for c in mock_logger.warning.call_args_list if "นอกขอบเขต" in c.args[0]] == []
