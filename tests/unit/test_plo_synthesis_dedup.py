from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from curriculum_agent.graph import AgentState
from curriculum_agent.models import BloomLevel, KSECCategory, Need
from curriculum_agent.stages import need_dedup
from curriculum_agent.stages import plo_synthesis as ps
from curriculum_agent.stages.need_dedup import DedupAnswer, DuplicateGroup, FoldGroup
from tests.support.smart_agent import set_soft_judge

_METADATA = {
    "program_id": "test",
    "field": "CS",
    "degree_level": "bachelor",
    "duration_years": 4,
    "faculty": "Engineering",
    "university": "Test University",
}


def _need(nid: str, demand: float, *, optional: bool = False) -> Need:
    return Need(
        need_id=nid,
        program_id="test",
        statement_th=f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.APPLY,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=demand,
        is_optional=optional,
        in_field_skill_count=1,
        graduate_capability_skill_count=1,
    )


def _fold(*needs: Need) -> FoldGroup:
    return FoldGroup(needs=tuple(ps.synthesis_order(list(needs))), reason_th="งานเดียวกัน")


def _slots(needs: list[Need], folds: list[FoldGroup]) -> list[tuple[str, list[str]]]:
    ordered = ps.synthesis_order(needs)
    slots = ps._select_slots(ps.build_units(ordered, folds))
    return [(s.plo_id, [n.need_id for n in s.needs]) for s in slots]


# --------------------------- units and slot selection ---------------------------


def test_without_folds_every_need_keeps_its_own_slot() -> None:
    needs = [_need("A", 0.9), _need("B", 0.5)]

    assert _slots(needs, []) == [("PLO1", ["A"]), ("PLO2", ["B"])]


def test_a_fold_is_one_slot_with_its_members_in_demand_order() -> None:
    a, b, c = _need("A", 0.9), _need("B", 0.5), _need("C", 0.3)

    assert _slots([a, b, c], [_fold(c, a)]) == [("PLO1", ["A", "C"]), ("PLO2", ["B"])]


def test_a_unit_ranks_by_its_top_member() -> None:
    """A low-demand Need folded into a high-demand one rides at the top."""
    a, b, c = _need("A", 0.2), _need("B", 0.5), _need("C", 0.9)

    assert _slots([a, b, c], [_fold(a, c)])[0] == ("PLO1", ["C", "A"])


def test_a_fold_frees_a_slot_the_next_need_below_the_cut_takes() -> None:
    """Eleven core Needs: without a fold the lowest loses the ceiling cut; with
    the top two folded, it gets the slot the fold freed."""
    needs = [_need(f"N{i:02d}", i / 100) for i in range(1, 12)]

    without = {nid for _, ids in _slots(needs, []) for nid in ids}
    with_fold = _slots(needs, [_fold(needs[10], needs[9])])

    assert "N01" not in without
    assert len(with_fold) == ps.MAX_CORE_PLOS
    assert "N01" in {nid for _, ids in with_fold for nid in ids}


def test_an_optional_need_folded_into_a_core_one_is_core() -> None:
    core, opt = _need("C", 0.5), _need("O", 0.1, optional=True)

    assert _slots([core, opt], [_fold(core, opt)]) == [("PLO1", ["C", "O"])]


def test_two_optional_needs_fold_into_one_optional_slot() -> None:
    o1, o2 = _need("O1", 0.2, optional=True), _need("O2", 0.1, optional=True)

    assert _slots([o1, o2], [_fold(o1, o2)]) == [("OPT1", ["O1", "O2"])]


# --------------------------- the merge floor ---------------------------


def _kept(needs: list[Need], folds: list[FoldGroup]) -> list[list[str]]:
    ordered = ps.synthesis_order(needs)
    return [[n.need_id for n in f.needs] for f in ps.enforce_merge_floor(ordered, folds)]


def test_a_fold_leaving_exactly_the_floor_is_kept() -> None:
    needs = [_need(f"N{i}", i / 10) for i in range(1, 6)]  # 5 core

    assert _kept(needs, [_fold(needs[0], needs[1])]) == [["N2", "N1"]]


def test_a_fold_leaving_less_than_the_floor_is_unfolded() -> None:
    needs = [_need(f"N{i}", i / 10) for i in range(1, 5)]  # 4 core

    assert _kept(needs, [_fold(needs[0], needs[1])]) == []


def test_the_lowest_demand_fold_is_unfolded_first() -> None:
    """Five core Needs, two pair folds → 3 slots. Unfolding one restores 4; it
    is the fold whose top member has the lower demand."""
    needs = [_need(f"N{i}", i / 10) for i in range(1, 6)]
    low = _fold(needs[0], needs[1])  # top demand 0.2
    high = _fold(needs[3], needs[4])  # top demand 0.5

    assert _kept(needs, [low, high]) == [["N5", "N4"]]


def test_a_set_already_below_the_floor_gets_no_core_folds() -> None:
    """Not blocked, just unable to shrink: the fold is unfolded, the set stays at 3."""
    needs = [_need(f"N{i}", i / 10) for i in range(1, 4)]  # 3 core

    assert _kept(needs, [_fold(needs[0], needs[1])]) == []


