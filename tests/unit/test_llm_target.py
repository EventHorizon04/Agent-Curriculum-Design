from __future__ import annotations

import pytest

import curriculum_agent.llm as llm
from curriculum_agent.config import Settings

_TYPHOON_KEY = "sk-typhoon-000000000000000000000000"
_ROUTER_KEY = "sk-or-v1-1111111111111111111111111111"


def _settings(**overrides: object) -> Settings:
    # These tests are about the per-slot mechanism, so the branch's pipeline pair
    # is opted out unless a test sets it.
    overrides.setdefault("pipeline_provider", None)
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


def test_clustering_resolves_to_a_different_endpoint_than_the_rest(typhoon: Settings) -> None:
    """Heavy is clustering alone, and clustering talks to OpenRouter while the
    slots that write Thai prose stay on the Thai model."""
    heavy = llm._resolve("clustering")[0]

    assert heavy == "openrouter"
    assert llm._base_url(heavy) == typhoon.openrouter_base_url
    assert llm._api_key(heavy) == _ROUTER_KEY
    assert llm._base_url(typhoon.llm_provider) == typhoon.opentyphoon_base_url


def test_clustering_follows_the_default_provider_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One endpoint for the whole pipeline stays a supported arrangement."""
    settings = _settings(
        llm_provider="ollama",
        clustering_provider=None,
        plo_synthesis_provider=None,
        extraction_provider=None,
        validation_provider=None,
    )
    monkeypatch.setattr(llm, "settings", settings)

    assert llm._resolve("clustering")[0] == "ollama"


def test_a_switched_off_validation_slot_resolves_to_no_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-slot resolver used to read `settings.validation_provider or
    settings.llm_provider`, which turned the kill switch straight back into a
    live provider — the switch was documented, and unthrowable."""
    settings = _settings(llm_provider="opentyphoon", validation_provider="")
    monkeypatch.setattr(llm, "settings", settings)

    assert llm._resolve("validation")[0] == ""


def test_the_startup_line_says_a_disabled_slot_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dropping the line instead would read as a slot that stopped existing, and
    the startup log is where an operator confirms the switch took."""
    settings = _settings(llm_provider="opentyphoon", validation_provider="")
    monkeypatch.setattr(llm, "settings", settings)

    target = llm.describe_target()

    assert "validation: disabled" in target
    validation_segment = next(seg for seg in target.split(" | ") if seg.startswith("validation:"))
    assert "api_key" not in validation_segment


def test_the_duplicate_check_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "" is the need_dedup kill switch: the startup line says so rather than
    resolving it back to a live provider."""
    monkeypatch.setattr(llm.settings, "need_dedup_provider", "")

    assert "need_dedup: disabled" in llm.describe_target()
    assert llm._resolve("need_dedup")[0] == ""


def test_plo_synthesis_stays_on_the_thai_endpoint_while_clustering_leaves(
    typhoon: Settings,
) -> None:
    """The reason synthesis is its own slot. Both calls used to be `heavy`, so
    this arrangement — clustering on OpenRouter, the PLO statement on the Thai
    model — was not expressible at all."""
    synthesis = llm._resolve("plo_synthesis")[0]

    assert synthesis == "opentyphoon"
    assert llm._base_url(synthesis) == typhoon.opentyphoon_base_url
    assert llm._api_key(synthesis) == _TYPHOON_KEY
    assert llm._resolve("clustering")[0] == "openrouter"


def test_plo_synthesis_follows_the_default_provider_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(
        llm_provider="ollama", plo_synthesis_provider=None, validation_provider=None
    )
    monkeypatch.setattr(llm, "settings", settings)

    assert llm._resolve("plo_synthesis")[0] == "ollama"


def test_extraction_runs_on_its_own_hosted_endpoint(typhoon: Settings) -> None:
    """Extraction fans out a call per window of every evidence item, so it is
    what exhausts a quota first — and it exhausted Typhoon's. It resolves to its
    own provider with that provider's key, not light's."""
    extraction = llm._resolve("extraction")[0]

    assert extraction == "openrouter"
    assert llm._base_url(extraction) == typhoon.openrouter_base_url
    assert llm._api_key(extraction) == _ROUTER_KEY


