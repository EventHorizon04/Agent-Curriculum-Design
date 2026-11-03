"""Bounded fan-out, shared by the stages that need one.

`skill_extraction` deliberately does **not** use this. Its semaphore
(`stages/skill_extraction.py`) is held around only the provider call, not the
whole task, so a cache hit never waits for a slot it does not need. A helper
that brackets the entire task would silently put every cache hit behind four
network calls, which is the opposite of what that stage was tuned for. Extract
for the callers that want the simple shape; refuse the tempting unification.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


async def gather_bounded(
    limit: int,
    factories: Sequence[Callable[[], Awaitable[T]]],
    *,
    cancel_on_error: bool = False,
) -> list[T]:
    """`asyncio.gather` with at most `limit` awaitables running at once.

    Input order is preserved, exactly as `gather`'s is. Callers number their
    results from the input list, never from completion order — `plo_synthesis`
    depends on that, because PLO1 means "the capability the market asked for
    most" and a designer cites these ids.

    Takes factories rather than coroutines so nothing starts before it has a
    slot. A list of pre-created coroutines would all be constructed up front,
    which is harmless today and stops being harmless the moment a caller does
    work in the coroutine's first statement.

    A failure propagates as `gather` propagates it, but `gather` leaves the other
    awaitables running, still spending tokens for a result nobody will read.
    `cancel_on_error` cancels them (and waits for the cancellation) before the
    same exception is raised.
    """
    if not factories:
        return []
    sem = asyncio.Semaphore(max(1, limit))

    async def _run(factory: Callable[[], Awaitable[T]]) -> T:
        async with sem:
            return await factory()

    if not cancel_on_error:
        return list(await asyncio.gather(*(_run(f) for f in factories)))
    tasks = [asyncio.ensure_future(_run(f)) for f in factories]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
