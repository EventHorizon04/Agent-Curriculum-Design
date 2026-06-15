from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from curriculum_agent.models import (
    PLO,
    BloomLevel,
    Domain,
    SkillCluster,
    SkillType,
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


def _cluster(cid: str, subject_specific: bool) -> SkillCluster:
    return SkillCluster(
        cluster_id=cid,
        program_id="prog-1",
        canonical_name_th="ทักษะ",
        canonical_name_en="Skill",
        description_th="รายละเอียด",
        skill_type=SkillType.KNOWLEDGE,
        is_subject_specific=subject_specific,
        member_skill_ids=["s1"],
        source_evidence_ids=["ev-1"],
        demand_score=0.5,
    )


def _patch_ctx(clusters, light_mock):
    cluster_repo = AsyncMock()
    cluster_repo.list_by_program = AsyncMock(return_value=clusters)
    plo_repo = AsyncMock()
    plo_repo.bulk_insert = AsyncMock()
    return (
        patch("curriculum_agent.stages.plo_report.ClusterRepository", return_value=cluster_repo),
        patch("curriculum_agent.stages.plo_report.PLORepository", return_value=plo_repo),
        patch("curriculum_agent.stages.plo_report.complete_light", light_mock),
    )


async def test_field_clear_specific_skips_llm():
    from curriculum_agent.stages.plo_report import run

    clusters = [_cluster("c1", True), _cluster("c2", True), _cluster("c3", True)]
    light = AsyncMock()
    p1, p2, p3 = _patch_ctx(clusters, light)
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

    clusters = [_cluster("c1", False), _cluster("c2", False), _cluster("c3", False)]
    light = AsyncMock()
    p1, p2, p3 = _patch_ctx(clusters, light)
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

    clusters = [_cluster("c1", True), _cluster("c2", False)]  # fraction 0.5 → ambiguous
    light = AsyncMock(
        return_value=_ClassificationResult(classification="generic", rationale_th="ทักษะทั่วไป")
    )
    p1, p2, p3 = _patch_ctx(clusters, light)
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

    clusters = []  # PLO references c9 which does not exist
    light = AsyncMock(
        return_value=_ClassificationResult(classification="specific", rationale_th="เฉพาะสาขา")
    )
    p1, p2, p3 = _patch_ctx(clusters, light)
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
    with p1, p2, p3:
        with pytest.raises(ValueError):
            await run(state)
