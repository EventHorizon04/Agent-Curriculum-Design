from __future__ import annotations

import pytest

import curriculum_agent.llm as llm
from curriculum_agent.config import Settings

_TYPHOON_KEY = "sk-typhoon-000000000000000000000000"


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


@pytest.fixture
def typhoon(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """OpenTyphoon selected with a key configured.

    The module-level name is replaced rather than the singleton mutated: llm.py
    binds `settings` at import, so a test that mutated the shared object would
    leak the provider into every later test in the session.
    """
    settings = _settings(llm_provider="opentyphoon", opentyphoon_api_key=_TYPHOON_KEY)
    monkeypatch.setattr(llm, "settings", settings)
    return settings


def test_opentyphoon_resolves_to_its_own_endpoint_and_key(typhoon: Settings) -> None:
    assert llm._base_url() == typhoon.opentyphoon_base_url
    assert llm._api_key() == _TYPHOON_KEY


def test_opentyphoon_sends_no_keep_alive(typhoon: Settings) -> None:
    """keep_alive pins a model in Ollama's VRAM. A hosted provider does not
    recognise the field, and OpenTyphoon is hosted."""
    assert llm._extra_body() == {}


def test_opentyphoon_without_a_key_names_the_variable_to_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm, "settings", _settings(llm_provider="opentyphoon"))

    with pytest.raises(ValueError, match="OPENTYPHOON_API_KEY"):
        llm._api_key()


def test_describe_target_never_renders_the_key(typhoon: Settings) -> None:
    """The line goes to a log file, a terminal, and often a bug report. It says
    whether a key is configured, never which one."""
    described = llm.describe_target()

    assert _TYPHOON_KEY not in described
    assert "api_key=set" in described
    assert "provider=opentyphoon" in described
    assert typhoon.opentyphoon_base_url in described


def test_describe_target_reports_a_missing_key_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Called from the API's lifespan, before any LLM work. Raising there would
    take down startup over a diagnostic line."""
    monkeypatch.setattr(llm, "settings", _settings(llm_provider="opentyphoon"))

    assert "api_key=MISSING" in llm.describe_target()
