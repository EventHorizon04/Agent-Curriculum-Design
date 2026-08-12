from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from curriculum_agent.api.static import mount_frontend


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<html>app shell</html>", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log(1)", encoding="utf-8")
    return tmp_path


def _app(dist: Path) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/programs/{program_id}")
    async def program(program_id: str) -> dict[str, str]:
        return {"program_id": program_id}

    mount_frontend(app, dist)
    return app


def test_root_serves_the_app_shell(dist: Path) -> None:
    resp = TestClient(_app(dist)).get("/")
    assert resp.status_code == 200
    assert "app shell" in resp.text


def test_real_asset_is_served_verbatim(dist: Path) -> None:
    resp = TestClient(_app(dist)).get("/assets/app.js")
    assert resp.status_code == 200
    assert resp.text == "console.log(1)"


def test_client_route_falls_back_to_the_app_shell(dist: Path) -> None:
    # BrowserRouter path with no file behind it: a reload must not 404.
    resp = TestClient(_app(dist)).get("/plo-report")
    assert resp.status_code == 200
    assert "app shell" in resp.text


def test_existing_routes_still_win_over_the_mount(dist: Path) -> None:
    client = TestClient(_app(dist))
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/programs/cs-1").json() == {"program_id": "cs-1"}


def test_unknown_api_path_stays_a_404_not_the_app_shell(dist: Path) -> None:
    # Serving index.html here would disguise a backend 404 as a blank page.
    resp = TestClient(_app(dist)).get("/programs/cs-1/nope")
    assert resp.status_code == 404
    assert "app shell" not in resp.text


def test_missing_dist_fails_at_startup_not_per_request(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="npm run build"):
        mount_frontend(FastAPI(), tmp_path / "does-not-exist")


def test_mount_on_real_app_routes_does_not_shadow_them(dist: Path) -> None:
    """C2 regression: Mount("/") disables Starlette's redirect_slashes, so a
    collection route the client calls without its trailing slash 404s under
    the mount instead of 307-redirecting the way it does without it. This
    test builds a *fresh* FastAPI app carrying the same Route objects as the
    real `curriculum_agent.api.main.app` singleton, mounts the bundle on top,
    and checks real routing behaviour survives it.

    Deliberately does not mount onto (or otherwise mutate) the shared `app`
    singleton itself — other test modules hold `TestClient(app)` against it,
    and a permanent mount there would change what every one of those tests
    exercises.
    """
    from curriculum_agent.api.main import app as real_app

    shadow = FastAPI()
    for route in real_app.routes:
        shadow.router.routes.append(route)
    mount_frontend(shadow, dist)
    client = TestClient(shadow)

    # A real collection route (GET /programs/) still serves JSON, with its
    # repository mocked so this stays a routing test, not a DB test.
    with patch("curriculum_agent.api.routes.programs.ProgramRepository") as repo_cls:
        repo_cls.return_value.list_all = AsyncMock(return_value=[])
        resp = client.get("/programs/")
    assert resp.status_code == 200
    assert resp.json() == []

    # /health still resolves to the API handler, not the SPA fallback.
    assert client.get("/health").json() == {"status": "ok"}

    # A client-side deep link with no file behind it still gets the app shell.
    deep_link = client.get("/plo-report")
    assert deep_link.status_code == 200
    assert "app shell" in deep_link.text

    # The flip side of the fix: Starlette's redirect_slashes never fires once
    # the mount is in place, so a call that omits the trailing slash 404s
    # rather than being redirected — this is exactly why the frontend call
    # sites have to match the route paths exactly (see api client fixes).
    no_slash = client.get("/programs", follow_redirects=False)
    assert no_slash.status_code == 404
