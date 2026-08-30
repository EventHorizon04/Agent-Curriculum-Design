from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, patch

from curriculum_agent.config import settings


async def test_cache_hit_skips_extraction_llm_call():
    """Cache hit for evidence → complete_extraction not called for skill extraction."""
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
        f"{text_slice}\x00general\x00{settings.extraction_model}"
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
    mock_cache_repo.get = AsyncMock(return_value=(settings.extraction_model, cached_json))
    mock_cache_repo.set = AsyncMock()

    llm_call_response_models: list = []

    async def mock_complete_extraction(response_model, messages, **kwargs):
        llm_call_response_models.append(response_model)
        raise AssertionError("complete_extraction should not be called on a cache hit")

    with (
        patch(
            "curriculum_agent.stages.skill_extraction.LLMCacheRepository",
            return_value=mock_cache_repo,
        ),
        patch(
            "curriculum_agent.stages.skill_extraction.complete_extraction",
            side_effect=mock_complete_extraction,
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


async def test_what_extraction_stores_is_what_a_later_run_reads_back():
    """The model name in the key, in the hit comparison, and in what `set`
    stores must be one and the same.

    It was three places and two names: keyed on light_model, stored as
    heavy_model. That only worked while both resolved to the same string —
    once skill extraction moved to its own provider they diverged, every write
    became a permanent miss, and the whole corpus was re-extracted on every
    run at full provider cost. Replaying the stored tuple is the only way to
    catch that; asserting each call site separately is what let it through.
    """
    from curriculum_agent.graph import AgentState
    from curriculum_agent.stages import skill_extraction as se

    text = "ต้องการผู้เชี่ยวชาญด้าน Python และ Machine Learning"
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
    state: AgentState = {"program_id": "prog-001", "classified_evidence": [evidence_dict]}

    fresh = se._ExtractedSkillsResponse(
        skills=[
            se._SkillItem(
                skill_name_th="Python",
                skill_name_en="Python",
                ksec_category="S",
                bloom_level="apply",
                evidence_span_th="ต้องการผู้เชี่ยวชาญด้าน Python",
                confidence=0.9,
            )
        ]
    )

    stored: dict[str, tuple[str, str]] = {}
    kinds: dict[str, tuple[str, str]] = {}

    async def fake_get(_self, key: str):
        return stored.get(key)

    async def fake_set(_self, key: str, model: str, payload: str, *, kind: str, contract: str):
        stored[key] = (model, payload)
        # Not read back on a hit — recorded so the assertion below can state
        # that the row carries the labels prune_cache classifies it by. A set
        # that stored the wrong kind would leave the sweep judging extraction
        # rows against the clustering slot's model.
        kinds[key] = (kind, contract)

    calls = 0

    async def fake_extract(response_model, messages, **kwargs):
        nonlocal calls
        calls += 1
        return fresh

    with (
        patch.object(se.LLMCacheRepository, "get", fake_get),
        patch.object(se.LLMCacheRepository, "set", fake_set),
        patch.object(se, "complete_extraction", fake_extract),
        patch.object(se.SkillRepository, "delete_by_program", AsyncMock(return_value=0)),
        patch.object(se.SkillRepository, "bulk_insert", AsyncMock()),
    ):
        await se.run(dict(state))
        assert calls == 1, "first pass must reach the provider"
        await se.run(dict(state))

    assert calls == 1, "second pass re-extracted — the cache write is unreadable"
    ((written_kind, written_contract),) = kinds.values()
    assert written_kind == "extraction"
    assert written_contract == se._EXTRACTION_CONTRACT
