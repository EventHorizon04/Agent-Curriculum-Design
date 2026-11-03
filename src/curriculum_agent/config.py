from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Model names to fall back on when a slot's *_MODEL is left unset. Keyed by
# provider so switching the provider that governs a slot carries that slot's
# model with it.
#
# OpenRouter's was meta-llama/llama-3.3-70b-instruct until 2026-10-01. Every
# probe that compared the two on this pipeline's own data chose glm-5.3-flash
# (extraction, validation, the duplicate check — see their SLOTS entries), so
# the default moved. Clustering is the exception and pins llama itself; its
# SLOTS entry says why.
_PROVIDER_DEFAULT_MODEL: dict[str, str] = {
    "ollama": "gemma4:31b-cloud",
    "openrouter": "z-ai/glm-5.3-flash",
    "opentyphoon": "typhoon-v2.5-30b-a3b-instruct",
}

# Branch feat/four-agent-pipeline runs every slot on one model so research runs
# compare cleanly; PIPELINE_PROVIDER="" restores the per-slot choices below.
_BRANCH_PIPELINE_PROVIDER = "openrouter"
_BRANCH_PIPELINE_MODEL = "z-ai/glm-5.3-flash"

# The credentials this file ships so a checkout runs against the compose stack
# with no .env at all. They are named here rather than written inline on the
# fields because `_refuse_development_credentials_in_production` has to compare
# against them: a default that is only a literal in a field declaration is a
# default nothing can detect it is still using.
#
# Convenience in development, a silent hole anywhere else. A deployment that
# forgets MINIO_SECRET_KEY does not fail — it starts, connects to whatever
# answers, and looks healthy. APP_ENV=production is what turns that into a
# refusal at startup.
_DEV_POSTGRES_DSN = "postgresql+asyncpg://curriculum:curriculum_dev@127.0.0.1:5432/curriculum_agent"
_DEV_MINIO_ACCESS_KEY = "minioadmin"
_DEV_MINIO_SECRET_KEY = "minioadmin_dev"


