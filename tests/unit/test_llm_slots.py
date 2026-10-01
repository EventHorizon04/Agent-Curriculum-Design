"""`SLOTS` is the one declaration of an LLM slot, so it is the one thing that
can be wrong about all of them at once.

A slot's provider and model are named as strings, which is what keeps one entry
to one line — and what mypy cannot check. These tests are the substitute: a
misspelled field name fails pytest instead of surfacing at boot as a slot
pointing at nothing.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from curriculum_agent.config import (
    _PROVIDER_DEFAULT_MODEL,
    SLOTS,
    Settings,
    SlotSpec,
)


def test_every_declared_field_exists_on_settings() -> None:
    """The check mypy cannot do for a getattr.

    `_apply_provider_model_defaults` and `_slot_provider` both reach these
    fields by name. A typo there is invisible until something reads the slot,
    and what it reads then is a model of "" pointed at no provider.
    """
    declared = set(Settings.model_fields)
    for slot in SLOTS:
        assert slot.model_field in declared, f"{slot.name}: no field '{slot.model_field}'"
        assert slot.provider_field in declared, f"{slot.name}: no field '{slot.provider_field}'"


def test_the_field_check_would_actually_catch_one() -> None:
    """A guard that silently matches nothing is the failure it exists to catch."""
    fabricated = SlotSpec("invented", "invented_provider", "invented_model")

    assert fabricated.model_field not in set(Settings.model_fields)


def test_no_slot_rides_the_default_provider_without_a_field_of_its_own() -> None:
    """LLM_PROVIDER has one job: the fallback for a slot whose provider is unset.

    It used to have two. `light` had no provider field and read LLM_PROVIDER
    directly, so that one setting was both the fallback and one slot's actual
    endpoint — and the slot could not be moved without moving every unset slot
    with it. Every slot now names its own field, which is what makes the
    fallback a fallback.
    """
    assert all(slot.provider_field for slot in SLOTS)


def test_slot_names_are_unique() -> None:
    """The name is the label in the startup log and the key `_slot` looks up, so
    two slots sharing one makes the second unreachable and the log ambiguous."""
    names = [slot.name for slot in SLOTS]

    assert len(set(names)) == len(names), names


def test_only_the_optional_checks_can_be_switched_off() -> None:
    """`disableable` says "" is a meaningful value for this slot's provider: the
    slot is a check the pipeline can run without, and "" is its kill switch. That
    is true of the validation agent and of the duplicate check before synthesis —
    both fall back to pure code — and of nothing that *produces* the pipeline's
    output. A third disableable slot is a third provider field where empty and
    unset differ, and every reader of that field has to learn the distinction."""
    disableable = [slot.name for slot in SLOTS if slot.disableable]

    assert disableable == ["need_dedup", "validation"]


def test_asking_for_a_slot_that_does_not_exist_says_so() -> None:
    """`_resolve` takes a name, so a typo at a call site has to fail loudly
    rather than resolve to a default slot."""
    from curriculum_agent import llm

    with pytest.raises(KeyError, match="no LLM slot named"):
        llm._slot("heavey")


def test_a_slot_setting_under_its_old_name_is_refused() -> None:
    """The rename would otherwise fail silently.

    `Settings` ignores unknown keys, so a .env still carrying HEAVY_MODEL is not
    an error to pydantic — it is a line nobody reads. The run then starts on the
    provider default while the operator believes they selected a model, and the
    slot they configured is the one they cannot find in the startup log.
    """
    with pytest.raises(ValidationError, match="CLUSTERING_MODEL"):
        Settings(heavy_model="meta-llama/llama-3.3-70b-instruct")


def test_every_stale_name_is_reported_at_once() -> None:
    """One restart should tell the operator everything they have to change,
    rather than one name per attempt."""
    with pytest.raises(ValidationError) as exc:
        Settings(
            light_model="typhoon-v2.5-30b-a3b-instruct",
            heavy_provider="openrouter",
            synthesis_model="typhoon-v2.5-30b-a3b-instruct",
        )

    message = str(exc.value)
    assert "NEED_COMBINATION_MODEL" in message
    assert "CLUSTERING_PROVIDER" in message
    assert "PLO_SYNTHESIS_MODEL" in message


def test_the_current_names_are_accepted() -> None:
    """The guard must reject the old spelling, not the settings themselves."""
    settings = Settings(
        clustering_model="meta-llama/llama-3.3-70b-instruct",
        need_combination_model="typhoon-v2.5-30b-a3b-instruct",
        plo_synthesis_model="typhoon-v2.5-30b-a3b-instruct",
    )

    assert settings.clustering_model == "meta-llama/llama-3.3-70b-instruct"


def test_a_slots_own_model_default_wins_over_the_providers() -> None:
    """A model choice is a line of code, not a line of .env.

    Which model a stage runs on is an engineering decision about that stage —
    extraction has to quote evidence verbatim and was chosen on that — so it
    belongs in the repository under review, not in a per-machine file. The
    provider-wide default stays the fallback for every slot that has no opinion.
    """
    settings = Settings(extraction_provider="openrouter", extraction_model="")

    assert settings.extraction_model == "z-ai/glm-5.3-flash"
    assert settings.clustering_model == _PROVIDER_DEFAULT_MODEL["openrouter"]


def test_the_override_is_looked_up_by_the_resolved_provider() -> None:
    """Keyed by provider, and read after the provider is resolved.

    A slot pinned to one model string would send an OpenRouter model id to
    Typhoon the moment someone moved that slot's provider — an unknown-model
    error nowhere near its cause.
    """
    settings = Settings(extraction_provider="opentyphoon", extraction_model="")

    assert settings.extraction_model == _PROVIDER_DEFAULT_MODEL["opentyphoon"]


def test_an_explicit_model_still_wins_over_both() -> None:
    """The code default is a default. Pinning a model for one run — a probe, an
    incident, a provider outage — must still be one environment variable."""
    settings = Settings(extraction_provider="openrouter", extraction_model="some/other-model")

    assert settings.extraction_model == "some/other-model"


def test_production_refuses_the_credentials_this_file_ships() -> None:
    """They are in the repository, so they authenticate nothing.

    Without this the process starts, connects to whatever is listening on the
    default port and reports itself healthy, which is a worse failure than not
    starting at all.
    """
    with pytest.raises(ValidationError) as exc:
        Settings(app_env="production")

    message = str(exc.value)
    for name in ("POSTGRES_DSN", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "API_KEY"):
        assert name in message, f"{name} missing from: {message}"


def test_production_accepts_real_credentials() -> None:
    settings = Settings(
        app_env="production",
        postgres_dsn="postgresql+asyncpg://u:p@db.internal:5432/curriculum_agent",
        minio_access_key="real-access-key",
        minio_secret_key="real-secret-key",
        api_key="real-api-key",
    )

    assert settings.app_env == "production"


def test_development_is_the_default_and_keeps_working_with_no_env() -> None:
    """Forgetting APP_ENV can only make the check stricter by accident, never
    weaker — and a fresh checkout still runs against the compose stack."""
    assert Settings().app_env == "development"
