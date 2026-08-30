from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from curriculum_agent.config import Settings

_SECRETS = {
    "openrouter_api_key": "sk-or-v1-000000000000000000000000000000000000",
    "api_key": "rest-admin-secret-value",
    "minio_secret_key": "minio-secret-value",
    "llm_api_key": "llm-secret-value",
}


@pytest.mark.parametrize("field_name", sorted(_SECRETS))
def test_secret_never_renders_in_text(field_name: str) -> None:
    """A plain str field leaks on every repr — a failing assertion, a log line, a
    debugger frame. pytest printed the real OpenRouter key into a terminal from
    an AttributeError on Settings, which is how this test came to exist."""
    settings = Settings(_env_file=None, **_SECRETS)
    value = _SECRETS[field_name]

    rendered = f"{settings!r} {settings} {settings.model_dump()} {settings.model_dump_json()}"

    assert value not in rendered


def test_secret_value_is_still_readable() -> None:
    settings = Settings(_env_file=None, **_SECRETS)
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == _SECRETS["api_key"]


def test_dsn_without_the_asyncpg_driver_is_rejected():
    """A DSN written as plain `postgresql://` resolves to SQLAlchemy's default
    postgres driver, psycopg2, which this project does not install — so
    create_async_engine dies with ModuleNotFoundError at import of
    data/postgres.py. Failing here names the actual mistake instead."""
    with pytest.raises(ValidationError, match=r"\+asyncpg"):
        Settings(
            _env_file=None,
            postgres_dsn="postgresql://curriculum:pw@localhost:5432/curriculum_agent",
        )


def test_dsn_with_a_different_async_driver_is_rejected():
    with pytest.raises(ValidationError, match=r"\+asyncpg"):
        Settings(
            _env_file=None,
            postgres_dsn="postgresql+psycopg://curriculum:pw@localhost:5432/curriculum_agent",
        )


def test_rejecting_a_bad_dsn_does_not_echo_the_password():
    with pytest.raises(ValidationError) as exc:
        Settings(
            _env_file=None,
            postgres_dsn="postgresql://curriculum:hunter2@localhost:5432/curriculum_agent",
        )
    assert "hunter2" not in str(exc.value)


def test_service_defaults_address_loopback_numerically():
    """docker-compose publishes these on 127.0.0.1 only, which is IPv4.

    On Windows `getaddrinfo("localhost")` returns ::1 first, and psycopg does
    not fall back to the IPv4 address the way asyncpg and curl do — it waits
    on a port nothing is listening on until the connect times out. The symptom
    is an API that hangs in its lifespan after logging that it is initialising
    the checkpointer, with no error to read. Spelling the address numerically
    removes the resolver from the path entirely.
    """
    s = Settings(_env_file=None)
    assert "@127.0.0.1:5432/" in s.postgres_dsn
    assert "localhost" not in s.postgres_dsn
    assert s.minio_endpoint == "127.0.0.1:9000"


def test_postgres_dsn_sync_strips_asyncpg_driver():
    s = Settings(postgres_dsn="postgresql+asyncpg://user:pass@localhost:5432/mydb")
    assert s.postgres_dsn_sync == "postgresql://user:pass@localhost:5432/mydb"


def test_postgres_dsn_langgraph_keeps_the_psycopg_form():
    s = Settings(postgres_dsn="postgresql+asyncpg://user:pass@localhost:5432/mydb")
    assert s.postgres_dsn_langgraph.startswith(
        "postgresql://user:pass@localhost:5432/mydb?options="
    )


def test_model_defaults_follow_the_ollama_provider():
    # heavy_provider=None collapses the three endpoints onto llm_provider, which
    # is the arrangement someone running fully local wants.
    s = Settings(_env_file=None, llm_provider="ollama", heavy_provider=None)
    assert s.light_model == "gemma4:31b-cloud"
    assert s.heavy_model == "gemma4:31b-cloud"


def test_model_defaults_follow_the_openrouter_provider():
    # The provider is read at instance level, not at class-definition time, so
    # switching it in .env must switch the model defaults with it.
    s = Settings(_env_file=None, llm_provider="openrouter", heavy_provider=None)
    assert s.light_model == "meta-llama/llama-3.3-70b-instruct"
    assert s.heavy_model == "meta-llama/llama-3.3-70b-instruct"


