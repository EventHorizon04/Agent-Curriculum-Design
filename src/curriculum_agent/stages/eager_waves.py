"""Run a first batch of parallel calls and start the rest as soon as it cannot decide.

Both voters (SMART judge runs, PLO review runs) run a first batch and the
remaining runs only when the first batch leaves the vote open. Waiting for the
whole first batch before starting the rest makes the second wave queue behind
the slowest first-batch run even when an earlier completion already proves the
batch cannot decide. This helper starts the rest the moment that is provable.

The set of runs started is exactly what the wait-for-everything version starts
for the same outcomes: the predicate is only ever asked about completions, and
once every first-batch run is done it answers the same question as the old
"is the batch decided" check. Token cost is therefore unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


async def run_eager_waves(
    start: Callable[[int], Awaitable[T]],
    *,
    first: int,
    requested: int,
    can_still_decide: Callable[[Sequence[T], int], bool],
) -> list[T]:
    """Results of every started run, in launch order.

    `start(i)` runs the i-th call (0-based, launch order). `can_still_decide`
    receives the completed first-batch results (in launch order) and the number
    of first-batch runs still pending; it must be True whenever the pending runs
    could still make the first batch decisive. When it is False the remaining
    `requested - first` runs start at once. With nothing pending it answers
    "is the first batch decisive", so a decisive batch never starts the rest.

    Exceptions propagate as `asyncio.gather` did; every started task is
    cancelled and awaited on error or cancellation, so none is left orphaned.
    """
    tasks: list[asyncio.Task[T]] = [asyncio.ensure_future(start(i)) for i in range(first)]
    rest_started = requested <= first
    live: set[asyncio.Task[T]] = set(tasks)
    try:
        while live:
            done, live = await asyncio.wait(live, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()  # surface an exception like gather would
            if rest_started:
                continue
            finished = [t.result() for t in tasks[:first] if t.done() and not t.cancelled()]
            if not can_still_decide(finished, first - len(finished)):
                rest_started = True
                for i in range(first, requested):
                    task = asyncio.ensure_future(start(i))
                    tasks.append(task)
                    live.add(task)
        return [t.result() for t in tasks]
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
