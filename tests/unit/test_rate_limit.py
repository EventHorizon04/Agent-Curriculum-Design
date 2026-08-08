# tests/unit/test_rate_limit.py
from __future__ import annotations

import pytest
from fastapi import HTTPException

from curriculum_agent.api.deps import RateLimiter

# The two route-wiring tests that lived here covered POST /programs/suggest-isced
# and POST /programs/extract-metadata, both removed with the intake trim. No
# route depends on enforce_llm_rate_limit today, so the limiter is tested as the
# unit it is; re-add a wiring test alongside the next LLM-backed endpoint.


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# --- RateLimiter unit ---


def test_allows_requests_up_to_limit() -> None:
    limiter = RateLimiter(limit=3, time_func=FakeClock())
    for _ in range(3):
        limiter.check("1.2.3.4")  # must not raise


def test_blocks_over_limit_with_retry_after() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=2, time_func=clock)
    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")
    with pytest.raises(HTTPException) as exc_info:
        limiter.check("1.2.3.4")
    assert exc_info.value.status_code == 429
    assert int(exc_info.value.headers["Retry-After"]) >= 1


def test_window_slides_frees_slot() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=1, window_seconds=60.0, time_func=clock)
    limiter.check("1.2.3.4")
    clock.advance(61.0)
    limiter.check("1.2.3.4")  # must not raise


def test_ips_tracked_independently() -> None:
    limiter = RateLimiter(limit=1, time_func=FakeClock())
    limiter.check("1.2.3.4")
    limiter.check("5.6.7.8")  # must not raise
