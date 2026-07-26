from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from curriculum_agent.models import (
    PLO,
    BloomLevel,
    Domain,
    KSECCategory,
    Need,
    SMARTCheck,
)

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)


def _plo(cluster_ids: list[str]) -> dict:
    return PLO(
        plo_id="PLO1",
        program_id="prog-1",
        statement_th="ออกแบบและพัฒนาระบบซอฟต์แวร์",
        domain=Domain.COGNITIVE,
        bloom_level=BloomLevel.CREATE,
        is_subject_specific=False,
        action_verb_th="ออกแบบ",
        smart_check=_SMART,
        source_cluster_ids=cluster_ids,
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
    assert plo["classification_method"] == "skill_type"
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
    assert plo["classification_method"] == "skill_type"
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


async def test_raises_when_no_plos():
    from curriculum_agent.stages.plo_report import run

    light = AsyncMock()
    p1, p2, p3 = _patch_ctx([], light)
    state = {"program_id": "prog-1", "plos": []}
    with p1, p2, p3, pytest.raises(ValueError):
        await run(state)