def test_the_default_provider_is_thai_first():
    """Pinned because it is a decision, not an accident: the prompts and the
    stored statements are Thai, so the default endpoint serves Thai-first models.
    Changing it should require changing this line and saying why.

    It governs `light` — the Need sentences and the SMART soft judge, the Thai
    prose a designer actually reads back. Heavy and extraction each run on their
    own endpoint for reasons pinned in their own tests.
    """
    s = Settings(_env_file=None)
    assert s.llm_provider == "opentyphoon"
    assert s.light_model == "typhoon-v2.5-30b-a3b-instruct"


def test_explicit_models_survive_the_provider_default():
    s = Settings(
        _env_file=None,
        llm_provider="ollama",
        heavy_provider=None,
        light_model="typhoon2:8b",
        heavy_model="qwen2.5:14b",
    )
    assert s.light_model == "typhoon2:8b"
    assert s.heavy_model == "qwen2.5:14b"


def test_frontend_serving_is_off_by_default():
    s = Settings(_env_file=None)
    assert s.serve_frontend is False


def test_frontend_dist_defaults_to_the_vite_output_dir():
    s = Settings(_env_file=None)
    assert s.frontend_dist == Path("frontend/dist")


def test_cors_origins_default_to_the_vite_dev_server():
    # Dev must keep working unchanged: this is the literal the middleware
    # used to carry hardcoded in main.py.
    s = Settings(_env_file=None)
    assert s.cors_origins == ["http://localhost:5173"]


def test_cors_origins_can_be_emptied_for_same_origin_serving():
    s = Settings(_env_file=None, cors_origins=[])
    assert s.cors_origins == []


def test_heavy_gets_its_own_provider_and_model():
    """The shipped split: clustering and PLO synthesis run on OpenRouter, the
    stages that write Thai prose stay on the Thai-first default."""
    s = Settings(_env_file=None)
    assert s.llm_provider == "opentyphoon"
    assert s.heavy_provider == "openrouter"
    assert s.heavy_model == "meta-llama/llama-3.3-70b-instruct"
    assert s.light_model == "typhoon-v2.5-30b-a3b-instruct"


def test_heavy_provider_unset_follows_the_default_provider():
    """Same contract as extraction_provider: None means "one endpoint for
    everything", and the model default follows the provider that wins."""
    s = Settings(_env_file=None, llm_provider="ollama", heavy_provider=None)
    assert s.heavy_provider == "ollama"
    assert s.heavy_model == "gemma4:31b-cloud"


def test_an_explicit_heavy_model_survives_the_provider_default():
    s = Settings(_env_file=None, heavy_model="qwen/qwen3-235b-a22b")
    assert s.heavy_provider == "openrouter"
    assert s.heavy_model == "qwen/qwen3-235b-a22b"


def test_skill_extraction_runs_off_the_thai_first_endpoint():
    """Extraction is the fan-out stage — one call per window of every evidence
    item — so it is what exhausts a quota before any other stage has run, and it
    ran Typhoon's out. It gives up little by moving: extraction names skills, it
    does not write the Thai prose the designer reads back. Pinned because it is a
    decision; changing it back should mean changing this line and saying why."""
    s = Settings(_env_file=None)
    assert s.extraction_provider == "openrouter"
    assert s.extraction_model == "meta-llama/llama-3.3-70b-instruct"


def test_extraction_provider_unset_follows_the_default_provider():
    """Running the whole pipeline on one endpoint must not require naming that
    endpoint twice — the model default follows the provider that wins."""
    s = Settings(_env_file=None, llm_provider="ollama", extraction_provider=None)
    assert s.extraction_provider == "ollama"
    assert s.extraction_model == "gemma4:31b-cloud"


def test_an_explicit_extraction_model_survives_the_provider_default():
    s = Settings(_env_file=None, extraction_model="qwen/qwen3-235b-a22b")
    assert s.extraction_model == "qwen/qwen3-235b-a22b"
