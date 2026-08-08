from __future__ import annotations

from curriculum_agent.config import Settings


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
