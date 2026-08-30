from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Model names to fall back on when LIGHT_MODEL / HEAVY_MODEL / EXTRACTION_MODEL
# are left unset. Keyed by provider so switching the provider that governs a
# slot carries that slot's model with it.
_PROVIDER_DEFAULT_MODEL: dict[str, str] = {
    "ollama": "gemma4:31b-cloud",
    "openrouter": "meta-llama/llama-3.3-70b-instruct",
    "opentyphoon": "typhoon-v2.5-30b-a3b-instruct",
}


class Settings(BaseSettings):
    # extra="ignore": stray/legacy keys in .env (e.g. from prior experiments)
    # must not crash Settings() — only declared fields are read.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # "opentyphoon" by default: every prompt in this pipeline is written in Thai
    # and every stored statement is read by a Thai curriculum designer, and a
    # Thai-first model is what stops a Need's sentence from drifting into
    # translated-sounding Thai. "openrouter" and "ollama" (local, no key) stay
    # one .env line away. Config-switchable per project rule — the default is a
    # setting a deployment overrides, never a provider hardcoded at a call site.
    llm_provider: Literal["ollama", "openrouter", "opentyphoon"] = "opentyphoon"
    ollama_base_url: str = "http://localhost:11434"
    # No trailing /v1 — the OpenAI client path is appended once, in llm.py.
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    opentyphoon_base_url: str = "https://api.opentyphoon.ai/v1"
    # Every credential below is SecretStr, not str: a plain str renders in full
    # on any repr of this object — a failing assertion, a log line, a debugger
    # frame. Read one with .get_secret_value() at the point of use.
    openrouter_api_key: SecretStr | None = None
    opentyphoon_api_key: SecretStr | None = None
    # Must name the asyncpg driver — see _require_asyncpg_driver.
    # 127.0.0.1, not localhost: compose publishes these on the IPv4 loopback
    # only, while getaddrinfo("localhost") hands back ::1 first on Windows.
    # asyncpg and curl fall back to the IPv4 address; psycopg does not, so a
    # "localhost" DSN leaves the API hanging in its lifespan with nothing to
    # read. Spelling it numerically keeps the resolver out of the path.
    postgres_dsn: str = (
        "postgresql+asyncpg://curriculum:curriculum_dev@127.0.0.1:5432/curriculum_agent"
    )
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: SecretStr = SecretStr("minioadmin_dev")
    # Empty means "unset" — _apply_provider_model_defaults fills these in from
    # the provider that governs each slot. They cannot carry a literal default
    # here: a class-body branch on a provider field would be frozen at import
    # time and ignore .env.
    light_model: str = ""
    heavy_model: str = ""
    # The heavy slot gets its own endpoint. Clustering and PLO synthesis are the
    # two calls that have to hold a whole bucket of skills, or a Need plus a
    # Bloom rubric, in one context and reason over it — the work a 30B Thai-first
    # model is weakest at. Their output is also the least Thai-shaped thing the
    # pipeline produces: a grouping decision and a single outcome sentence the
    # designer edits anyway, not the prose that carries the corpus's voice.
    # None means "whatever llm_provider is", for running the whole pipeline on
    # one endpoint; the model resolves from whichever provider ends up selected.
    heavy_provider: Literal["ollama", "openrouter", "opentyphoon"] | None = "openrouter"
    # skill_extraction has its own knob too, kept separate from the heavy one
    # because it is the stage that decides a quota bill: it is the only one that
    # fans out a call per evidence item. It ships on the Thai-first default —
    # it reads Thai evidence and names Thai skills — but the whole point of the
    # field is that moving it off is one line when a quota runs out.
    extraction_provider: Literal["ollama", "openrouter", "opentyphoon"] | None = None
    extraction_model: str = ""
    # REST API auth secret (require_api_key). None disables auth (dev default).
    api_key: SecretStr | None = None
    # Sent as the OpenAI-client api_key when talking to local Ollama. Ollama
    # ignores it for local models; cloud-tagged models (":cloud") are
    # authenticated via the host's own `ollama signin` session, not this
    # value — "ollama" is just a non-empty placeholder the client requires.
    llm_api_key: SecretStr = SecretStr("ollama")
    # Ceiling on in-flight LLM calls when a stage fans out over a corpus. Sized
    # for hosted providers' rate limits; a local Ollama can take more, but the
    # gain is small when one model serves the calls anyway.
    llm_max_concurrency: int = 5
    # Serve the built React bundle from this process, making the API and the UI
    # one origin. False in dev, where Vite serves the UI on 5173 and proxies here.
    serve_frontend: bool = False
    frontend_dist: Path = Path("frontend/dist")
    # Was hardcoded in main.py. Same-origin serving needs no entry at all, so the
    # demo sets this empty; the default keeps the Vite dev server working.
    cors_origins: list[str] = ["http://localhost:5173"]

    @field_validator("postgres_dsn")
    @classmethod
    def _require_asyncpg_driver(cls, dsn: str) -> str:
        """Reject a DSN that does not name asyncpg.

        `postgresql://` is a valid URL that SQLAlchemy resolves to its default
        postgres driver, psycopg2 — which this project does not install. The
        engine in data/postgres.py is built at import time, so the mistake
        surfaces as `ModuleNotFoundError: No module named 'psycopg2'` from
        inside a dialect file, which reads as a broken install rather than a
        one-word typo in .env. The sync and langgraph DSNs are derived from
        this one by dropping the driver, so asking for it here costs nothing.

        The message never quotes the DSN: it carries the password.
        """
        if not dsn.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "POSTGRES_DSN must start with 'postgresql+asyncpg://'. A plain "
                "'postgresql://' URL resolves to psycopg2, which is not installed; "
                "psycopg3 gets its own DSN from postgres_dsn_sync."
            )
        return dsn

    @model_validator(mode="after")
    def _apply_provider_model_defaults(self) -> Settings:
        # Resolved before the model defaults, and here rather than at each call
        # site, so nothing downstream has to remember that None means "follow
        # llm_provider" — and so a model default never reads an unresolved None.
        if self.heavy_provider is None:
            self.heavy_provider = self.llm_provider
        if self.extraction_provider is None:
            self.extraction_provider = self.llm_provider
        # Each model falls back to its own provider's default, not to
        # llm_provider's: pointing heavy at OpenRouter and leaving HEAVY_MODEL
        # unset would otherwise send a Typhoon model name to OpenRouter, which
        # fails as an unknown-model error nowhere near its cause.
        if not self.light_model:
            self.light_model = _PROVIDER_DEFAULT_MODEL[self.llm_provider]
        if not self.heavy_model:
            self.heavy_model = _PROVIDER_DEFAULT_MODEL[self.heavy_provider]
        if not self.extraction_model:
            self.extraction_model = _PROVIDER_DEFAULT_MODEL[self.extraction_provider]
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
