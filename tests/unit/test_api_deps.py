# tests/unit/test_api_deps.py
from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

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


async def test_auth_stays_off_when_the_configured_key_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blank API_KEY means "auth off", same as unset.

    This rides on SecretStr defining __len__ (it has no __bool__), so an empty
    one is falsy and the existing guard holds. Pinned because that is a detail of
    pydantic's type, not something the guard states: were it to change, a blank
    setting would switch auth *on* and reject every caller.
    """
    monkeypatch.setattr(deps.settings, "api_key", SecretStr(""))

    assert await deps.require_api_key(None) == "no-auth-configured"


async def test_wrong_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps.settings, "api_key", SecretStr("right-key"))

    with pytest.raises(HTTPException) as exc_info:
        await deps.require_api_key("wrong-key")

    assert exc_info.value.status_code == 401


async def test_correct_key_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps.settings, "api_key", SecretStr("right-key"))

    assert await deps.require_api_key("right-key") == "right-key"


async def test_non_ascii_key_does_not_explode(monkeypatch: pytest.MonkeyPatch) -> None:
    """secrets.compare_digest raises TypeError on non-ASCII str, so the
    comparison has to run over bytes."""
    monkeypatch.setattr(deps.settings, "api_key", SecretStr("กุญแจลับ"))

    assert await deps.require_api_key("กุญแจลับ") == "กุญแจลับ"
    with pytest.raises(HTTPException):
        await deps.require_api_key("ผิด")
