from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, patch

from curriculum_agent.config import settings


async def test_cache_hit_skips_extraction_llm_call():
    """Cache hit for evidence → complete_light not called for skill extraction."""
    from curriculum_agent.graph import AgentState
    from curriculum_agent.stages.skill_extraction import _EXTRACTION_CONTRACT, run

    text = "ต้องการผู้เชี่ยวชาญด้าน Python และ Machine Learning"
    text_slice = text[:1200]
    # The contract fingerprint is part of the key on purpose: it is what stops a
    # payload cached under an older response schema from being replayed. Import it
    # rather than restating it, so this test cannot drift from the code again.
    # field_th/program_name_th are empty strings here because `state` carries no
    # "metadata" key — see skill_extraction.run's `metadata = state.get("metadata")
    # or {}` fallback — and both are part of the key alongside the contract
    # fingerprint (Task 8).
    cache_key = hashlib.sha256(
        f"{text_slice}\x00general\x00{settings.light_model}"
        f"\x00{_EXTRACTION_CONTRACT}\x00\x00".encode()
    ).hexdigest()

    cached_json = (
        '{"skills": [{"skill_name_th": "Python", "skill_name_en": "Python",'
        ' "ksec_category": "S", "bloom_level": "apply",'
        ' "evidence_span_th": "ต้องการผู้เชี่ยวชาญด้าน Python", "confidence": 0.9}]}'
    )

    evidence_dict = {
        "evidence_id": "ev-001",
        "program_id": "prog-001",
        "stakeholder_type": "employer",
        "source_name": "Test",
        "raw_text_th": text,
        "collected_at": "2026-01-01T00:00:00",
        "classification": "general",
        "metadata": {},
    }

    state: AgentState = {
        "program_id": "prog-001",
        "classified_evidence": [evidence_dict],
        "extracted_skills": [],
    }

    mock_cache_repo = AsyncMock()
    mock_cache_repo.get = AsyncMock(return_value=(settings.light_model, cached_json))
    mock_cache_repo.set = AsyncMock()

    llm_call_response_models: list = []

    async def mock_complete_light(response_model, messages, **kwargs):
        llm_call_response_models.append(response_model)
        raise AssertionError("complete_light should not be called on a cache hit")

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
            "curriculum_agent.stages.skill_extraction.SkillRepository",
            return_value=AsyncMock(bulk_insert=AsyncMock()),
        ),
    ):
        result_state = await run(state)

    # Cache was consulted with the text+classification+model key
    mock_cache_repo.get.assert_called_once_with(cache_key)
    # Extraction LLM was NOT called at all — cache satisfied it
    assert llm_call_response_models == []
    # Skills came from cache and ended up in state
    assert len(result_state["extracted_skills"]) > 0
    assert result_state["extracted_skills"][0]["skill_name_th"] == "Python"
    # Cache set should NOT be called on a hit
    mock_cache_repo.set.assert_not_called()
