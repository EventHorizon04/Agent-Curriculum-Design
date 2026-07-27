"""PLO identifiers are assigned by code, not invented by the model.

The prompt used to ask each per-Need call for a `plo_id`. Because every Need gets
its own call with no knowledge of the others, each call plausibly answered
"PLO1" — and `plo_id` is the primary key while the repository upserts, so a set
of eight outcomes could collapse into one row while the run reported success.
The fallback for a missing id was a random uuid fragment, so ids were also
unciteable and unsortable.

These tests pin the replacement: PLO1..PLOn by descending demand for the main
set, a separate OPT1..OPTn series for supplementary outcomes, and no `plo_id`
field on the draft schema at all.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import BloomLevel, KSECCategory, Need, ProgramMetadata
from curriculum_agent.stages import plo_synthesis as ps


def _need(nid: str, demand: float, *, optional: bool = False) -> Need:
    return Need(
        need_id=nid,
        program_id="cs-test",
        statement_th=f"ตลาดต้องการความสามารถ {nid}",
        ksec_category=KSECCategory.SS,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=demand,
        is_optional=optional,
    )


def test_draft_schema_has_no_plo_id_for_the_model_to_fill():
    assert "plo_id" not in ps._PLODraft.model_fields


def test_format_plo_id_uses_separate_series_per_kind():
    assert ps.format_plo_id(1, is_optional=False) == "PLO1"
    assert ps.format_plo_id(7, is_optional=False) == "PLO7"
    assert ps.format_plo_id(1, is_optional=True) == "OPT1"


def test_synthesis_order_is_most_demanded_first():
    ordered = ps.synthesis_order([_need("N1", 0.4), _need("N2", 0.9), _need("N3", 0.7)])
    assert [n.need_id for n in ordered] == ["N2", "N3", "N1"]


def test_synthesis_order_breaks_ties_reproducibly():
    tied = [_need("Nb", 0.5), _need("Na", 0.5)]
    assert [n.need_id for n in ps.synthesis_order(tied)] == ["Na", "Nb"]
    # Same input in the other order must still number the same way, or a re-run
    # would silently change what PLO2 refers to.
    assert [n.need_id for n in ps.synthesis_order(list(reversed(tied)))] == ["Na", "Nb"]


def test_next_plo_id_fills_the_lowest_free_number():
    assert ps.next_plo_id([], is_optional=False) == "PLO1"
    assert ps.next_plo_id(["PLO1", "PLO2"], is_optional=False) == "PLO3"
    assert ps.next_plo_id(["PLO1", "PLO3"], is_optional=False) == "PLO2"


def test_next_plo_id_keeps_the_two_series_independent():
    existing = ["PLO1", "PLO2", "OPT1"]
    assert ps.next_plo_id(existing, is_optional=False) == "PLO3"
    assert ps.next_plo_id(existing, is_optional=True) == "OPT2"


def test_next_plo_id_ignores_ids_it_does_not_recognise():
    # Hand-edited or legacy ids must not make the allocator skip or crash.
    assert ps.next_plo_id(["PLO-abc123", "PLOx", "PLO"], is_optional=False) == "PLO1"


@pytest.fixture(autouse=True)
def _no_db(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ps.PLORepository, "bulk_insert", AsyncMock())


def _patch_model(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_heavy(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SingleDraftResponse(
            plo=ps._PLODraft(
                statement_th="วิเคราะห์ข้อมูลเพื่อเสนอแนวทางแก้ปัญหาได้",
                bloom_level=BloomLevel.ANALYZE,
                action_verb_th="วิเคราะห์",
                source_need_ids=["placeholder"],
                rationale_th="ตรงกับความต้องการของตลาด",
            )
        )

    async def fake_light(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SmartSoftJudge(
            specific_object_ok=True, achievable_ok=True, relevant_alignment_ok=True
        )

    monkeypatch.setattr(ps, "complete_heavy", fake_heavy)
    monkeypatch.setattr(ps, "complete_light", fake_light)


async def test_run_numbers_main_plos_by_descending_demand(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    _patch_model(monkeypatch)
    needs = [_need("Nlow", 0.3), _need("Nhigh", 0.95), _need("Nmid", 0.6)]

    state = await ps.run(
        {
            "program_id": "cs-test",
            "metadata": program_metadata.model_dump(mode="json"),
            "needs": [n.model_dump(mode="json") for n in needs],
        }
    )

    by_id = {p["plo_id"]: p["source_need_ids"][0] for p in state["plos"]}
    assert by_id == {"PLO1": "Nhigh", "PLO2": "Nmid", "PLO3": "Nlow"}


async def test_run_gives_ids_that_are_unique_and_would_not_overwrite_each_other(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    """The original defect: every call answered "PLO1" and the upsert collapsed them."""
    _patch_model(monkeypatch)
    needs = [_need(f"N{i}", 0.9 - i / 100) for i in range(8)]

    state = await ps.run(
        {
            "program_id": "cs-test",
            "metadata": program_metadata.model_dump(mode="json"),
            "needs": [n.model_dump(mode="json") for n in needs],
        }
    )

    ids = [p["plo_id"] for p in state["plos"]]
    assert len(ids) == 8
    assert len(set(ids)) == 8, f"duplicate plo_id would silently overwrite: {ids}"
    assert ids == [f"PLO{i}" for i in range(1, 9)]


async def test_run_numbers_optional_plos_in_their_own_series(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    _patch_model(monkeypatch)
    needs = [
        _need("Ncore1", 0.9),
        _need("Nopt1", 0.8, optional=True),
        _need("Ncore2", 0.7),
        _need("Nopt2", 0.2, optional=True),
    ]

    state = await ps.run(
        {
            "program_id": "cs-test",
            "metadata": program_metadata.model_dump(mode="json"),
            "needs": [n.model_dump(mode="json") for n in needs],
        }
    )

    by_need = {p["source_need_ids"][0]: p["plo_id"] for p in state["plos"]}
    assert by_need == {
        "Ncore1": "PLO1",
        "Ncore2": "PLO2",
        "Nopt1": "OPT1",
        "Nopt2": "OPT2",
    }


async def test_a_failed_need_leaves_a_gap_rather_than_renumbering(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    """Renumbering would change what PLO2 means between runs; designers cite these."""

    async def fake_light(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SmartSoftJudge(
            specific_object_ok=True, achievable_ok=True, relevant_alignment_ok=True
        )

    async def flaky_heavy(model, messages, **kw):  # noqa: ANN001, ANN003
        if "Nmid" in messages[-1]["content"]:
            raise RuntimeError("model unavailable for this one")
        return ps._SingleDraftResponse(
            plo=ps._PLODraft(
                statement_th="วิเคราะห์ข้อมูลเพื่อเสนอแนวทางแก้ปัญหาได้",
                bloom_level=BloomLevel.ANALYZE,
                action_verb_th="วิเคราะห์",
                source_need_ids=["placeholder"],
                rationale_th="ตรงกับความต้องการของตลาด",
            )
        )

    monkeypatch.setattr(ps, "complete_heavy", flaky_heavy)
    monkeypatch.setattr(ps, "complete_light", fake_light)

    needs = [_need("Nhigh", 0.9), _need("Nmid", 0.6), _need("Nlow", 0.3)]
    state = await ps.run(
        {
            "program_id": "cs-test",
            "metadata": program_metadata.model_dump(mode="json"),
            "needs": [n.model_dump(mode="json") for n in needs],
        }
    )

    by_id = {p["plo_id"]: p["source_need_ids"][0] for p in state["plos"]}
    assert by_id == {"PLO1": "Nhigh", "PLO3": "Nlow"}, "PLO2 must stay unused, not be reassigned"
