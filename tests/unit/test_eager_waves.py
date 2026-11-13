from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from curriculum_agent.stages.eager_waves import run_eager_waves


async def test_results_are_in_launch_order_not_completion_order() -> None:
    async def start(i: int) -> int:
        await asyncio.sleep(0.03 - i * 0.01 if i < 3 else 0)
        return i

    out = await run_eager_waves(start, first=3, requested=5, can_still_decide=lambda d, p: False)
    assert out == [0, 1, 2, 3, 4]


async def test_a_decisive_first_batch_starts_nothing_more() -> None:
    started: list[int] = []

    async def start(i: int) -> int:
        started.append(i)
        return i

    out = await run_eager_waves(start, first=3, requested=5, can_still_decide=lambda d, p: True)
    assert out == [0, 1, 2] and started == [0, 1, 2]


async def test_an_error_cancels_and_awaits_every_started_task() -> None:
    cancelled: list[int] = []

    async def start(i: int) -> int:
        if i == 0:
            raise RuntimeError("boom")
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.append(i)
            raise
        return i

    with pytest.raises(RuntimeError):
        await run_eager_waves(start, first=3, requested=5, can_still_decide=lambda d, p: True)
    assert sorted(cancelled) == [1, 2]


async def test_outer_cancellation_propagates_and_cleans_up() -> None:
    cancelled: list[int] = []

    async def start(i: int) -> int:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.append(i)
            raise
        return i

    def never(d: Sequence[int], p: int) -> bool:
        return True

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await run_eager_waves(start, first=3, requested=5, can_still_decide=never)
    assert sorted(cancelled) == [0, 1, 2]
