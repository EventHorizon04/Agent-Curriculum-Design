from __future__ import annotations

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
    light_model: str = "gemma4:31b-cloud"
    heavy_model: str = "gemma4:31b-cloud"
    api_key: str | None = None

    @computed_field  # type: ignore[misc]
    @property
    def postgres_dsn_sync(self) -> str:
        return self.postgres_dsn.replace("postgresql+asyncpg://", "postgresql://")


settings = Settings()
