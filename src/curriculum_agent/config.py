from __future__ import annotations

import urllib.parse

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    ollama_base_url: str = "http://localhost:11434"
    qdrant_url: str = "http://localhost:6333"
    postgres_dsn: str = (
        "postgresql+asyncpg://curriculum:curriculum_dev@localhost:5432/curriculum_agent"
    )
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin_dev"
    light_model: str = "scb10x/typhoon2-8b-instruct"
    heavy_model: str = "qwen2.5:7b"
    api_key: str | None = None

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
