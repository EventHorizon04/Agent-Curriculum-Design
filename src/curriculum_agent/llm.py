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


def _base_url() -> str:
    if settings.llm_provider == "openrouter":
        return settings.openrouter_base_url
    # Ollama exposes an OpenAI-compatible endpoint at /v1.
    elif settings.llm_provider == "opentyphoon":
        return settings.opentyphoon_base_url
    return f"{settings.ollama_base_url}/v1"


def _api_key() -> str:
    if settings.llm_provider == "openrouter":
        if not settings.openrouter_api_key:
            raise ValueError("llm_provider is 'openrouter' but OPENROUTER_API_KEY is not set")
        return settings.openrouter_api_key.get_secret_value()
    elif settings.llm_provider == "opentyphoon":
        if not settings.opentyphoon_api_key:
            raise ValueError("llm_provider is 'opentyphoon' but OPENTYPHOON_API_KEY is not set")
        return settings.opentyphoon_api_key.get_secret_value()
    return settings.llm_api_key.get_secret_value()


def _extra_body() -> dict[str, Any]:
    # keep_alive pins a model in Ollama's VRAM; OpenRouter has no such concept
    # and does not recognize the field.
    if settings.llm_provider in _HOSTED_PROVIDERS:
        return {}
    return {"keep_alive": -1}


def describe_target() -> str:
    """Which LLM endpoint and models this process talks to, as one log line.

    Never includes the API key. It reports only whether one is configured, which
    is the part that is actually useful when a call fails — the value itself is a
    credential and does not belong in a log file, a terminal, or a bug report.
    Base URLs are safe: they are public endpoints, and for Ollama the host is the
    operator's own machine.
    """
    provider = settings.llm_provider
    try:
        key_state = "set" if _api_key() else "empty"
    except ValueError:
        # The provider needs a key and none is configured. Say so here rather than
        # letting the first real call fail with the same message 40 frames deep.
        key_state = "MISSING"
    return (
        f"LLM target: provider={provider} base_url={_base_url()} api_key={key_state} "
        f"light={settings.light_model} heavy={settings.heavy_model}"
    )


def log_target() -> None:
    """Log describe_target() at INFO. Safe to call more than once."""
    logger.info(describe_target())


@functools.cache
def _get_client() -> instructor.AsyncInstructor:
    """Lazy singleton — created on first call, not at import time."""
    # Logged from inside the cached builder so it fires exactly once per process,
    # at the moment the connection is actually configured. A module-level log
    # would fire on import, before .env-driven settings could have failed.
    logger.info(f"Creating LLM client — {describe_target()}")
    return instructor.from_openai(
        AsyncOpenAI(base_url=_base_url(), api_key=_api_key()),
        mode=instructor.Mode.JSON,
    )


@functools.cache
def _get_raw_client() -> AsyncOpenAI:
    logger.info(f"Creating raw LLM client — {describe_target()}")
    return AsyncOpenAI(base_url=_base_url(), api_key=_api_key())


async def complete_light(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """Light model used for classification and SMART validation."""
    logger.debug(f"LLM light call: {settings.light_model} ({settings.llm_provider})")
    return await _get_client().chat.completions.create(
        model=settings.light_model,
        response_model=response_model,
        # Prompt builders emit OpenAI-shaped role/content dicts; cast to the SDK's
        # message param type instead of restructuring at runtime.
        messages=cast(list[ChatCompletionMessageParam], messages),
        extra_body=_extra_body(),
        **kwargs,
    )


async def complete_heavy(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """Heavy model used for PLO synthesis."""
    logger.debug(f"LLM heavy call: {settings.heavy_model} ({settings.llm_provider})")
    return await _get_client().chat.completions.create(
        model=settings.heavy_model,
        response_model=response_model,
        # Same OpenAI-shaped messages cast as complete_light above.
        messages=cast(list[ChatCompletionMessageParam], messages),
        extra_body=_extra_body(),
        **kwargs,
    )


async def warmup_models() -> None:
    """Push light and heavy models into Ollama VRAM at startup.

    No-op for every hosted provider — there is no local VRAM to warm, and the
    warm-up call would spend a real request (and, on a paid provider, real money)
    on a prompt whose answer is thrown away.
    """
    if settings.llm_provider in _HOSTED_PROVIDERS:
        return
    client = _get_raw_client()
    for model_name in dict.fromkeys([settings.light_model, settings.heavy_model]):
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
