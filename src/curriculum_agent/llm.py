from __future__ import annotations

import functools
from typing import Any, TypeVar, cast

import instructor
from loguru import logger
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from curriculum_agent.config import settings

T = TypeVar("T", bound=BaseModel)

# Providers reached over the network, where the model is not ours to pin in VRAM.
# Ollama is the only local one.
_HOSTED_PROVIDERS = frozenset({"openrouter", "opentyphoon"})


# Every helper below takes the provider rather than reading settings.llm_provider,
# because two endpoints are in play: the pipeline's default, and whichever one
# skill_extraction is routed to (settings.extraction_provider). A helper that
# resolved the provider itself would silently send extraction's model to the
# default endpoint, which fails as an unknown-model error far from its cause.


def _base_url(provider: str) -> str:
    if provider == "openrouter":
        return settings.openrouter_base_url
    elif provider == "opentyphoon":
        return settings.opentyphoon_base_url
    # Ollama exposes an OpenAI-compatible endpoint at /v1.
    return f"{settings.ollama_base_url}/v1"


def _api_key(provider: str) -> str:
    if provider == "openrouter":
        if not settings.openrouter_api_key:
            raise ValueError("provider 'openrouter' is selected but OPENROUTER_API_KEY is not set")
        return settings.openrouter_api_key.get_secret_value()
    elif provider == "opentyphoon":
        if not settings.opentyphoon_api_key:
            raise ValueError(
                "provider 'opentyphoon' is selected but OPENTYPHOON_API_KEY is not set"
            )
        return settings.opentyphoon_api_key.get_secret_value()
    return settings.llm_api_key.get_secret_value()


def _extra_body(provider: str) -> dict[str, Any]:
    # keep_alive pins a model in Ollama's VRAM; a hosted provider has no such
    # concept and does not recognize the field.
    if provider in _HOSTED_PROVIDERS:
        return {}
    return {"keep_alive": -1}


def _extraction_provider() -> str:
    """Provider for skill_extraction. Settings resolves None to llm_provider."""
    return settings.extraction_provider or settings.llm_provider


def _key_state(provider: str) -> str:
    try:
        return "set" if _api_key(provider) else "empty"
    except ValueError:
        # The provider needs a key and none is configured. Say so here rather than
        # letting the first real call fail with the same message 40 frames deep.
        return "MISSING"


def describe_target() -> str:
    """Which LLM endpoints and models this process talks to, as one log line.

    Both are reported, because they can differ: skill_extraction has its own
    provider, and "the wrong model answered" is impossible to diagnose from a
    line that names only the default one.

    Never includes an API key. It reports only whether one is configured, which
    is the part that is actually useful when a call fails — the value itself is a
    credential and does not belong in a log file, a terminal, or a bug report.
    Base URLs are safe: they are public endpoints, and for Ollama the host is the
    operator's own machine.
    """
    provider = settings.llm_provider
    extraction = _extraction_provider()
    return (
        f"LLM target: provider={provider} base_url={_base_url(provider)} "
        f"api_key={_key_state(provider)} light={settings.light_model} "
        f"heavy={settings.heavy_model} | extraction: provider={extraction} "
        f"base_url={_base_url(extraction)} api_key={_key_state(extraction)} "
        f"model={settings.extraction_model}"
    )


def log_target() -> None:
    """Log describe_target() at INFO. Safe to call more than once."""
    logger.info(describe_target())


@functools.cache
def _get_client(provider: str) -> instructor.AsyncInstructor:
    """Lazy per-provider singleton — created on first call, not at import time.

    Cached on the provider so the two endpoints in play get one client each
    rather than one client that silently belongs to whichever stage called first.
    """
    logger.info(f"Creating LLM client for provider '{provider}' at {_base_url(provider)}")
    return instructor.from_openai(
        AsyncOpenAI(base_url=_base_url(provider), api_key=_api_key(provider)),
        mode=instructor.Mode.JSON,
    )


@functools.cache
def _get_raw_client(provider: str) -> AsyncOpenAI:
    logger.info(f"Creating raw LLM client for provider '{provider}' at {_base_url(provider)}")
    return AsyncOpenAI(base_url=_base_url(provider), api_key=_api_key(provider))


async def _complete(
    provider: str,
    model: str,
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """One structured completion against one endpoint.

    The three public wrappers differ only in which provider and model they name,
    so the call itself lives here — otherwise a change to instructor's contract
    has to be made three times and will eventually be made twice.
    """
    logger.debug(f"LLM call: {model} ({provider})")
    return await _get_client(provider).chat.completions.create(
        model=model,
        response_model=response_model,
        # Prompt builders emit OpenAI-shaped role/content dicts; cast to the SDK's
        # message param type instead of restructuring at runtime.
        messages=cast(list[ChatCompletionMessageParam], messages),
        extra_body=_extra_body(provider),
        **kwargs,
    )


async def complete_light(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """Light model used for classification, Need sentences and SMART validation."""
    return await _complete(
        settings.llm_provider, settings.light_model, response_model, messages, **kwargs
    )


async def complete_heavy(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """Heavy model used for clustering and PLO synthesis."""
    return await _complete(
        settings.llm_provider, settings.heavy_model, response_model, messages, **kwargs
    )


async def complete_extraction(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """skill_extraction's own endpoint — see Settings.extraction_provider.

    Separate from complete_light/heavy rather than a flag on them: extraction is
    a per-evidence fan-out whose cost and quota profile is nothing like the
    handful of calls the other stages make, and the cache key it writes is keyed
    on this model name. A stage picking the endpoint per call would put that
    decision somewhere the cache cannot see it.
    """
    return await _complete(
        _extraction_provider(), settings.extraction_model, response_model, messages, **kwargs
    )


async def warmup_models() -> None:
    """Push every locally-served model into Ollama VRAM at startup.

    Hosted providers are skipped — there is no local VRAM to warm, and the
    warm-up call would spend a real request (and, on a paid provider, real money)
    on a prompt whose answer is thrown away. Both targets are considered, since
    only one of them may be the local one.
    """
    local = {
        model
        for provider, model in (
            (settings.llm_provider, settings.light_model),
            (settings.llm_provider, settings.heavy_model),
            (_extraction_provider(), settings.extraction_model),
        )
        if provider not in _HOSTED_PROVIDERS
    }
    if not local:
        return
    client = _get_raw_client("ollama")
    for model_name in sorted(local):
        try:
            await client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
                extra_body={"keep_alive": -1},
            )
            logger.info(f"Warmed up Ollama model: {model_name}")
        except Exception as exc:
            logger.warning(f"Model warmup failed for {model_name}: {exc}")
