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
# because five endpoints are in play: the pipeline's default (light), and one
# each for heavy, plo_synthesis, skill_extraction and the SMART validation
# agent. A helper that resolved the provider itself would silently send one
# slot's model to another slot's endpoint, which fails as an unknown-model error
# far from its cause.


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


def _heavy_provider() -> str:
    """Provider for the heavy slot. Settings resolves None to llm_provider."""
    return settings.heavy_provider or settings.llm_provider


def _synthesis_provider() -> str:
    """Provider for plo_synthesis. Settings resolves None to llm_provider."""
    return settings.synthesis_provider or settings.llm_provider


def _extraction_provider() -> str:
    """Provider for skill_extraction. Settings resolves None to llm_provider."""
    return settings.extraction_provider or settings.llm_provider


def _validation_provider() -> str:
    """Provider for the SMART validation agent. Settings resolves None to llm_provider."""
    return settings.validation_provider or settings.llm_provider


def _slots() -> tuple[tuple[str, str, str], ...]:
    """Every slot as (label, provider, model), resolved now.

    One list, three readers — describe_target, warmup_models, and the config
    tests. Both of the first two used to enumerate the slots by hand, and five
    is where such a list stops being obviously complete: a sixth slot added to
    only one of them would be a model nobody warms or a model nobody can see in
    the startup log.
    """
    return (
        ("light", settings.llm_provider, settings.light_model),
        ("heavy", _heavy_provider(), settings.heavy_model),
        ("synthesis", _synthesis_provider(), settings.synthesis_model),
        ("extraction", _extraction_provider(), settings.extraction_model),
        ("validation", _validation_provider(), settings.validation_model),
    )


def _key_state(provider: str) -> str:
    try:
        return "set" if _api_key(provider) else "empty"
    except ValueError:
        # The provider needs a key and none is configured. Say so here rather than
        # letting the first real call fail with the same message 40 frames deep.
        return "MISSING"


def _describe_slot(label: str, provider: str, model: str) -> str:
    return (
        f"{label}: provider={provider} base_url={_base_url(provider)} "
        f"api_key={_key_state(provider)} model={model}"
    )


def describe_target() -> str:
    """Which LLM endpoints and models this process talks to, as one log line.

    Every slot is reported, because they can differ: heavy, plo_synthesis,
    skill_extraction and the SMART validation agent each have their own
    provider, and "the wrong model answered" is impossible to diagnose from a
    line that names only one of them.

    Never includes an API key. It reports only whether one is configured, which
    is the part that is actually useful when a call fails — the value itself is a
    credential and does not belong in a log file, a terminal, or a bug report.
    Base URLs are safe: they are public endpoints, and for Ollama the host is the
    operator's own machine.
    """
    return "LLM target: " + " | ".join(
        _describe_slot(label, provider, model) for label, provider, model in _slots()
    )


def log_target() -> None:
    """Log describe_target() at INFO. Safe to call more than once."""
    logger.info(describe_target())


@functools.cache
def _get_client(provider: str) -> instructor.AsyncInstructor:
    """Lazy per-provider singleton — created on first call, not at import time.

    Cached on the provider so the endpoints in play get one client each rather
    than one client that silently belongs to whichever stage called first.
    Slots that share a provider share the client, which is what makes the
    all-on-one-endpoint arrangement cost one connection pool rather than three.
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

    The public wrappers differ only in which provider and model they name, so
    the call itself lives here — otherwise a change to instructor's contract has
    to be made once per slot and will eventually be made one short.

    `messages` may already carry assistant turns: the validation agent's loop
    accumulates the conversation and calls its wrapper once per turn. That
    works because this function passes the list through, so multi-turn needs no
    support of its own here.
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
    """Light model used for classification and Need sentences."""
    return await _complete(
        settings.llm_provider, settings.light_model, response_model, messages, **kwargs
    )


async def complete_heavy(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """Heavy model, used by LLM clustering — see Settings.heavy_provider."""
    return await _complete(
        _heavy_provider(), settings.heavy_model, response_model, messages, **kwargs
    )


async def complete_synthesis(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """plo_synthesis's own endpoint — see Settings.synthesis_provider.

    Split out of complete_heavy rather than left sharing it: clustering and
    synthesis want opposite things from a model, and one wrapper meant neither
    could be moved without dragging the other along. Both the draft call and the
    SMART repair call go through here, so a repair is never answered by a
    different model than wrote the draft it is repairing.
    """
    return await _complete(
        _synthesis_provider(), settings.synthesis_model, response_model, messages, **kwargs
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


async def complete_validation(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """The SMART validation agent's own endpoint — see Settings.validation_provider.

    The only slot that runs a multi-turn loop: the caller accumulates the
    message list and calls this once per turn. Nothing here holds state — the
    list of messages is the whole conversation, and `_complete` already accepts
    an assistant turn in it, so no multi-turn machinery belongs in this module.

    Not complete_heavy, though it defaults to the same provider and model
    family: heavy is LLM clustering and nothing else, and a slot sharing that
    knob could not be moved without moving clustering.

    Not complete_synthesis either, and that is the load-bearing part. This model
    decides *whether* a statement needs repair; the repair itself goes back
    through complete_synthesis, so a repair is still never answered by a
    different model than wrote the draft.
    """
    return await _complete(
        _validation_provider(), settings.validation_model, response_model, messages, **kwargs
    )


async def warmup_models() -> None:
    """Push every locally-served model into Ollama VRAM at startup.

    Hosted providers are skipped — there is no local VRAM to warm, and the
    warm-up call would spend a real request (and, on a paid provider, real money)
    on a prompt whose answer is thrown away. Every slot is considered, since
    only some of them may be the local one.
    """
    local = {model for _, provider, model in _slots() if provider not in _HOSTED_PROVIDERS}
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
