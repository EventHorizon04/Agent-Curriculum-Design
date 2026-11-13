from __future__ import annotations

import functools
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, TypeVar, cast

import instructor
from loguru import logger
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from curriculum_agent.config import SLOTS, SlotSpec, settings
from curriculum_agent.data.repositories import LLMUsageRepository
from curriculum_agent.llm_context import current_scope
from curriculum_agent.models import LLMUsage

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


def _slot_provider(slot: SlotSpec) -> str:
    """The endpoint one slot resolves to, or "" when the slot is switched off.

    One function for every slot, read off `SLOTS`. There were four of these,
    differing only in which field they named — and in one load-bearing detail
    that a reader had to notice was missing from the fourth.

    That detail: Settings has already turned None into llm_provider before
    anything reads a provider field, so there is nothing to fall back to here.
    A `or settings.llm_provider` would not be a harmless belt-and-braces — for
    the disableable slot it turns "" , the documented kill switch, back into a
    live provider, and the switch cannot be thrown at all. That is the bug the
    per-slot version of this function carried, and the reason it is written as
    a plain read rather than an `or`.
    """
    provider = (
        settings.llm_provider
        if slot.provider_field is None
        else getattr(settings, slot.provider_field)
    )
    # A disableable slot may legitimately hold "". Everything else has been
    # resolved to a real provider by Settings, so this normalises only None.
    return provider or ""


def _slot(name: str) -> SlotSpec:
    """The one slot with this name. Raises if the caller invents a slot."""
    for slot in SLOTS:
        if slot.name == name:
            return slot
    raise KeyError(f"no LLM slot named '{name}' — SLOTS declares {[s.name for s in SLOTS]}")


def _resolve(name: str) -> tuple[str, str]:
    """(provider, model) for one slot by name, resolved now."""
    slot = _slot(name)
    return _slot_provider(slot), getattr(settings, slot.model_field)


def _slots() -> tuple[tuple[str, str, str], ...]:
    """Every slot as (label, provider, model), resolved now.

    Derived from `SLOTS` rather than written out: describe_target, warmup_models
    and the config tests all read this, and the two former ones used to
    enumerate the slots by hand — a slot present in only one of them is a model
    nobody warms or a model nobody can see in the startup log.
    """
    return tuple(
        (slot.name, _slot_provider(slot), getattr(settings, slot.model_field)) for slot in SLOTS
    )


def _key_state(provider: str) -> str:
    try:
        return "set" if _api_key(provider) else "empty"
    except ValueError:
        # The provider needs a key and none is configured. Say so here rather than
        # letting the first real call fail with the same message 40 frames deep.
        return "MISSING"


def _describe_slot(label: str, provider: str, model: str) -> str:
    # A slot with no provider is switched off. Say so on its own line rather
    # than dropping it: a missing line reads as a slot that stopped existing,
    # and the startup log is where an operator confirms the switch took.
    if not provider:
        return f"{label}: disabled"
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


@dataclass
class _Attempt:
    """One provider response seen by instructor's hooks."""

    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int | None
    latency_ms: int
    ok: bool = True


# The attempts of the call running in this task. The client is a cached singleton
# shared by every concurrent call, so per-call state cannot live on it; the hooks
# find their call through these variables, which `_complete` sets for its own task.
_attempts: ContextVar[list[_Attempt] | None] = ContextVar("llm_attempts", default=None)
_started: ContextVar[float | None] = ContextVar("llm_attempt_started", default=None)


def _on_kwargs(*_args: Any, **_kwargs: Any) -> None:
    _started.set(time.monotonic())


