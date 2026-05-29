from __future__ import annotations

import functools
from typing import Any, TypeVar

import instructor
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
        **kwargs,
    )


async def complete_heavy(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """Qwen 2.5 14B/32B — used for PLO synthesis and YLO derivation."""
    return await _get_client().chat.completions.create(
        model=settings.heavy_model,
        response_model=response_model,
        messages=messages,
        **kwargs,
    )
