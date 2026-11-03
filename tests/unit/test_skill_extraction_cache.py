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
    # Three empty trailing segments: field_th, program_name_th, scope_th. The
    # scope statement is appended unconditionally, so a program without one still
    # contributes its separator — there is no shorter key for the no-scope case.
    cache_key = hashlib.sha256(
        f"{text_slice}\x00general\x00{settings.extraction_model}"
        f"\x00{_EXTRACTION_CONTRACT}\x00\x00\x00".encode()
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

    It was three places and two names: keyed on need_combination_model, stored as
    clustering_model. That only worked while both resolved to the same string —
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


async def test_a_scoped_program_replays_the_entry_stored_under_its_own_scope():
    """The scope statement is the last segment of the key, appended after
    program_name_th.

    Written as a replay rather than as an assertion on the key `run` computes:
    the last cache bug here survived because the key and the write were checked
    at separate call sites and each looked right on its own. Planting an entry
    and watching the provider go untouched is the only shape that checks the
    whole path at once.
    """
    from curriculum_agent.graph import AgentState
    from curriculum_agent.stages.skill_extraction import _EXTRACTION_CONTRACT, run

    scope = "หลักสูตรนี้ครอบคลุมการพัฒนาซอฟต์แวร์ การวิเคราะห์ข้อมูล และการดูแลระบบฐานข้อมูล"
    text = "ต้องการผู้เชี่ยวชาญด้าน Python และ Machine Learning"
    cache_key = hashlib.sha256(
        f"{text[:1200]}\x00general\x00{settings.extraction_model}"
        f"\x00{_EXTRACTION_CONTRACT}\x00\x00\x00{scope}".encode()
    ).hexdigest()

    cached_json = (
        '{"skills": [{"skill_name_th": "Python", "skill_name_en": "Python",'
        ' "ksec_category": "S", "bloom_level": "apply",'
        ' "evidence_span_th": "ต้องการผู้เชี่ยวชาญด้าน Python", "confidence": 0.9}]}'
    )

    state: AgentState = {
        "program_id": "prog-001",
        "metadata": {"scope_th": scope},
        "classified_evidence": [
            {
                "evidence_id": "ev-001",
                "program_id": "prog-001",
                "stakeholder_type": "employer",
                "source_name": "Test",
                "raw_text_th": text,
                "collected_at": "2026-01-01T00:00:00",
                "classification": "general",
                "metadata": {},
            }
        ],
        "extracted_skills": [],
    }

    mock_cache_repo = AsyncMock()
    mock_cache_repo.get = AsyncMock(return_value=(settings.extraction_model, cached_json))
    mock_cache_repo.set = AsyncMock()

    async def refuse(response_model, messages, **kwargs):  # noqa: ANN001, ANN003, ANN202
        raise AssertionError("complete_extraction should not be called on a cache hit")

    with (
        patch(
            "curriculum_agent.stages.skill_extraction.LLMCacheRepository",
            return_value=mock_cache_repo,
        ),
        patch("curriculum_agent.stages.skill_extraction.complete_extraction", side_effect=refuse),
        patch(
            "curriculum_agent.stages.skill_extraction.SkillRepository",
            return_value=AsyncMock(bulk_insert=AsyncMock()),
        ),
    ):
        result_state = await run(state)

    mock_cache_repo.get.assert_called_once_with(cache_key)
    assert result_state["extracted_skills"][0]["skill_name_th"] == "Python"


async def test_editing_a_scope_statement_re_extracts_only_that_program():
    """Two programs reading the same source text — the same สภาวิชาชีพ standard,
    the same scraped posting — must not share an entry, because is_field_relevant
    was judged against a different scope in each.

    The other half matters just as much: the same scope must still hit. Without
    it, the fix for a collision could just as well be a key nothing ever matches,
    and the whole corpus would be re-extracted on every run.
    """
    from curriculum_agent.graph import AgentState
    from curriculum_agent.stages import skill_extraction as se

    text = "ต้องการผู้เชี่ยวชาญด้าน Python และ Machine Learning"
    evidence = {
        "evidence_id": "ev-001",
        "program_id": "prog-001",
        "stakeholder_type": "employer",
        "source_name": "Test",
        "raw_text_th": text,
        "collected_at": "2026-01-01T00:00:00",
        "classification": "general",
        "metadata": {},
    }

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
    calls = 0

    async def fake_get(_self, key: str):
        return stored.get(key)

    async def fake_set(_self, key: str, model: str, payload: str, *, kind: str, contract: str):
        stored[key] = (model, payload)

    async def fake_extract(response_model, messages, **kwargs):  # noqa: ANN001, ANN003
        nonlocal calls
        calls += 1
        return fresh

    def _state(scope: str) -> AgentState:
        return {
            "program_id": "prog-001",
            "metadata": {"scope_th": scope},
            "classified_evidence": [dict(evidence)],
        }

    translation = "หลักสูตรนี้ครอบคลุมการแปลเอกสารธุรกิจ การล่ามการเจรจา และการตรวจแก้งานแปล"
    software = "หลักสูตรนี้ครอบคลุมการพัฒนาซอฟต์แวร์ การวิเคราะห์ข้อมูล และการดูแลระบบฐานข้อมูล"

    with (
        patch.object(se.LLMCacheRepository, "get", fake_get),
        patch.object(se.LLMCacheRepository, "set", fake_set),
        patch.object(se, "complete_extraction", fake_extract),
        patch.object(se.SkillRepository, "delete_by_program", AsyncMock(return_value=0)),
        patch.object(se.SkillRepository, "bulk_insert", AsyncMock()),
    ):
        await se.run(_state(translation))
        assert calls == 1
        await se.run(_state(software))
        assert calls == 2, "a different scope statement replayed the other program's entry"
        await se.run(_state(translation))

    assert calls == 2, "the same scope statement failed to hit its own entry"
    assert len(stored) == 2


def _extraction_state() -> dict:
    return {
        "program_id": "prog-001",
        "classified_evidence": [
            {
                "evidence_id": "ev-001",
                "program_id": "prog-001",
                "stakeholder_type": "employer",
                "source_name": "Test",
                "raw_text_th": "ต้องการผู้เชี่ยวชาญด้าน Python",
                "collected_at": "2026-01-01T00:00:00",
                "classification": "general",
                "metadata": {},
            }
        ],
        "extracted_skills": [],
    }


async def _run_extraction_miss(monkeypatch) -> tuple[AsyncMock, AsyncMock]:  # noqa: ANN001
    from curriculum_agent.stages import skill_extraction as se

    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    call = AsyncMock(return_value=se._ExtractedSkillsResponse(skills=[]))
    monkeypatch.setattr(se, "LLMCacheRepository", lambda: cache)
    monkeypatch.setattr(se, "complete_extraction", call)
    monkeypatch.setattr(se, "SkillRepository", lambda: AsyncMock(bulk_insert=AsyncMock()))
    await se.run(_extraction_state())  # type: ignore[arg-type]
    return cache, call


async def test_unset_extraction_bounds_change_neither_request_nor_key(monkeypatch):
    from curriculum_agent.stages.skill_extraction import _EXTRACTION_CONTRACT

    monkeypatch.setattr(settings, "extraction_max_tokens", None)
    monkeypatch.setattr(settings, "extraction_reasoning_max_tokens", None)
    cache, call = await _run_extraction_miss(monkeypatch)

    text = "ต้องการผู้เชี่ยวชาญด้าน Python"
    legacy_key = hashlib.sha256(
        f"{text}\x00general\x00{settings.extraction_model}"
        f"\x00{_EXTRACTION_CONTRACT}\x00\x00\x00".encode()
    ).hexdigest()
    cache.get.assert_called_once_with(legacy_key)
    assert "max_tokens" not in call.await_args.kwargs
    assert "reasoning_max_tokens" not in call.await_args.kwargs


async def test_set_extraction_bounds_are_sent_and_change_the_key(monkeypatch):
    monkeypatch.setattr(settings, "extraction_max_tokens", None)
    monkeypatch.setattr(settings, "extraction_reasoning_max_tokens", None)
    unbounded, _ = await _run_extraction_miss(monkeypatch)
    unbounded_key = unbounded.get.call_args.args[0]

    monkeypatch.setattr(settings, "extraction_max_tokens", 2048)
    monkeypatch.setattr(settings, "extraction_reasoning_max_tokens", 512)
    bounded, call = await _run_extraction_miss(monkeypatch)

    assert call.await_args.kwargs["max_tokens"] == 2048
    assert call.await_args.kwargs["reasoning_max_tokens"] == 512
    assert bounded.get.call_args.args[0] != unbounded_key
    assert bounded.set.call_args.args[0] == bounded.get.call_args.args[0]
