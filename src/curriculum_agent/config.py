from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Model names to fall back on when a slot's *_MODEL is left unset. Keyed by
# provider so switching the provider that governs a slot carries that slot's
# model with it.
_PROVIDER_DEFAULT_MODEL: dict[str, str] = {
    "ollama": "gemma4:31b-cloud",
    "openrouter": "meta-llama/llama-3.3-70b-instruct",
    "opentyphoon": "typhoon-v2.5-30b-a3b-instruct",
}


@dataclass(frozen=True)
class SlotSpec:
    """One LLM slot, declared once.

    A slot used to be declared in six places: two Settings fields, an entry in
    the defaults validator, a resolver function in llm.py, a row in `_slots()`,
    and a `complete_*` wrapper. Five slots is where such a spread stops being
    obviously consistent — `_slots()` says so in its own docstring — and adding
    a sixth meant finding all six.

    What each slot needs, and nothing else: the label an operator reads in the
    startup log, where its provider and model are configured, and whether it can
    be switched off. Everything else — defaults, the resolved provider, the
    startup line, the warm-up list — is derived from this list.

    Fields are named rather than passed as accessors so one entry stays one
    line. mypy cannot check a getattr, so `test_llm_slots.py` walks this list
    against `Settings.model_fields` instead: a typo fails pytest rather than
    surfacing as a missing model at boot.
    """

    name: str
    # Every slot has one. This was `str | None` for as long as one slot
    # (`light`, now need_combination) had no provider of its own and rode
    # LLM_PROVIDER directly — which left LLM_PROVIDER doing two jobs: the
    # fallback for any unset slot, and that one slot's actual endpoint. Giving
    # it a field of its own ended both the asymmetry and the double duty.
    provider_field: str
    model_field: str
    # Only validation: "" is its kill switch, and "" must never resolve to
    # llm_provider. Every other slot's provider only selects an endpoint.
    disableable: bool = False


