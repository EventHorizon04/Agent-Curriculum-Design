from __future__ import annotations

from unittest.mock import AsyncMock, patch

import curriculum_agent.stages.skill_extraction as se
from curriculum_agent.prompts.classify_cluster_bloom import build_cluster_bloom_prompt


def test_bloom_prompt_contains_cluster_info():
    msgs = build_cluster_bloom_prompt(
        "วิเคราะห์ข้อมูล", "กลุ่มทักษะวิเคราะห์", ["สถิติ", "Python"], "knowledge"
    )
    assert msgs[0]["role"] == "system"
    joined = msgs[0]["content"] + msgs[1]["content"]
    assert "Bloom" in joined
    assert "วิเคราะห์ข้อมูล" in msgs[1]["content"]
    assert "สถิติ" in msgs[1]["content"]


def test_bloom_result_model_affective_gets_krathwohl():
    r = se._ClusterBloomResult(krathwohl_level="valuing", is_subject_specific=False)
    assert r.bloom_level is None
    assert r.krathwohl_level == "valuing"


def test_bloom_result_model_cognitive_gets_bloom():
    r = se._ClusterBloomResult(bloom_level="analyze", is_subject_specific=True)
    assert r.bloom_level == "analyze"
    assert r.krathwohl_level is None


def test_bloom_result_model_psychomotor_gets_psychomotor():
    r = se._ClusterBloomResult(psychomotor_level="precise", is_subject_specific=True)
    assert r.psychomotor_level == "precise"
    assert r.bloom_level is None
    assert r.krathwohl_level is None


def _build_initial_state():
    from curriculum_agent.graph import AgentState

    evidence_dict = {
        "evidence_id": "ev-001",
        "program_id": "prog-001",
        "stakeholder_type": "employer",
        "source_name": "Test",
        "raw_text_th": "ต้องการผู้เชี่ยวชาญด้าน Python และการวิเคราะห์ข้อมูล",
        "collected_at": "2026-01-01T00:00:00",
        "classification": "need",
        "metadata": {},
    }

    state: AgentState = {
        "program_id": "prog-001",
        "classified_evidence": [evidence_dict],
        "extracted_skills": [],
        "skill_clusters": [],
    }
    return state


async def _run_stage_with_mocked_llm(naming_result, bloom_effect):
    """Drive skill_extraction.run() end-to-end with complete_light dispatched by
    response-model class. `bloom_effect` may be a _ClusterBloomResult instance
    (returned) or an Exception instance (raised) for the tagging call."""
    state = _build_initial_state()

    extraction_result = se._ExtractedSkillsResponse(
        skills=[
            se._SkillItem(
                skill_name_th="Python",
                skill_name_en="Python",
                ksec_category="SS",
                bloom_level="apply",
                evidence_span_th="ต้องการผู้เชี่ยวชาญด้าน Python",
                confidence=0.9,
            )
        ]
    )

    async def dispatch_complete_light(response_model, messages, **kwargs):
        if response_model is se._ExtractedSkillsResponse:
            return extraction_result
        if response_model is se._ClusterNameResult:
            return naming_result
        if response_model is se._ClusterBloomResult:
            if isinstance(bloom_effect, Exception):
                raise bloom_effect
            return bloom_effect
        raise AssertionError(f"unexpected response_model {response_model}")

    mock_cache_repo = AsyncMock()
    mock_cache_repo.get = AsyncMock(return_value=None)
    mock_cache_repo.set = AsyncMock()

    with (
        patch(
            "curriculum_agent.stages.skill_extraction.LLMCacheRepository",
            return_value=mock_cache_repo,
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.complete_light",
            side_effect=dispatch_complete_light,
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.cluster_skill_names",
            new=AsyncMock(return_value=[[0]]),
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.SkillRepository",
            return_value=AsyncMock(bulk_insert=AsyncMock()),
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.ClusterRepository",
            return_value=AsyncMock(bulk_insert=AsyncMock()),
        ),
    ):
        return await se.run(state)