def test_extraction_follows_the_default_provider_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One endpoint for the whole pipeline is a supported arrangement — someone
    running fully local should not have to also name a provider for extraction."""
    settings = _settings(
        llm_provider="ollama",
        clustering_provider=None,
        plo_synthesis_provider=None,
        extraction_provider=None,
        validation_provider=None,
    )
    monkeypatch.setattr(llm, "settings", settings)

    assert llm._resolve("extraction")[0] == "ollama"
    assert llm._base_url(llm._resolve("extraction")[0]).endswith("/v1")


def test_validation_runs_on_its_own_hosted_endpoint(typhoon: Settings) -> None:
    """The agent loop reasons over a Thai sentence plus tool results rather than
    writing Thai, so it moves off the Thai-first endpoint — but it is its own
    slot, not heavy's, because heavy is clustering and nothing else."""
    validation = llm._resolve("validation")[0]

    assert validation == "openrouter"
    assert llm._base_url(validation) == typhoon.openrouter_base_url
    assert llm._api_key(validation) == _ROUTER_KEY


def test_validation_follows_the_default_provider_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One endpoint end to end stays a supported arrangement."""
    settings = _settings(
        llm_provider="ollama",
        clustering_provider=None,
        plo_synthesis_provider=None,
        extraction_provider=None,
        validation_provider=None,
    )
    monkeypatch.setattr(llm, "settings", settings)

    assert llm._resolve("validation")[0] == "ollama"
    assert llm._base_url(llm._resolve("validation")[0]).endswith("/v1")


def test_describe_target_names_every_slot_and_no_key(typhoon: Settings) -> None:
    """The line goes to a log file, a terminal, and often a bug report. It says
    whether a key is configured, never which one — and it names every slot,
    since "the wrong model answered" cannot be diagnosed from one of them."""
    described = llm.describe_target()

    assert _TYPHOON_KEY not in described
    assert _ROUTER_KEY not in described
    assert "extraction: provider=openrouter" in described
    assert "clustering: provider=openrouter" in described
    assert "need_combination: provider=opentyphoon" in described
    assert "need_dedup: provider=openrouter" in described
    assert "plo_synthesis: provider=opentyphoon" in described
    assert "validation: provider=openrouter" in described
    assert typhoon.openrouter_base_url in described
    assert typhoon.opentyphoon_base_url in described
    assert typhoon.clustering_model in described
    assert typhoon.plo_synthesis_model in described
    assert typhoon.extraction_model in described
    assert typhoon.validation_model in described
    assert typhoon.need_dedup_model in described
    assert "api_key=set" in described


def test_every_slot_is_reported_and_warmed_from_one_list(typhoon: Settings) -> None:
    """describe_target and warmup_models both used to enumerate the slots by
    hand. Five is where such a list stops looking obviously complete, and a slot
    present in only one of them is a model nobody warms or a model nobody can
    see in the startup log. Both now read `SLOTS`.

    The order is pinned, and it is the order the pipeline calls them in: the
    startup line reads as the path a designer walks, so a slot's place in it is
    a fact about the run. It used to be light/heavy/synthesis — a guess about
    model size, by then wrong on both counts.
    """
    labels = [label for label, _, _ in llm._slots()]

    assert labels == [
        "extraction",
        "clustering",
        "need_combination",
        "need_dedup",
        "plo_synthesis",
        "validation",
        "plo_review",
    ]
    assert len(set(labels)) == len(labels)


def test_describe_target_reports_a_missing_key_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Called from the API's lifespan, before any LLM work. Raising there would
    take down startup over a diagnostic line."""
    monkeypatch.setattr(llm, "settings", _settings(llm_provider="opentyphoon"))

    assert "api_key=MISSING" in llm.describe_target()
