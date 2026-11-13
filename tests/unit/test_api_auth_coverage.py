"""Every write route requires the API key (designer's decision, 2026-11-11)."""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr

from curriculum_agent.api import deps
from curriculum_agent.api.deps import require_api_key
from curriculum_agent.api.main import app

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# A write route that must stay open goes here with its reason. Empty on purpose.
_OPEN_WRITE_ROUTES: dict[tuple[str, str], str] = {}


def _calls(dependant: object) -> set[object]:
    found: set[object] = set()
    stack = [dependant]
    while stack:
        node = stack.pop()
        call = getattr(node, "call", None)
        if call is not None:
            found.add(call)
        stack.extend(getattr(node, "dependencies", []))
    return found


def test_every_write_route_requires_the_api_key() -> None:
    unguarded: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods & _WRITE_METHODS):
            if (method, route.path) in _OPEN_WRITE_ROUTES:
                continue
            if require_api_key not in _calls(route.dependant):
                unguarded.append(f"{method} {route.path}")
    assert unguarded == []


def test_classify_stream_requires_the_api_key() -> None:
    """The one GET with side effects (it runs the classifier) is guarded too."""
    matches = [
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/programs/{program_id}/evidence/classify-stream"
        and "GET" in route.methods
    ]
    assert len(matches) == 1
    assert require_api_key in _calls(matches[0].dependant)


def test_write_without_key_is_401_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps.settings, "api_key", SecretStr("test-key"))
    client = TestClient(app)

    response = client.post("/programs/p/needs/N1/exclude")

    assert response.status_code == 401


def test_session_start_without_key_is_401_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps.settings, "api_key", SecretStr("test-key"))
    client = TestClient(app)

    assert client.post("/programs/p/sessions/", json={}).status_code == 401
    assert client.post("/programs/p/plos/run").status_code == 401