async def test_ungrounded_skill_is_dropped_and_counted():
    """A skill whose evidence_span_th does not occur in the evidence text is
    dropped by the groundedness filter before clustering, and the drop is
    counted on state — the LLM invented a quote, is_grounded() catches it."""
    state = _build_initial_state()

    extraction_result = se._ExtractedSkillsResponse(
        skills=[
            se._SkillItem(
                skill_name_th="Python",
                skill_name_en="Python",
                ksec_category="SS",
                bloom_level="apply",
                evidence_span_th="ข้อความที่ไม่มีอยู่จริงในหลักฐานเลย",
                confidence=0.9,
            )
        ]
    )

    async def dispatch_complete_light(response_model, messages, **kwargs):
        if response_model is se._ExtractedSkillsResponse:
            return extraction_result
        raise AssertionError(f"unexpected response_model {response_model}")

    mock_cache_repo = AsyncMock()
    mock_cache_repo.get = AsyncMock(return_value=None)
    mock_cache_repo.set = AsyncMock()

    with (
        patch(
            "curriculum_agent.stages.skill_extraction.LLMCacheRepository",
            return_value=mock_cache_repo,
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.complete_light",
            side_effect=dispatch_complete_light,
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.SkillRepository",
            return_value=AsyncMock(bulk_insert=AsyncMock()),
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.ClusterRepository",
            return_value=AsyncMock(bulk_insert=AsyncMock()),
        ),
    ):
        result_state = await se.run(state)

    assert result_state["extracted_skills"] == []
    assert result_state["skill_clusters"] == []
    assert result_state["dropped_ungrounded_count"] == 1


async def test_full_stage_tags_clusters_with_bloom_level():
    """Stage run() wires the tagging call through and stamps bloom_level on clusters."""
    naming_result = se._ClusterNameResult(
        canonical_name_th="ทักษะ Python",
        canonical_name_en="Python Skills",
        description_th="ทักษะด้าน Python",
        skill_type="knowledge",
        is_subject_specific=True,
    )
    bloom_result = se._ClusterBloomResult(bloom_level="analyze", is_subject_specific=True)

    result_state = await _run_stage_with_mocked_llm(naming_result, bloom_result)

    assert len(result_state["skill_clusters"]) > 0
    for cluster in result_state["skill_clusters"]:
        assert cluster["bloom_level"] == "analyze"


async def test_tagging_failure_leaves_cluster_untagged():
    """If the tagging call raises, the cluster falls back to untagged with naming's
    is_subject_specific value, instead of crashing the stage."""
    naming_result = se._ClusterNameResult(
        canonical_name_th="ทักษะ Python",
        canonical_name_en="Python Skills",
        description_th="ทักษะด้าน Python",
        skill_type="knowledge",
        is_subject_specific=True,
    )

    result_state = await _run_stage_with_mocked_llm(
        naming_result, Exception("tagging LLM call failed")
    )

    assert len(result_state["skill_clusters"]) > 0
    cluster = result_state["skill_clusters"][0]
    assert cluster["bloom_level"] is None
    assert cluster["krathwohl_level"] is None
    assert cluster["is_subject_specific"] is True


async def test_psychomotor_cluster_gets_psychomotor_level():
    """Psychomotor clusters get psychomotor_level tagged instead of bloom_level."""
    naming_result = se._ClusterNameResult(
        canonical_name_th="ทักษะการใช้เครื่องมือวัด",
        canonical_name_en="Instrumentation Skills",
        description_th="ทักษะปฏิบัติการใช้เครื่องมือวัด",
        skill_type="psychomotor",
        is_subject_specific=True,
    )
    bloom_result = se._ClusterBloomResult(psychomotor_level="precise", is_subject_specific=True)

    result_state = await _run_stage_with_mocked_llm(naming_result, bloom_result)

    assert len(result_state["skill_clusters"]) > 0
    cluster = result_state["skill_clusters"][0]
    assert cluster["psychomotor_level"] == "precise"
    assert cluster["bloom_level"] is None
    assert cluster["krathwohl_level"] is None


