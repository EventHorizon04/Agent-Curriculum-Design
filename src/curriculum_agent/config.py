from __future__ import annotations

import urllib.parse
from typing import Literal

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": stray/legacy keys in .env (e.g. from prior experiments)
    # must not crash Settings() — only declared fields are read.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # "ollama" (default, open-source, local) or "openrouter" (paid, hosted).
    # Config-switchable per project rule — never hardcode a paid provider.
    llm_provider: Literal["ollama", "openrouter"] = "openrouter"
    ollama_base_url: str = "http://localhost:11434"
    # No trailing /v1 — the OpenAI client path is appended once, in llm.py.
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str | None = None
    postgres_dsn: str = (
        "postgresql+asyncpg://curriculum:curriculum_dev@localhost:5432/curriculum_agent"
    )
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin_dev"
    light_model: str = "meta-llama/llama-3.3-70b-instruct"
    heavy_model: str = "meta-llama/llama-3.3-70b-instruct"
    # REST API auth secret (require_api_key). None disables auth (dev default).
    api_key: str | None = None
    # Sent as the OpenAI-client api_key when talking to local Ollama. Ollama
    # ignores it for local models; cloud-tagged models (":cloud") are
    # authenticated via the host's own `ollama signin` session, not this
    # value — "ollama" is just a non-empty placeholder the client requires.
    llm_api_key: str = "ollama"
    llm_rate_limit_per_minute: int = 5

    @computed_field  # type: ignore[prop-decorator]
    @property
    def postgres_dsn_sync(self) -> str:
        """psycopg3-compatible DSN (no +asyncpg driver suffix)."""
        return self.postgres_dsn.replace("postgresql+asyncpg://", "postgresql://")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def postgres_dsn_langgraph(self) -> str:
        """psycopg3 DSN with search_path=langgraph to keep LangGraph checkpoint
        tables isolated from the application-level 'checkpoints' table."""
        options = urllib.parse.quote("-c search_path=langgraph")
        return f"{self.postgres_dsn_sync}?options={options}"


settings = Settings()
