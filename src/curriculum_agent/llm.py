from __future__ import annotations

import functools
from typing import Any, TypeVar

import instructor
from loguru import logger
from openai import AsyncOpenAI
from pydantic import BaseModel

from curriculum_agent.config import settings

T = TypeVar("T", bound=BaseModel)


@functools.cache
def _get_client() -> instructor.AsyncInstructor:
    """Lazy singleton — created on first call, not at import time.

    Ollama exposes an OpenAI-compatible endpoint at /v1.
    """
    return instructor.from_openai(
        AsyncOpenAI(
            base_url=f"{settings.ollama_base_url}/v1",
            api_key="ollama",
        ),
        mode=instructor.Mode.JSON,
    )


@functools.cache
def _get_raw_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=f"{settings.ollama_base_url}/v1",
        api_key="ollama",
    )


async def complete_light(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """Typhoon 2 8B — fast, used for classification and SMART validation."""
    return await _get_client().chat.completions.create(
        model=settings.light_model,
        response_model=response_model,
        messages=messages,
        extra_body={"keep_alive": -1},
        **kwargs,
    )


async def complete_heavy(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """Qwen 2.5 14B/32B — used for PLO synthesis."""
    return await _get_client().chat.completions.create(
        model=settings.heavy_model,
        response_model=response_model,
        messages=messages,
        extra_body={"keep_alive": -1},
        **kwargs,
    )


async def warmup_models() -> None:
    """Push light and heavy models into Ollama VRAM at startup."""
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
