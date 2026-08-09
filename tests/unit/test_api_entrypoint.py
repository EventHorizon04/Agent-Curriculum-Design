# tests/unit/test_api_entrypoint.py
from __future__ import annotations

import asyncio
import runpy
import sys
from typing import Any

import pytest
import uvicorn
from uvicorn.importer import import_from_string

from curriculum_agent.api.main import app, lifespan


@pytest.fixture(autouse=True)
def _restore_event_loop_policy():
    """Executing the entrypoint mutates global asyncio state — put it back."""
    original = asyncio.get_event_loop_policy()
    yield
    asyncio.set_event_loop_policy(original)


def _run_entrypoint(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake_run(target: str, **kwargs: Any) -> None:
        seen["target"] = target
        seen["kwargs"] = kwargs
        seen["policy"] = type(asyncio.get_event_loop_policy()).__name__

    monkeypatch.setattr(uvicorn, "run", fake_run)
    runpy.run_module("curriculum_agent.api", run_name="__main__")
    return seen


def test_entrypoint_serves_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _run_entrypoint(monkeypatch)
    assert seen["target"] == "curriculum_agent.api.main:app"


@pytest.mark.skipif(sys.platform != "win32", reason="the loop choice only bites on Windows")
def test_entrypoint_hands_uvicorn_a_loop_psycopg_can_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting the event loop policy is not enough — uvicorn never reads it.

    `Server.run()` passes `config.get_loop_factory()` straight to asyncio.Runner,
    and on Windows that factory is ProactorEventLoop unless `use_subprocess`
    (reload or workers > 1) is on. So the entrypoint has to name the factory.
    Resolve it the way uvicorn will and check the loop it actually builds, rather
    than asserting on the string.
    """
    seen = _run_entrypoint(monkeypatch)

    factory = import_from_string(seen["kwargs"]["loop"])
    loop = factory()
    try:
        assert not isinstance(loop, asyncio.ProactorEventLoop)
    finally:
        loop.close()


@pytest.mark.skipif(sys.platform != "win32", reason="ProactorEventLoop is Windows-only")
def test_lifespan_says_which_loop_it_needs_instead_of_failing_inside_psycopg() -> None:
    """On a Proactor loop the old code got as far as psycopg and died with a
    40-line traceback ending in InterfaceError. Fail at the door instead, and
    name the fix — nothing here should reach the database."""

    async def _enter() -> None:
        async with lifespan(app):
            pass

    loop = asyncio.ProactorEventLoop()
    try:
        with pytest.raises(RuntimeError, match="SelectorEventLoop"):
            loop.run_until_complete(_enter())
    finally:
        loop.close()