# Slot settings that were renamed, and what to say when one turns up.
#
# `extra="ignore"` is what makes this necessary: a .env carrying HEAVY_MODEL
# after the rename is not an error to pydantic, it is a line nobody reads. The
# run then starts on the provider default while the operator believes they
# selected a model — the failure is silent, and the slot they configured is the
# one they cannot see in the startup log. Declaring the old names as fields is
# what lets a validator refuse them: pydantic populates them from .env and the
# environment alike, so neither has to be parsed here.
_RENAMED_SLOT_SETTINGS: dict[str, str] = {
    "light_model": "need_combination_model",
    "heavy_provider": "clustering_provider",
    "heavy_model": "clustering_model",
    "synthesis_provider": "plo_synthesis_provider",
    "synthesis_model": "plo_synthesis_model",
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
    # This slot's own model choice, per provider, for the providers where it
    # differs from `_PROVIDER_DEFAULT_MODEL`. Keyed by provider because a model
    # name is only meaningful at one endpoint: pinning a slot to one string
    # would send an OpenRouter model id to Typhoon the moment someone moved the
    # slot's provider.
    #
    # It exists so a model choice is a line of code rather than a line of .env.
    # Which model a stage runs on is an engineering decision about that stage —
    # extraction quotes evidence verbatim and needs a model that can, and that
    # reasoning belongs in the repository next to the slot it is about, under
    # review, the same for everyone. `.env` is for secrets and for what differs
    # between machines; a model name is neither. Only providers listed here are
    # overridden, so a slot that is happy with its provider's default declares
    # nothing.
    default_models: Mapping[str, str] = field(default_factory=dict)
    # need_dedup and validation: "" is their kill switch, and "" must never
    # resolve to llm_provider. Every other slot's provider only selects an
    # endpoint.
    disableable: bool = False


# Pipeline order, not weight order: the startup line then reads as the path a
# designer walks, and a slot's position is a fact about the run rather than a
# guess about how big its model should be. "light" and "heavy" were that guess,
# and both had drifted from what they do. light had one caller left — the Need
# sentence — once evidence classification stopped calling an LLM at all, while
# its docstring still said "classification and Need sentences"; heavy was only
# ever clustering, as its own config comment said outright.
SLOTS: tuple[SlotSpec, ...] = (
    # extraction quotes the evidence verbatim — `evidence_span_th` is checked
    # against the source by `is_grounded` and an invented span is dropped — so
    # this slot is chosen on how well a model copies, not on how well it writes.
    # Probed on the real schema against one stored window: glm-5.3-flash
    # returned 5 skills with 5/5 grounded in 37.5s, llama-3.3-70b 6 with 4/6 in
    # 13.8s. Quoting is immutable rule 2, so the slower model is the safer one.
    SlotSpec(
        "extraction",
        "extraction_provider",
        "extraction_model",
        default_models={"openrouter": "z-ai/glm-5.3-flash"},
    ),
    # Pinned to llama-3.3-70b, not the provider default. glm-5.3-flash was tried
    # here on 2026-10-01 and cannot fit the stage: on the stored corpus its
    # hidden reasoning took 374.7s on the 53-name S bucket alone and 473s for
    # all four calls, against need_combination's 300s route timeout. Bounding
    # the reasoning brought it to 25s, but this endpoint treats any bound as
    # reasoning off, and an unreasoned glm grouping is unmeasured. llama is
    # also the model ticket 16 measured this slot on, so its figures stay
    # comparable.
    SlotSpec(
        "clustering",
        "clustering_provider",
        "clustering_model",
        default_models={"openrouter": "meta-llama/llama-3.3-70b-instruct"},
    ),
    SlotSpec("need_combination", "need_combination_provider", "need_combination_model"),
    # Runs at the start of plo_synthesis, before any draft, so it sits here in
    # pipeline order. Probed on the 9 stored in-scope Needs (design doc,
    # "Measured"), 3 runs each: llama-3.3-70b (the clustering model, then also
    # the provider default) folded 1fe0 with d7c4+5dd3 and 396a with 9d07 every
    # run — neither pair shares a main task and object — while glm-5.3-flash
    # folded only 252f+6a45 and afe6+befb, left 1fe0/396a/9d07 ungrouped, on
    # all 3 runs.
    SlotSpec(
        "need_dedup",
        "need_dedup_provider",
        "need_dedup_model",
        default_models={"openrouter": "z-ai/glm-5.3-flash"},
        disableable=True,
    ),
    SlotSpec("plo_synthesis", "plo_synthesis_provider", "plo_synthesis_model"),
    # Same reasoning as extraction, and the same model: this loop reads a Thai
    # sentence plus tool results and emits an instruction, so it is judged on
    # following a schema rather than on Thai prose.
    SlotSpec(
        "validation",
        "validation_provider",
        "validation_model",
        default_models={"openrouter": "z-ai/glm-5.3-flash"},
        disableable=True,
    ),
    # Reads the finished PLO set once, after synthesis, and reports — it never
    # writes a statement. glm-5.3-flash for the same reason as need_dedup: the
    # task is judging and labelling, and one call per program pays its reasoning
    # latency once. disableable: the review is advisory, so "" turns it off.
    # Its hidden reasoning is bounded at the call (stages/plo_review_agent._MAX_REASONING_TOKENS)
    # because unbounded it did not finish inside the timeout.
    SlotSpec(
        "plo_review",
        "plo_review_provider",
        "plo_review_model",
        default_models={"openrouter": "z-ai/glm-5.3-flash"},
        disableable=True,
    ),
)


class Settings(BaseSettings):
    # extra="ignore": stray/legacy keys in .env (e.g. from prior experiments)
    # must not crash Settings() — only declared fields are read.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Which half of the contract this process is held to. Everything in this
    # file has a default that works on a fresh checkout, which is the right
    # trade for development and the wrong one anywhere a real person's data
    # lands: the credentials below are in the repository, so a deployment that
    # forgets to set them starts anyway and looks healthy.
    #
    # "production" turns those defaults into a startup refusal
    # (`_refuse_development_credentials_in_production`). It is a setting rather
    # than a build flag because the same image runs in both, and it defaults to
    # development so that forgetting it can only ever make the check stricter
    # by accident, never weaker.
    app_env: Literal["development", "production"] = "development"

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
    postgres_dsn: str = _DEV_POSTGRES_DSN
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = _DEV_MINIO_ACCESS_KEY
    minio_secret_key: SecretStr = SecretStr(_DEV_MINIO_SECRET_KEY)
    # Empty means "unset" — _apply_provider_model_defaults fills these in from
    # the provider that governs each slot. They cannot carry a literal default
    # here: a class-body branch on a provider field would be frozen at import
    # time and ignore .env.
    need_combination_model: str = ""
    # This branch runs every slot on one model, so the GLM pair is the default.
    # Per slot: own *_PROVIDER/*_MODEL, then these, then slot default, then
    # LLM_PROVIDER. The pair resolves together: the model only reaches slots whose
    # provider came from PIPELINE_PROVIDER, and the default model belongs to the
    # default provider only. PIPELINE_PROVIDER="" turns the pair off and every slot
    # resolves per slot, as on main.
    pipeline_provider: Literal["ollama", "openrouter", "opentyphoon", ""] | None = (
        _BRANCH_PIPELINE_PROVIDER  # type: ignore[assignment]
    )
    pipeline_model: str = _BRANCH_PIPELINE_MODEL
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
    # The duplicate check before PLO synthesis: one call per synthesis run that
    # reads every in-scope Need's sentence and answers with groups of labels —
    # a grouping, not Thai prose, which is why it defaults to OpenRouter beside
    # clustering. Its own knob, so neither can move without the other.
    #
    # Disableable, like validation and for the same reason: the step is a check
    # the stage can run without. `NEED_DEDUP_PROVIDER=` (empty) skips the call
    # and every Need gets its own slot, which is also what an outage falls back
    # to — and the baseline any measurement of this step is taken against.
    need_dedup_provider: Literal["ollama", "openrouter", "opentyphoon", ""] | None = "openrouter"
    need_dedup_model: str = ""
    # How many times the duplicate check reads the same Needs, in parallel; only
    # groups a majority agrees on are merged. 1 restores the single call.
    need_dedup_runs: int = Field(default=5, ge=1)
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
    # Wall clock for each of the three Agent 1 / Agent 2 job steps (extraction,
    # grouping, need_combination), one budget apiece. It was 300 until 2026-10-28;
    # the designer raised it while run time is not a concern on this branch, since
    # cold GLM runs measured extraction at 240-300 s.
    need_job_step_timeout_seconds: int = Field(default=900, ge=1)
    # The PLO set review (stages/plo_review.py). Advisory: "" (empty) switches it
    # off and the report says so; None follows LLM_PROVIDER like every slot.
    plo_review_provider: Literal["ollama", "openrouter", "opentyphoon", ""] | None = "openrouter"
    plo_review_model: str = ""
    # Wall clock for the whole agent run (up to six steps), not one call.
    plo_review_timeout_seconds: int = 300
    # How many times the QA agent reads the same dossier, in parallel; the stored
    # review keeps what a majority agrees on. 1 restores the single-run review.
    plo_review_runs: int = Field(default=5, ge=1)
    # Phase 4: after a fresh agent review, send its agreed redundancy / Bloom /
    # unused-Need findings back as redrafts (stages/plo_feedback.py), each with a
    # trail row. False restores the advisory-only review.
    plo_review_send_back: bool = True
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
    # Output bounds for the extraction call (phase 5). Measured 2026-11-03
    # (.scratch/reports/2026-11-03-phase5-extraction.md): about 89% of unbounded
    # extraction output is hidden reasoning, and bounding it took Agent 1 from
    # ~255 s to ~47 s for -9.1% skills and -1.6% grounding. 0 means "no bound":
    # nothing is sent and the cache key is the pre-bound one. A positive bound can
    # change what the model returns, so skill_extraction puts it in the cache key.
    extraction_max_tokens: int = Field(default=4096, ge=0)
    extraction_reasoning_max_tokens: int = Field(default=1024, ge=0)
    # Accepted only to be refused — see _RENAMED_SLOT_SETTINGS and
    # _reject_renamed_slot_settings. They hold no value the program reads, and
    # `exclude=True` keeps them out of any dump of this object.
    light_model: str | None = Field(default=None, exclude=True)
    heavy_provider: str | None = Field(default=None, exclude=True)
    heavy_model: str | None = Field(default=None, exclude=True)
    synthesis_provider: str | None = Field(default=None, exclude=True)
    synthesis_model: str | None = Field(default=None, exclude=True)
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
    def _reject_renamed_slot_settings(self) -> Settings:
        """Refuse a slot setting under its old name instead of ignoring it.

        Raised rather than logged: a warning about a model that is not being
        used scrolls past, and what follows is a whole run on an endpoint
        nobody chose. Every name is reported at once, so one restart tells the
        operator everything they have to change.
        """
        stale = [(old, new) for old, new in _RENAMED_SLOT_SETTINGS.items() if getattr(self, old)]
        if stale:
            lines = "; ".join(f"{old.upper()} -> {new.upper()}" for old, new in stale)
            raise ValueError(
                "LLM slot settings were renamed after each slot was named for the stage "
                f"that calls it. These are no longer read: {lines}. "
                "Rename them in .env, or unset them."
            )
        return self

    @model_validator(mode="after")
    def _resolve_pipeline_pair(self) -> Settings:
        """Normalise the pipeline pair, then refuse a model with the pair turned off.

        Runs before `_apply_provider_model_defaults` (validators run in definition
        order), so that sees only a resolved pair. "" means off and becomes None,
        keeping every later `is None` test. The default model belongs to the
        default provider: a provider set on its own drops it, so GLM's name never
        lands on another endpoint. A model set explicitly while the pair is off is
        an error, since it would silently do nothing.
        """
        if self.pipeline_provider == "":
            self.pipeline_provider = None
        fields = self.model_fields_set
        if "pipeline_provider" in fields and "pipeline_model" not in fields:
            self.pipeline_model = ""
        if self.pipeline_provider is None:
            if self.pipeline_model and "pipeline_model" in fields:
                raise ValueError(
                    "PIPELINE_MODEL requires PIPELINE_PROVIDER to be non-empty; "
                    "an empty PIPELINE_PROVIDER turns the pipeline pair off."
                )
            self.pipeline_model = ""
        return self

    @model_validator(mode="after")
    def _refuse_development_credentials_in_production(self) -> Settings:
        """Under APP_ENV=production, refuse the credentials this file ships.

        Every one of them is in the repository, so they authenticate nothing —
        and the failure they cause without this check is the bad kind: the
        process starts, connects to whatever is listening on the default port,
        and reports itself healthy. A missing secret should stop a deployment,
        loudly, at startup, rather than after it has written somewhere nobody
        meant it to.

        `api_key` is in the list because `require_api_key` treats None as "auth
        is off", which is the right default for a laptop and an open door on a
        public address. It is the one entry that is about absence rather than a
        known value, and it is the same mistake either way: a credential nobody
        set.

        Every failure is reported in one message. An operator bringing up a new
        environment usually has more than one of these unset, and a validator
        that names only the first turns one fix into three restarts.
        """
        if self.app_env != "production":
            return self

        unset: list[str] = []
        if self.postgres_dsn == _DEV_POSTGRES_DSN:
            unset.append("POSTGRES_DSN (still the checked-in development DSN)")
        if self.minio_access_key == _DEV_MINIO_ACCESS_KEY:
            unset.append("MINIO_ACCESS_KEY (still 'minioadmin')")
        if self.minio_secret_key.get_secret_value() == _DEV_MINIO_SECRET_KEY:
            unset.append("MINIO_SECRET_KEY (still the checked-in development value)")
        if self.api_key is None:
            unset.append("API_KEY (unset means every write endpoint is unauthenticated)")

        if unset:
            raise ValueError(
                "APP_ENV=production, but these are still at their development "
                "defaults and must be set in the environment:\n  - " + "\n  - ".join(unset)
            )
        return self

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

        A slot's own `default_models` wins over the provider-wide default, and
        is looked up by the provider that was just resolved rather than by the
        one declared on the field — so a slot moved to another endpoint gets
        that endpoint's model, not a name only its usual provider would know.

        One loop over one list, because this used to be ten `if` statements and
        the tenth was the one that could be forgotten.
        """
        # Snapshot first: setattr below adds names to model_fields_set, and a
        # class-level default (extraction's "openrouter") must not count as set.
        explicit = set(self.model_fields_set)
        for slot in SLOTS:
            provider = getattr(self, slot.provider_field)
            from_pipeline = False
            # PIPELINE_PROVIDER outranks the slot's class default but never the
            # slot's own env/kwarg setting, "" (the kill switch) included.
            if self.pipeline_provider is not None and slot.provider_field not in explicit:
                provider = self.pipeline_provider
                from_pipeline = True
                setattr(self, slot.provider_field, provider)
            elif provider is None:
                provider = self.llm_provider
                setattr(self, slot.provider_field, provider)
            # "" is left exactly as it is. It is the kill switch, and resolving
            # it to llm_provider is precisely the bug that made the switch a
            # no-op — `or self.llm_provider` here would undo it again, which is
            # why this is an `is None` test.

            if provider and not getattr(self, slot.model_field):
                # PIPELINE_MODEL is half of a pair: only a slot that took
                # PIPELINE_PROVIDER, and named no model of its own, may use it.
                if from_pipeline and self.pipeline_model and slot.model_field not in explicit:
                    chosen = self.pipeline_model
                else:
                    chosen = slot.default_models.get(provider, _PROVIDER_DEFAULT_MODEL[provider])
                setattr(self, slot.model_field, chosen)
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
