from __future__ import annotations

from pathlib import Path

import pytest

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


def test_postgres_dsn_sync_strips_asyncpg_driver():
    s = Settings(postgres_dsn="postgresql+asyncpg://user:pass@localhost:5432/mydb")
    assert s.postgres_dsn_sync == "postgresql://user:pass@localhost:5432/mydb"


def test_postgres_dsn_sync_unchanged_when_no_asyncpg():
    s = Settings(postgres_dsn="postgresql://user:pass@localhost:5432/mydb")
    assert s.postgres_dsn_sync == "postgresql://user:pass@localhost:5432/mydb"


def test_model_defaults_follow_the_ollama_provider():
    s = Settings(_env_file=None, llm_provider="ollama")
    assert s.light_model == "gemma4:31b-cloud"
    assert s.heavy_model == "gemma4:31b-cloud"


def test_model_defaults_follow_the_openrouter_provider():
    # The provider is read at instance level, not at class-definition time, so
    # switching it in .env must switch the model defaults with it.
    s = Settings(_env_file=None, llm_provider="openrouter")
    assert s.light_model == "meta-llama/llama-3.3-70b-instruct"
    assert s.heavy_model == "meta-llama/llama-3.3-70b-instruct"


def test_explicit_models_survive_the_provider_default():
    s = Settings(
        _env_file=None,
        llm_provider="ollama",
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
