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


def _base_url() -> str:
    if settings.llm_provider == "openrouter":
        return settings.openrouter_base_url
    # Ollama exposes an OpenAI-compatible endpoint at /v1.
    return f"{settings.ollama_base_url}/v1"


def _api_key() -> str:
    if settings.llm_provider == "openrouter":
        if not settings.openrouter_api_key:
            raise ValueError("llm_provider is 'openrouter' but OPENROUTER_API_KEY is not set")
        return settings.openrouter_api_key.get_secret_value()
    return settings.llm_api_key.get_secret_value()


def _extra_body() -> dict[str, Any]:
    # keep_alive pins a model in Ollama's VRAM; OpenRouter has no such concept
    # and does not recognize the field.
    if settings.llm_provider == "openrouter":
        return {}
    return {"keep_alive": -1}


@functools.cache
def _get_client() -> instructor.AsyncInstructor:
    """Lazy singleton — created on first call, not at import time."""
    return instructor.from_openai(
        AsyncOpenAI(base_url=_base_url(), api_key=_api_key()),
        mode=instructor.Mode.JSON,
    )


@functools.cache
def _get_raw_client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=_base_url(), api_key=_api_key())


async def complete_light(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """Light model used for classification and SMART validation."""
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

    No-op for OpenRouter — there is no local VRAM to warm.
    """
    if settings.llm_provider == "openrouter":
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
