from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

from curriculum_agent.config import settings


async def test_cache_hit_skips_extraction_llm_call():
    """Cache hit for evidence → complete_light not called for skill extraction."""
    from curriculum_agent.graph import AgentState
    from curriculum_agent.stages.skill_extraction import _ClusterNameResult, run

    text = "ต้องการผู้เชี่ยวชาญด้าน Python และ Machine Learning"
    text_slice = text[:1200]
    cache_key = hashlib.sha256(
        f"{text_slice}\x00need\x00{settings.light_model}".encode()
    ).hexdigest()

    cached_json = (
        '{"skills": [{"skill_name_th": "Python", "skill_name_en": "Python",'
        ' "skill_type": "knowledge", "is_subject_specific": true, "confidence": 0.9}]}'
    )

    evidence_dict = {
        "evidence_id": "ev-001",
        "program_id": "prog-001",
        "stakeholder_type": "employer",
        "source_name": "Test",
        "raw_text_th": text,
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

    mock_cache_repo = AsyncMock()
    mock_cache_repo.get = AsyncMock(return_value=(settings.light_model, cached_json))
    mock_cache_repo.set = AsyncMock()

    cluster_name = _ClusterNameResult(
        canonical_name_th="ทักษะ Python",
        canonical_name_en="Python Skills",
        description_th="ทักษะด้าน Python",
        skill_type="knowledge",
        is_subject_specific=True,
    )

    llm_call_response_models: list = []

    async def mock_complete_light(response_model, messages, **kwargs):
        llm_call_response_models.append(response_model)
        return cluster_name

    mock_qdrant = MagicMock()
    mock_qdrant.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
    mock_qdrant.create_collection = AsyncMock()
    mock_qdrant.upsert = AsyncMock()

    with (
        patch(
            "curriculum_agent.stages.skill_extraction.LLMCacheRepository",
            return_value=mock_cache_repo,
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.complete_light",
            side_effect=mock_complete_light,
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.extract_keywords",
            return_value=[],
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.embed",
            return_value=[[0.0] * 1024],
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.get_qdrant",
            return_value=mock_qdrant,
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
        result_state = await run(state)

    from curriculum_agent.stages.skill_extraction import _ExtractedSkillsResponse

    # Cache was consulted
    mock_cache_repo.get.assert_called_once()
    # Extraction LLM was NOT called (only cluster naming goes through complete_light)
    assert _ExtractedSkillsResponse not in llm_call_response_models
    # Skills came from cache and ended up in state
    assert len(result_state["extracted_skills"]) > 0
    # Cache set should NOT be called on a hit
    mock_cache_repo.set.assert_not_called()
