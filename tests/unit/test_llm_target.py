from __future__ import annotations

import pytest

import curriculum_agent.llm as llm
from curriculum_agent.config import Settings

_TYPHOON_KEY = "sk-typhoon-000000000000000000000000"
_ROUTER_KEY = "sk-or-v1-1111111111111111111111111111"


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


@pytest.fixture
def typhoon(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """The shipped arrangement: OpenTyphoon for light and extraction, OpenRouter
    for heavy.

    The module-level name is replaced rather than the singleton mutated: llm.py
    binds `settings` at import, so a test that mutated the shared object would
    leak the provider into every later test in the session.
    """
    settings = _settings(
        llm_provider="opentyphoon",
        opentyphoon_api_key=_TYPHOON_KEY,
        openrouter_api_key=_ROUTER_KEY,
    )
    monkeypatch.setattr(llm, "settings", settings)
    return settings


def test_opentyphoon_resolves_to_its_own_endpoint_and_key(typhoon: Settings) -> None:
    assert llm._base_url("opentyphoon") == typhoon.opentyphoon_base_url
    assert llm._api_key("opentyphoon") == _TYPHOON_KEY


def test_opentyphoon_sends_no_keep_alive(typhoon: Settings) -> None:
    """keep_alive pins a model in Ollama's VRAM. A hosted provider does not
    recognise the field, and OpenTyphoon is hosted."""
    assert llm._extra_body("opentyphoon") == {}


def test_opentyphoon_without_a_key_names_the_variable_to_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm, "settings", _settings(llm_provider="opentyphoon"))

    with pytest.raises(ValueError, match="OPENTYPHOON_API_KEY"):
        llm._api_key("opentyphoon")


def test_heavy_resolves_to_a_different_endpoint_than_the_rest(typhoon: Settings) -> None:
    """The whole point of the split: clustering and PLO synthesis talk to
    OpenRouter while the stages that write Thai prose stay on the Thai model."""
    heavy = llm._heavy_provider()

    assert heavy == "openrouter"
    assert llm._base_url(heavy) == typhoon.openrouter_base_url
    assert llm._api_key(heavy) == _ROUTER_KEY
    assert llm._base_url(typhoon.llm_provider) == typhoon.opentyphoon_base_url


def test_heavy_follows_the_default_provider_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One endpoint for the whole pipeline stays a supported arrangement."""
    settings = _settings(llm_provider="ollama", heavy_provider=None, extraction_provider=None)
    monkeypatch.setattr(llm, "settings", settings)

    assert llm._heavy_provider() == "ollama"


def test_extraction_shares_the_thai_first_endpoint(typhoon: Settings) -> None:
    """Extraction reads Thai evidence and names Thai skills, so it sits on the
    same endpoint as light rather than on heavy's."""
    extraction = llm._extraction_provider()

    assert extraction == "opentyphoon"
    assert llm._base_url(extraction) == typhoon.opentyphoon_base_url
    assert llm._api_key(extraction) == _TYPHOON_KEY


def test_extraction_follows_the_default_provider_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One endpoint for the whole pipeline is a supported arrangement — someone
    running fully local should not have to also name a provider for extraction."""
    settings = _settings(llm_provider="ollama", heavy_provider=None, extraction_provider=None)
    monkeypatch.setattr(llm, "settings", settings)

    assert llm._extraction_provider() == "ollama"
    assert llm._base_url(llm._extraction_provider()).endswith("/v1")


def test_describe_target_names_both_endpoints_and_no_key(typhoon: Settings) -> None:
    """The line goes to a log file, a terminal, and often a bug report. It says
    whether a key is configured, never which one — and it names both targets,
    since "the wrong model answered" cannot be diagnosed from one of them."""
    described = llm.describe_target()

    assert _TYPHOON_KEY not in described
    assert _ROUTER_KEY not in described
    assert "light: provider=opentyphoon" in described
    assert "heavy: provider=openrouter" in described
    assert "extraction: provider=opentyphoon" in described
    assert typhoon.openrouter_base_url in described
    assert typhoon.opentyphoon_base_url in described
    assert typhoon.heavy_model in described
    assert typhoon.extraction_model in described
    assert "api_key=set" in described


def test_describe_target_reports_a_missing_key_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Called from the API's lifespan, before any LLM work. Raising there would
    take down startup over a diagnostic line."""
    monkeypatch.setattr(llm, "settings", _settings(llm_provider="opentyphoon"))

    assert "api_key=MISSING" in llm.describe_target()
