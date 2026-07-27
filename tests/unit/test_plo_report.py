from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from curriculum_agent.models import (
    PLO,
    BloomLevel,
    KSECCategory,
    Need,
    SMARTCheck,
)

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)


def _plo(need_ids: list[str]) -> dict:
    return PLO(
        plo_id="PLO1",
        program_id="prog-1",
        statement_th="ออกแบบและพัฒนาระบบซอฟต์แวร์",
        bloom_level=BloomLevel.CREATE,
        is_subject_specific=False,
        action_verb_th="ออกแบบ",
        smart_check=_SMART,
        source_need_ids=need_ids,
        source_evidence_ids=["ev-1"],
        rationale_th="เหตุผล",
    ).model_dump(mode="json")


def _need(nid: str, ksec: KSECCategory) -> Need:
    return Need(
        need_id=nid,
        program_id="prog-1",
        statement_th="ทักษะ",
        statement_en="Skill",
        ksec_category=ksec,
        bloom_level=BloomLevel.APPLY,
        member_skill_ids=["s1"],
        source_evidence_ids=["ev-1"],
        freq=1,
        demand_score=0.5,
    )


def _patch_ctx(needs, light_mock):
    need_repo = AsyncMock()
    need_repo.list_by_program = AsyncMock(return_value=needs)
    plo_repo = AsyncMock()
    plo_repo.bulk_insert = AsyncMock()
    return (
        patch("curriculum_agent.stages.plo_report.NeedRepository", return_value=need_repo),
        patch("curriculum_agent.stages.plo_report.PLORepository", return_value=plo_repo),
        patch("curriculum_agent.stages.plo_report.complete_light", light_mock),
    )


async def test_field_clear_specific_skips_llm():
    from curriculum_agent.stages.plo_report import run

    needs = [
        _need("c1", KSECCategory.SS),
        _need("c2", KSECCategory.SS),
        _need("c3", KSECCategory.SS),
    ]
    light = AsyncMock()
    p1, p2, p3 = _patch_ctx(needs, light)
    state = {"program_id": "prog-1", "plos": [_plo(["c1", "c2", "c3"])]}
    with p1, p2, p3:
        result = await run(state)

    plo = result["plos"][0]
    assert plo["classification"] == "specific"
    assert plo["classification_method"] == "ksec"
    assert plo["is_subject_specific"] is True
    light.assert_not_called()


async def test_field_clear_generic_skips_llm():
    from curriculum_agent.stages.plo_report import run

    needs = [
        _need("c1", KSECCategory.GS),
        _need("c2", KSECCategory.GS),
        _need("c3", KSECCategory.GS),
    ]
    light = AsyncMock()
    p1, p2, p3 = _patch_ctx(needs, light)
    state = {"program_id": "prog-1", "plos": [_plo(["c1", "c2", "c3"])]}
    with p1, p2, p3:
        result = await run(state)

    plo = result["plos"][0]
    assert plo["classification"] == "generic"
    assert plo["classification_method"] == "ksec"
    assert plo["is_subject_specific"] is False
    light.assert_not_called()


async def test_ambiguous_uses_llm_fallback():
    from curriculum_agent.stages.plo_report import _ClassificationResult, run

    needs = [
        _need("c1", KSECCategory.SS),
        _need("c2", KSECCategory.GS),
    ]  # fraction 0.5 → ambiguous
    light = AsyncMock(
        return_value=_ClassificationResult(classification="generic", rationale_th="ทักษะทั่วไป")
    )
    p1, p2, p3 = _patch_ctx(needs, light)
    state = {"program_id": "prog-1", "plos": [_plo(["c1", "c2"])]}
    with p1, p2, p3:
        result = await run(state)

    plo = result["plos"][0]
    assert plo["classification"] == "generic"
    assert plo["classification_method"] == "llm"
    assert plo["is_subject_specific"] is False
    assert plo["classification_rationale_th"] == "ทักษะทั่วไป"
    light.assert_called_once()


async def test_no_resolvable_clusters_uses_llm():
    from curriculum_agent.stages.plo_report import _ClassificationResult, run

    needs: list[Need] = []  # PLO references c9 which does not exist
    light = AsyncMock(
        return_value=_ClassificationResult(classification="specific", rationale_th="เฉพาะสาขา")
    )
    p1, p2, p3 = _patch_ctx(needs, light)
    state = {"program_id": "prog-1", "plos": [_plo(["c9"])]}
    with p1, p2, p3:
        result = await run(state)

    plo = result["plos"][0]
    assert plo["classification"] == "specific"
    assert plo["classification_method"] == "llm"
    light.assert_called_once()


async def test_one_llm_classification_failure_degrades_only_that_plo():
    """One PLO's LLM classification call fails; the stage must not abort and
    discard classifications already completed for other PLOs. The failing PLO
    gets a visible fallback classification instead of taking the whole report
    stage down with it.
    """
    from curriculum_agent.stages.plo_report import _ClassificationResult, run

    needs = [
        _need("c1", KSECCategory.SS),
        _need("c2", KSECCategory.GS),
        _need("c3", KSECCategory.SS),
        _need("c4", KSECCategory.GS),
    ]  # fraction 0.5 for both PLOs → both routed through the LLM fallback

    call_count = 0

    async def flaky_light(model, messages, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("LLM unavailable")
        return _ClassificationResult(classification="specific", rationale_th="เฉพาะสาขา")

    p1, p2, p3 = _patch_ctx(needs, flaky_light)
    state = {
        "program_id": "prog-1",
        "plos": [_plo(["c1", "c2"]), _plo(["c3", "c4"])],
    }
    with p1, p2, p3:
        result = await run(state)

    plos = result["plos"]
    assert len(plos) == 2, "stage must not abort and drop the second PLO"

    failed, ok = plos[0], plos[1]
    assert failed["classification_method"] == "fallback"
    assert failed["classification"] == "generic"
    assert ok["classification_method"] == "llm"
    assert ok["classification"] == "specific"


async def test_raises_when_no_plos():
    from curriculum_agent.stages.plo_report import run

    light = AsyncMock()
    p1, p2, p3 = _patch_ctx([], light)
    state = {"program_id": "prog-1", "plos": []}
    with p1, p2, p3, pytest.raises(ValueError):
        await run(state)