def _on_response(response: Any) -> None:
    attempts = _attempts.get()
    if attempts is None:
        return
    started = _started.get()
    latency = int((time.monotonic() - started) * 1000) if started is not None else 0
    usage = getattr(response, "usage", None)
    details = getattr(usage, "completion_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", None)
    attempts.append(
        _Attempt(
            prompt_tokens=int(getattr(usage, "prompt_tokens", None) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", None) or 0),
            reasoning_tokens=reasoning if isinstance(reasoning, int) else None,
            latency_ms=latency,
        )
    )


def _on_parse_error(_error: Exception) -> None:
    attempts = _attempts.get()
    if attempts:
        attempts[-1].ok = False


def _on_completion_error(_error: Exception) -> None:
    # A truncated response (IncompleteOutputException) takes this path, not
    # parse:error, and instructor retries it. With no response in this attempt the
    # last entry is an earlier attempt, which already failed, so this is idempotent.
    attempts = _attempts.get()
    if attempts:
        attempts[-1].ok = False


def _ensure_usage_hooks(client: instructor.AsyncInstructor) -> None:
    """Register the recorder's hooks once per client (the client is cached)."""
    if getattr(client, "_usage_hooks_installed", False):
        return
    client.on("completion:kwargs", _on_kwargs)
    client.on("completion:response", _on_response)
    client.on("parse:error", _on_parse_error)
    client.on("completion:error", _on_completion_error)
    client._usage_hooks_installed = True  # type: ignore[attr-defined]


async def _record_usage(attempts: list[_Attempt], *, slot: str, provider: str, model: str) -> None:
    """One row per provider response. Never raises: accounting must not fail a call."""
    scope = current_scope()
    for attempt in attempts:
        try:
            await LLMUsageRepository().add(
                LLMUsage(
                    program_id=scope.program_id,
                    job_id=scope.job_id,
                    session_id=scope.session_id,
                    slot=slot,
                    provider=provider,
                    model=model,
                    prompt_tokens=attempt.prompt_tokens,
                    completion_tokens=attempt.completion_tokens,
                    reasoning_tokens=attempt.reasoning_tokens,
                    latency_ms=attempt.latency_ms,
                    ok=attempt.ok,
                )
            )
        except Exception as exc:  # noqa: BLE001 - best effort by design
            logger.warning(f"llm usage not recorded ({slot}): {exc!r}")


async def _complete(
    provider: str,
    model: str,
    response_model: type[T],
    messages: list[dict[str, Any]],
    *,
    slot: str,
    reasoning_max_tokens: int | None = None,
    **kwargs: Any,
) -> T:
    """One structured completion against one endpoint.

    The public wrappers differ only in which provider and model they name, so
    the call itself lives here — otherwise a change to instructor's contract has
    to be made once per slot and will eventually be made one short.

    `messages` may already carry assistant turns: the validation agent's loop
    accumulates the conversation and calls its wrapper once per turn, so
    multi-turn needs no support of its own here — but it does need the list
    handed over as a copy. instructor's JSON mode appends the response schema to
    the system message *in place* (its `kwargs.copy()` is shallow, so the dict it
    edits is the caller's), and a list reused across turns therefore grew one
    schema per call: the same opening turn measured 5,773, then 7,423, then
    9,073 prompt tokens, and turn eight carried eight copies. A shallow copy of
    each message is enough, because every builder here emits string content.

    `reasoning_max_tokens` bounds a model's hidden reasoning where the endpoint
    has a field for it, which is OpenRouter's `reasoning`. Some models there
    spend one `max_tokens` on both reasoning and answer with nothing between
    them, and the validation model spent all of it thinking and returned no
    content at all — see `smart_agent._MAX_REASONING_TOKENS`. Elsewhere the field
    means nothing and is not sent, so moving a slot off OpenRouter cannot start
    failing its calls over an unknown parameter.

    `slot` names the stage that called, for the usage rows (phase 5). Every
    provider response is recorded, instructor's retries included, and the
    recording never changes what this returns or raises; see `_record_usage`.
    """
    logger.debug(f"LLM call: {model} ({provider})")
    extra_body = _extra_body(provider)
    if reasoning_max_tokens is not None and provider == "openrouter":
        extra_body = {**extra_body, "reasoning": {"max_tokens": reasoning_max_tokens}}
    client = _get_client(provider)
    _ensure_usage_hooks(client)
    attempts: list[_Attempt] = []
    token = _attempts.set(attempts)
    failed = True
    try:
        result = await client.chat.completions.create(
            model=model,
            response_model=response_model,
            # Prompt builders emit OpenAI-shaped role/content dicts; cast to the SDK's
            # message param type instead of restructuring at runtime.
            messages=cast(list[ChatCompletionMessageParam], [dict(m) for m in messages]),
            extra_body=extra_body,
            **kwargs,
        )
        failed = False
        return result
    finally:
        # Intended under cancellation too (a job's time budget): the last attempt is
        # marked failed and its rows are still written while the cancel propagates.
        _attempts.reset(token)
        if failed and attempts and attempts[-1].ok:
            # The last response arrived but the call still raised (a truncation, or
            # the final validation failure): that response produced nothing.
            attempts[-1].ok = False
        await _record_usage(attempts, slot=slot, provider=provider, model=model)


async def complete_need_combination(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """Writes the Thai sentence for each Need, and nothing else.

    The docstring used to say "light model used for classification and Need
    sentences", which was wrong twice over: `light` was this slot's name before
    the rename to the calling stage, and evidence classification stopped calling
    an LLM at all when it became a code lookup from `StakeholderType`. One
    caller, `need_combination`, and the sentence it writes is the only thing
    `plo_synthesis` is later handed.
    """
    return await _complete(
        *_resolve("need_combination"), response_model, messages, slot="need_combination", **kwargs
    )


async def complete_need_dedup(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """The duplicate check before PLO synthesis — see Settings.need_dedup_provider.

    One caller, `stages.need_dedup.find_duplicate_groups`, once per synthesis
    run. It answers with labels, never with Thai a designer reads, and whatever
    it answers is judged again in pure code before anything is folded.
    """
    return await _complete(
        *_resolve("need_dedup"), response_model, messages, slot="need_dedup", **kwargs
    )


async def complete_plo_review(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """The PLO set review before the report — see Settings.plo_review_provider.

    One caller, `stages.plo_review`, once per changed PLO set. Its answer is
    advice for the designer and is judged again in pure code before it is stored.
    """
    return await _complete(
        *_resolve("plo_review"), response_model, messages, slot="plo_review", **kwargs
    )


async def complete_clustering(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """Heavy model, used by LLM clustering — see Settings.clustering_provider."""
    return await _complete(
        *_resolve("clustering"), response_model, messages, slot="clustering", **kwargs
    )


async def complete_plo_synthesis(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """plo_synthesis's own endpoint — see Settings.plo_synthesis_provider.

    Split out of complete_clustering rather than left sharing it: clustering and
    synthesis want opposite things from a model, and one wrapper meant neither
    could be moved without dragging the other along. Both the draft call and the
    SMART repair call go through here, so a repair is never answered by a
    different model than wrote the draft it is repairing.
    """
    return await _complete(
        *_resolve("plo_synthesis"), response_model, messages, slot="plo_synthesis", **kwargs
    )


async def complete_extraction(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """skill_extraction's own endpoint — see Settings.extraction_provider.

    Separate from complete_need_combination/heavy rather than a flag on them: extraction is
    a per-evidence fan-out whose cost and quota profile is nothing like the
    handful of calls the other stages make, and the cache key it writes is keyed
    on this model name. A stage picking the endpoint per call would put that
    decision somewhere the cache cannot see it.
    """
    return await _complete(
        *_resolve("extraction"), response_model, messages, slot="extraction", **kwargs
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

    Not complete_clustering, though it defaults to the same provider and model
    family: heavy is LLM clustering and nothing else, and a slot sharing that
    knob could not be moved without moving clustering.

    Not complete_plo_synthesis either, and that is the load-bearing part. This model
    decides *whether* a statement needs repair; the repair itself goes back
    through complete_plo_synthesis, so a repair is still never answered by a
    different model than wrote the draft.
    """
    provider, model = _resolve("validation")
    if not provider:
        # The loop checks this before it starts and returns a code-only verdict,
        # so reaching here means a caller skipped that guard. Fail with the
        # reason rather than handing "" to _get_client.
        raise RuntimeError(
            "the SMART validation agent is switched off (VALIDATION_PROVIDER is empty)"
        )
    return await _complete(provider, model, response_model, messages, slot="validation", **kwargs)


async def warmup_models() -> None:
    """Push every locally-served model into Ollama VRAM at startup.

    Hosted providers are skipped — there is no local VRAM to warm, and the
    warm-up call would spend a real request (and, on a paid provider, real money)
    on a prompt whose answer is thrown away. Every slot is considered, since
    only some of them may be the local one.
    """
    # `provider` guards the disabled slot: "" is not in _HOSTED_PROVIDERS, so
    # without it a switched-off validation slot would still warm a model.
    local = {
        model for _, provider, model in _slots() if provider and provider not in _HOSTED_PROVIDERS
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
