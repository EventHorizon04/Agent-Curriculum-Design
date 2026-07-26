from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import BloomLevel, KSECCategory, Need, ProgramMetadata
from curriculum_agent.stages import plo_synthesis as ps


def _need(nid: str, optional: bool = False) -> Need:
    return Need(
        need_id=nid,
        program_id="cs-test",
        statement_th=f"สามารถทำงาน {nid} ตามที่ตลาดต้องการ",
        ksec_category=KSECCategory.SS,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=0.7,
        is_optional=optional,
    )


def _draft(nid: str) -> ps._PLODraft:
    return ps._PLODraft(
        plo_id=f"PLO-{nid}",
        statement_th=f"วิเคราะห์งาน {nid} เพื่อเสนอแนวทางแก้ปัญหาได้",
        bloom_level=BloomLevel.ANALYZE,
        is_subject_specific=True,
        action_verb_th="วิเคราะห์",
        source_need_ids=[nid],
        source_evidence_ids=[f"E-{nid}"],
        rationale_th="ตรงกับความต้องการของตลาด",
    )


@pytest.fixture(autouse=True)
def _no_db(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ps.PLORepository, "bulk_insert", AsyncMock())


def _patch_llm(monkeypatch: pytest.MonkeyPatch, needs: list[Need]) -> AsyncMock:
    drafts = {n.need_id: _draft(n.need_id) for n in needs}
    calls: list[str] = []

    async def fake_heavy(model, messages, **kw):  # noqa: ANN001, ANN003
        body = messages[-1]["content"]
        nid = next(n.need_id for n in needs if n.need_id in body)
        calls.append(nid)
        return ps._SingleDraftResponse(plo=drafts[nid])

    async def fake_light(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SmartSoftJudge(
            specific_object_ok=True, achievable_ok=True, relevant_alignment_ok=True
        )

    monkeypatch.setattr(ps, "complete_heavy", fake_heavy)
    monkeypatch.setattr(ps, "complete_light", fake_light)
    mock = AsyncMock()
    mock.calls = calls  # type: ignore[attr-defined]
    return mock


async def test_each_need_produces_exactly_one_plo(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    needs = [_need("N1"), _need("N2"), _need("N3")]
    _patch_llm(monkeypatch, needs)

    state = await ps.run(
        {
            "program_id": "cs-test",
            "metadata": program_metadata.model_dump(mode="json"),
            "needs": [n.model_dump(mode="json") for n in needs],
        }
    )

    plos = state["plos"]
    assert len(plos) == len(needs)
    assert [p["source_need_ids"] for p in plos] == [["N1"], ["N2"], ["N3"]]


async def test_optional_need_yields_optional_plo(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    needs = [_need("N1"), _need("N2", optional=True)]
    _patch_llm(monkeypatch, needs)

    state = await ps.run(
        {
            "program_id": "cs-test",
            "metadata": program_metadata.model_dump(mode="json"),
            "needs": [n.model_dump(mode="json") for n in needs],
        }
    )

    by_need = {p["source_need_ids"][0]: p for p in state["plos"]}
    assert by_need["N1"]["is_optional"] is False
    assert by_need["N2"]["is_optional"] is True


async def test_no_needs_raises_rather_than_inventing_plos(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    with pytest.raises(ValueError, match="no Needs"):
        await ps.run(
            {
                "program_id": "cs-test",
                "metadata": program_metadata.model_dump(mode="json"),
                "needs": [],
            }
        )


async def test_merging_needs_keeps_every_source_id_and_evidence(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    needs = [_need("N1"), _need("N2")]

    async def fake_heavy(model, messages, **kw):  # noqa: ANN001, ANN003
        # The model omits evidence ids; the Needs' own trail must fill the gap.
        draft = _draft("N1").model_copy(
            update={"source_need_ids": ["N1", "N2"], "source_evidence_ids": []}
        )
        return ps._SingleDraftResponse(plo=draft)

    async def fake_light(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SmartSoftJudge(
            specific_object_ok=True, achievable_ok=True, relevant_alignment_ok=True
        )

    monkeypatch.setattr(ps, "complete_heavy", fake_heavy)
    monkeypatch.setattr(ps, "complete_light", fake_light)

    plo = await ps.synthesize_from_needs(program_metadata, needs, "cs-test", {"N1", "N2"})

    assert plo is not None
    assert plo.source_need_ids == ["N1", "N2"]
    assert set(plo.source_evidence_ids) == {"E-N1", "E-N2"}


async def test_merged_plo_is_optional_only_when_all_sources_are(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    async def fake_heavy(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SingleDraftResponse(
            plo=_draft("N1").model_copy(update={"source_need_ids": ["N1", "N2"]})
        )

    async def fake_light(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SmartSoftJudge(
            specific_object_ok=True, achievable_ok=True, relevant_alignment_ok=True
        )

    monkeypatch.setattr(ps, "complete_heavy", fake_heavy)
    monkeypatch.setattr(ps, "complete_light", fake_light)

    mixed = await ps.synthesize_from_needs(
        program_metadata, [_need("N1"), _need("N2", optional=True)], "cs-test", {"N1", "N2"}
    )
    all_optional = await ps.synthesize_from_needs(
        program_metadata,
        [_need("N1", optional=True), _need("N2", optional=True)],
        "cs-test",
        {"N1", "N2"},
    )

    assert mixed is not None and mixed.is_optional is False
    assert all_optional is not None and all_optional.is_optional is True


async def test_synthesize_returns_none_when_the_model_fails(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    async def boom(model, messages, **kw):  # noqa: ANN001, ANN003
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(ps, "complete_heavy", boom)
    result = await ps.synthesize_from_needs(program_metadata, [_need("N1")], "cs-test", {"N1"})
    assert result is None


async def test_synthesize_rejects_an_empty_need_list(program_metadata: ProgramMetadata):
    with pytest.raises(ValueError, match="at least one Need"):
        await ps.synthesize_from_needs(program_metadata, [], "cs-test", set())
