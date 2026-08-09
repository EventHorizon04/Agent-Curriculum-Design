from __future__ import annotations

import urllib.parse
from typing import Literal

from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Model names to fall back on when LIGHT_MODEL / HEAVY_MODEL are left unset.
# Keyed by provider so switching LLM_PROVIDER carries the models with it.
_PROVIDER_DEFAULT_MODEL: dict[str, str] = {
    "ollama": "gemma4:31b-cloud",
    "openrouter": "meta-llama/llama-3.3-70b-instruct",
}


class Settings(BaseSettings):
    # extra="ignore": stray/legacy keys in .env (e.g. from prior experiments)
    # must not crash Settings() — only declared fields are read.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # "ollama" (default, open-source, local) or "openrouter" (paid, hosted).
    # Config-switchable per project rule — never hardcode a paid provider.
    llm_provider: Literal["ollama", "openrouter"] = "ollama"
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
    # Empty means "unset" — _apply_provider_model_defaults fills these in from
    # llm_provider. They cannot carry a literal default here: a class-body
    # branch on llm_provider would be frozen at import time and ignore .env.
    light_model: str = ""
    heavy_model: str = ""
    # REST API auth secret (require_api_key). None disables auth (dev default).
    api_key: str | None = None
    # Sent as the OpenAI-client api_key when talking to local Ollama. Ollama
    # ignores it for local models; cloud-tagged models (":cloud") are
    # authenticated via the host's own `ollama signin` session, not this
    # value — "ollama" is just a non-empty placeholder the client requires.
    llm_api_key: str = "ollama"

    @model_validator(mode="after")
    def _apply_provider_model_defaults(self) -> Settings:
        fallback = _PROVIDER_DEFAULT_MODEL[self.llm_provider]
        if not self.light_model:
            self.light_model = fallback
        if not self.heavy_model:
            self.heavy_model = fallback
        return self

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