def test_optional_folds_are_never_unfolded_for_the_floor() -> None:
    core = [_need(f"N{i}", i / 10) for i in range(1, 4)]  # 3 core, below the floor
    o1, o2 = _need("O1", 0.05, optional=True), _need("O2", 0.04, optional=True)
    mixed = _fold(core[0], _need("O3", 0.03, optional=True))

    kept = _kept([*core, o1, o2, mixed.needs[1]], [_fold(o1, o2), mixed])

    assert ["O1", "O2"] in kept, "an all-optional fold does not touch the core count"
    assert ["N1", "O3"] in kept, "an optional-into-core fold does not lower it either"


# --------------------------- run ---------------------------


def _patch_llm(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Drafts keyed by the first Need id in the prompt; records which Needs each
    synthesis call was handed."""
    seen: dict[str, str] = {}

    async def fake_synthesis(model, messages, **kw):  # noqa: ANN001, ANN003
        body = messages[-1]["content"]
        ids = [line.split("need_id: ")[1] for line in body.splitlines() if "need_id: " in line]
        seen[ids[0]] = ",".join(ids)
        return ps._SingleDraftResponse(
            plo=ps._PLODraft(
                statement_th=f"วิเคราะห์งาน {ids[0]} เพื่อเสนอแนวทางแก้ปัญหาได้",
                bloom_level=BloomLevel.ANALYZE,
                action_verb_th="วิเคราะห์",
                source_need_ids=ids,
                rationale_th="ตรงกับความต้องการของตลาด",
            )
        )

    monkeypatch.setattr(ps, "complete_plo_synthesis", fake_synthesis)
    set_soft_judge(monkeypatch)
    monkeypatch.setattr(ps.PLORepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(ps.PLORepository, "bulk_insert", AsyncMock())
    return seen


async def test_run_drafts_one_plo_from_every_member_of_a_fold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    needs = [_need(f"N{i}", i / 10) for i in range(1, 7)]  # 6 core
    _patch_llm(monkeypatch)
    fold = _fold(needs[5], needs[4])
    finder = AsyncMock(return_value=[fold])
    monkeypatch.setattr(ps, "find_duplicate_groups", finder)

    state: AgentState = {
        "program_id": "test",
        "metadata": _METADATA,
        "needs": [n.model_dump(mode="json") for n in needs],
    }
    result = await ps.run(state)

    plos = result["plos"]
    assert len(plos) == 5
    assert plos[0]["plo_id"] == "PLO1"
    assert plos[0]["source_need_ids"] == ["N6", "N5"]
    assert set(plos[0]["source_evidence_ids"]) == {"E-N6", "E-N5"}
    handed = [n.need_id for n in finder.await_args.args[0]]
    assert handed == ["N6", "N5", "N4", "N3", "N2", "N1"], "the finder sees demand order"


async def test_run_logs_the_core_count_before_and_after_folding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    needs = [_need(f"N{i}", i / 10) for i in range(1, 7)]  # 6 core
    _patch_llm(monkeypatch)
    monkeypatch.setattr(
        ps, "find_duplicate_groups", AsyncMock(return_value=[_fold(needs[5], needs[4])])
    )
    logger = Mock()
    monkeypatch.setattr(ps, "logger", logger)

    await ps.run(
        {
            "program_id": "test",
            "metadata": _METADATA,
            "needs": [n.model_dump(mode="json") for n in needs],
        }
    )

    lines = [c.args[0] for c in logger.info.call_args_list]
    assert "need_dedup: 1 fold(s) kept, 0 unfolded for the floor — core PLO slots 6 → 5" in lines


async def test_run_applies_the_floor_to_what_the_finder_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    needs = [_need(f"N{i}", i / 10) for i in range(1, 5)]  # 4 core
    _patch_llm(monkeypatch)
    monkeypatch.setattr(
        ps, "find_duplicate_groups", AsyncMock(return_value=[_fold(needs[3], needs[2])])
    )

    result = await ps.run(
        {
            "program_id": "test",
            "metadata": _METADATA,
            "needs": [n.model_dump(mode="json") for n in needs],
        }
    )

    assert len(result["plos"]) == 4, "folding would leave 3, below the merge floor"


async def test_run_with_dedup_disabled_never_calls_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NEED_DEDUP_PROVIDER="" is the kill switch: find_duplicate_groups returns
    before the model is ever awaited, so every Need keeps its own slot, in
    demand order."""
    needs = [_need(f"N{i}", i / 10) for i in range(1, 4)]  # N3 > N2 > N1 by demand
    _patch_llm(monkeypatch)
    monkeypatch.setattr(ps.settings, "need_dedup_provider", "")
    stub = AsyncMock(
        return_value=DedupAnswer(
            groups=[DuplicateGroup(labels=["N1", "N2"], reason_th="งานเดียวกัน")]
        )
    )
    monkeypatch.setattr(need_dedup, "complete_need_dedup", stub)

    result = await ps.run(
        {
            "program_id": "test",
            "metadata": _METADATA,
            "needs": [n.model_dump(mode="json") for n in needs],
        }
    )

    plos = result["plos"]
    assert [p["plo_id"] for p in plos] == ["PLO1", "PLO2", "PLO3"]
    assert [p["source_need_ids"] for p in plos] == [["N3"], ["N2"], ["N1"]]
    stub.assert_not_awaited()