async def _run_stage_with_dedup_cluster(
    extraction_skills, cluster_groups, naming_result, bloom_result
):
    """Like _run_stage_with_mocked_llm, but drives multiple extracted skills
    through the real dedupe_names -> cluster_skill_names -> index remap path,
    with cluster_skill_names mocked (rather than the real heavy-model call)
    to return a fixed grouping over deduped unique names."""
    state = _build_initial_state()

    extraction_result = se._ExtractedSkillsResponse(skills=extraction_skills)

    async def dispatch_complete_light(response_model, messages, **kwargs):
        if response_model is se._ExtractedSkillsResponse:
            return extraction_result
        if response_model is se._ClusterNameResult:
            return naming_result
        if response_model is se._ClusterBloomResult:
            return bloom_result
        raise AssertionError(f"unexpected response_model {response_model}")

    mock_cache_repo = AsyncMock()
    mock_cache_repo.get = AsyncMock(return_value=None)
    mock_cache_repo.set = AsyncMock()

    mock_cluster = AsyncMock(return_value=cluster_groups)

    with (
        patch(
            "curriculum_agent.stages.skill_extraction.LLMCacheRepository",
            return_value=mock_cache_repo,
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.complete_light",
            side_effect=dispatch_complete_light,
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.cluster_skill_names",
            new=mock_cluster,
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.SkillRepository",
            return_value=AsyncMock(bulk_insert=AsyncMock()),
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.ClusterRepository",
            return_value=AsyncMock(bulk_insert=AsyncMock()),
        ),
    ):
        result_state = await se.run(state)
    return result_state, mock_cluster


async def test_dedupe_then_cluster_remaps_to_original_skill_indices():
    """3 extracted skills — two spellings of "Python" plus "SQL" — are deduped
    to 2 unique names before the (mocked) clustering call, and the resulting
    groups are remapped back to the original extracted-skill indices."""
    extraction_skills = [
        se._SkillItem(
            skill_name_th="Python",
            skill_name_en="Python",
            ksec_category="SS",
            bloom_level="apply",
            evidence_span_th="ต้องการผู้เชี่ยวชาญด้าน Python",
            confidence=0.9,
        ),
        se._SkillItem(
            skill_name_th="  python ",
            skill_name_en="Python",
            ksec_category="SS",
            bloom_level="apply",
            evidence_span_th="ต้องการผู้เชี่ยวชาญด้าน Python",
            confidence=0.8,
        ),
        se._SkillItem(
            skill_name_th="SQL",
            skill_name_en="SQL",
            ksec_category="SS",
            bloom_level="apply",
            evidence_span_th="และการวิเคราะห์ข้อมูล",
            confidence=0.9,
        ),
    ]
    naming_result = se._ClusterNameResult(
        canonical_name_th="ทักษะ",
        canonical_name_en="Skill",
        description_th="desc",
        skill_type="knowledge",
        is_subject_specific=True,
    )
    bloom_result = se._ClusterBloomResult(bloom_level="apply", is_subject_specific=True)

    result_state, mock_cluster = await _run_stage_with_dedup_cluster(
        extraction_skills, [[0], [1]], naming_result, bloom_result
    )

    # cluster_skill_names called with the deduped, sorted, first-seen-spelling names
    mock_cluster.assert_called_once_with(["Python", "SQL"])

    clusters = result_state["skill_clusters"]
    assert len(clusters) == 2
    member_counts = sorted(len(c["member_skill_ids"]) for c in clusters)
    assert member_counts == [1, 2]

    all_skill_ids = {s["skill_id"] for s in result_state["extracted_skills"]}
    for cluster in clusters:
        for member_skill_id in cluster["member_skill_ids"]:
            assert member_skill_id in all_skill_ids


async def test_affective_cluster_gets_krathwohl_level():
    """Affective clusters get krathwohl_level tagged instead of bloom_level."""
    naming_result = se._ClusterNameResult(
        canonical_name_th="ทักษะ Python",
        canonical_name_en="Python Skills",
        description_th="ทักษะด้าน Python",
        skill_type="affective",
        is_subject_specific=True,
    )
    bloom_result = se._ClusterBloomResult(krathwohl_level="valuing", is_subject_specific=False)

    result_state = await _run_stage_with_mocked_llm(naming_result, bloom_result)

    assert len(result_state["skill_clusters"]) > 0
    cluster = result_state["skill_clusters"][0]
    assert cluster["krathwohl_level"] == "valuing"
    assert cluster["bloom_level"] is None
    assert cluster["is_subject_specific"] is False
