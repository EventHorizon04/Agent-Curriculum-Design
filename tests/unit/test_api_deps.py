# tests/unit/test_api_deps.py
from __future__ import annotations

from curriculum_agent.api import deps
from curriculum_agent.config import Settings


def test_deps_exposes_no_rate_limiting_machinery() -> None:
    """The rate limiter guarded POST /programs/suggest-isced and
    POST /programs/extract-metadata, both removed with the intake trim. It has
    had no caller since, and a limiter no route consumes reads as protection
    that isn't there. Recover it from git history when an LLM-backed endpoint
    comes back — see docs/superpowers/plans/2026-07-17-toctou-ratelimit.md.
    """
    for name in ("RateLimiter", "llm_rate_limiter", "enforce_llm_rate_limit"):
        assert not hasattr(deps, name), f"{name} should have been deleted"


def test_settings_drops_the_rate_limit_knob() -> None:
    assert "llm_rate_limit_per_minute" not in Settings.model_fields