# Pipeline order, not weight order: the startup line then reads as the path a
# designer walks, and a slot's position is a fact about the run rather than a
# guess about how big its model should be. "light" and "heavy" were that guess,
# and both had drifted from what they do. light had one caller left — the Need
# sentence — once evidence classification stopped calling an LLM at all, while
# its docstring still said "classification and Need sentences"; heavy was only
# ever clustering, as its own config comment said outright.
SLOTS: tuple[SlotSpec, ...] = (
    SlotSpec("extraction", "extraction_provider", "extraction_model"),
    SlotSpec("clustering", "clustering_provider", "clustering_model"),
    SlotSpec("need_combination", "need_combination_provider", "need_combination_model"),
    SlotSpec("plo_synthesis", "plo_synthesis_provider", "plo_synthesis_model"),
    SlotSpec("validation", "validation_provider", "validation_model", disableable=True),
)


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
    need_combination_model: str = ""
    # The Need sentence, and only that: `need_combination` calls this slot once
    # per group to write the Thai statement a PLO is later drafted from. It was
    # the `light` slot, named for a size rather than a job, and its docstring
    # still claimed "classification and Need sentences" long after evidence
    # classification became a pure code lookup that calls no model at all.
    #
    # None, not a literal provider: this slot had no provider field until the
    # rename and read `llm_provider` directly, which means "follow the default
    # endpoint, always". Pinning it to opentyphoon here would look like the same
    # thing and quietly stop being it the moment LLM_PROVIDER moved — the
    # Thai-first default is a property of `llm_provider`, and this slot's job is
    # to inherit it.
    need_combination_provider: Literal["ollama", "openrouter", "opentyphoon"] | None = None
    clustering_model: str = ""
    # The clustering slot is LLM clustering, and nothing else. It holds a whole KSEC
    # bucket of skills in one context and reasons over it, which is the work a
    # 30B Thai-first model is weakest at, and it returns a grouping rather than
    # prose — so there is nothing Thai to lose by moving it off Typhoon.
    # None means "whatever llm_provider is", for running the whole pipeline on
    # one endpoint; the model resolves from whichever provider ends up selected.
    clustering_provider: Literal["ollama", "openrouter", "opentyphoon"] | None = "openrouter"
    # PLO synthesis is its own slot rather than part of heavy. Both calls were
    # `heavy` until they had to go different ways: clustering wants the larger
    # model, while a PLO statement is Thai that a curriculum designer submits to
    # MHESI under their own name — the most consequential Thai the pipeline
    # writes. Sharing one knob meant neither could move without the other.
    # It is affordable to leave here: synthesis is at most four calls per PLO
    # (one draft plus up to three SMART repairs) against extraction's one per
    # window of every evidence item, so it is not what exhausts a quota.
    plo_synthesis_provider: Literal["ollama", "openrouter", "opentyphoon"] | None = "opentyphoon"
    plo_synthesis_model: str = ""
    # The SMART validation agent is its own slot, and specifically NOT `heavy`:
    # heavy is LLM clustering and nothing else, and a slot sharing that knob
    # could not be moved without moving clustering. It defaults to OpenRouter —
    # the same model family as heavy — because the loop reasons over a Thai
    # sentence plus a set of tool results rather than writing Thai. When it
    # decides a statement must be repaired it emits an instruction and
    # plo_synthesis_model rewrites the sentence, so a repair is still never
    # answered by a different model than wrote the draft.
    #
    # It is the most expensive slot per PLO: one draft plus up to
    # validation_max_turns loop turns plus up to validation_max_repairs repair
    # drafts, against the previous five calls. That is what
    # validation_max_concurrent_plos bounds.
    #
    # `VALIDATION_PROVIDER=` (empty) skips the agent: the stage keeps the
    # pure-code verdict, which has to exist anyway for an endpoint outage. That
    # is the kill switch — there is no feature flag.
    #
    # The empty string is in the Literal because that is what a blank line in a
    # `.env` file produces, and this field is the one place where empty and
    # None have to mean different things. For every other slot both mean
    # "follow LLM_PROVIDER" — a provider is all they select. Here the setting
    # also answers *whether to run at all*, so None keeps the sibling meaning
    # and "" is off. As documented and never implemented, the kill switch did
    # neither: `VALIDATION_PROVIDER=` failed the Literal and the API would not
    # boot, while leaving it unset resolved to LLM_PROVIDER and the agent kept
    # running. `ValidationReason.DISABLED` was unreachable the whole time.
    validation_provider: Literal["ollama", "openrouter", "opentyphoon", ""] | None = "openrouter"
    validation_model: str = ""
    validation_max_turns: int = 8
    # Three, matching the SMART gate's long-standing retry ceiling — the rule is
    # "max 3 attempts, then escalate", and the agent inherits it rather than
    # introducing a second number for the same policy.
    validation_max_repairs: int = 3
    # In-flight agent *loops*, not calls — deliberately not llm_max_concurrency.
    # A loop is serial (turn n+1 needs turn n's observation), so N concurrent
    # loops is N in-flight calls, and bounding here keeps that provable. It also
    # keeps a deployment that raises the per-call ceiling for extraction from
    # silently multiplying the validation bill.
    validation_max_concurrent_plos: int = 3
    # Wall clock for one PLO's loop. Bounds the whole stage at roughly
    # ceil(N / concurrency) x this, and turns a hung provider into one
    # code-only verdict rather than a stage that never returns.
    validation_timeout_seconds: int = 240
    # skill_extraction has its own knob too, kept separate from the heavy one
    # because it is the stage that decides a quota bill: it is the only one that
    # fans out a call per evidence item, and now one per window of each item
    # rather than one per item. It shipped on the Thai-first default, which is
    # what the knob exists to move — Typhoon's quota is the first thing a real
    # corpus exhausts, and extraction exhausts it before any other stage has run.
    # What it gives up is small: extraction names skills, it does not write the
    # Thai prose a designer reads back. That is `light`, which stays on Typhoon.
    # None means "whatever llm_provider is", for one endpoint end to end.
    extraction_provider: Literal["ollama", "openrouter", "opentyphoon"] | None = "openrouter"
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
        """Resolve every slot's provider, then its model, from `SLOTS`.

        Providers first, and here rather than at each call site, so nothing
        downstream has to remember that None means "follow llm_provider" — and
        so a model default never reads an unresolved None.

        Each model falls back to *its own* provider's default, never to
        llm_provider's: pointing a slot at OpenRouter and leaving its model
        unset would otherwise send a Typhoon model name to OpenRouter, which
        fails as an unknown-model error nowhere near its cause.

        One loop over one list, because this used to be ten `if` statements and
        the tenth was the one that could be forgotten.
        """
        for slot in SLOTS:
            provider = getattr(self, slot.provider_field)
            if provider is None:
                provider = self.llm_provider
                setattr(self, slot.provider_field, provider)
            # "" is left exactly as it is. It is the kill switch, and resolving
            # it to llm_provider is precisely the bug that made the switch a
            # no-op — `or self.llm_provider` here would undo it again, which is
            # why this is an `is None` test.

            if provider and not getattr(self, slot.model_field):
                setattr(self, slot.model_field, _PROVIDER_DEFAULT_MODEL[provider])
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
