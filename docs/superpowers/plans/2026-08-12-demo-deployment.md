# Demo Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the React bundle from FastAPI on a single loopback origin so a small invited group can drive the whole pipeline through a Cloudflare Tunnel, with service credentials moved out of git.

**Architecture:** One FastAPI process answers both `/programs/*` and `/*`; the static mount is registered after every router and falls back to `index.html` for client-side routes, but never for API prefixes. Everything else — CORS, the API base URL, the SSE headers — follows from that single origin. Postgres and MinIO bind to loopback only and read their passwords from `.env`.

**Tech Stack:** Python 3.11+, FastAPI, Starlette `StaticFiles`, pydantic-settings, pytest (`asyncio_mode = "auto"`), React 19 + Vite + react-router-dom 7, Docker Compose, PowerShell 5.1, `uv`.

**Spec:** `docs/superpowers/specs/2026-08-12-demo-deployment-design.md`. Read it before Task 1.

## Global Constraints

- Type hints on every signature; `from __future__ import annotations` at the top of every Python module.
- `uv run ruff format src/ tests/`, `uv run ruff check src/ tests/`, and `uv run mypy src/` clean before each commit. Line limit 100 characters.
- `cd frontend && npm run lint && npm run build` clean before the frontend commit. One pre-existing warning at `frontend/src/pages/Pipeline.tsx:221` is not yours.
- Tests use `asyncio_mode = "auto"`; never add `@pytest.mark.asyncio`.
- `loguru` for logging, never stdlib `logging`.
- Thai for user-facing strings; code, comments, variable names, and log messages in English.
- Repository pattern for data access; no SQL in route or stage code.
- Do not use `git add -A` or `git commit -a`; stage the specific paths you edit.
- **No test may open a network connection, start a tunnel, or call an LLM.** Everything in this plan is testable offline.
- **Do not change pipeline behaviour.** `stages/`, `prompts/`, `models.py`, `graph.py`, and `exporters/` are not touched by any task here. If a task seems to require editing them, stop and report.
- **Do not modify `scripts/start-dev.ps1`.** The demo gets its own script; the dev script keeps working as it does today.
- The working tree already contains uncommitted changes to `src/curriculum_agent/prompts/cluster_skills.py` and `tests/unit/test_cluster_skills_prompt.py` from unrelated work. Never stage them.

---

## File Structure

**Created**
- `src/curriculum_agent/api/static.py` — the SPA static mount and its fallback rule, isolated so tests can mount it on a throwaway app instead of the module-level singleton
- `tests/unit/test_api_static.py` — mount behaviour
- `scripts/start-demo.ps1` — demo startup
- `docs/demo-runbook.md` — tunnel, Access policy, backup, teardown

**Modified**
- `src/curriculum_agent/config.py` — three settings
- `src/curriculum_agent/api/main.py` — CORS from settings, static mount after routers
- `src/curriculum_agent/api/routes/evidence.py:59` — SSE headers
- `frontend/src/api/client.ts:4` — relative base URL
- `docker-compose.yml` — env-sourced credentials, loopback binds, pgAdmin profile
- `.env.example` — new keys
- `tests/unit/test_config.py` — defaults for the new settings
- `tests/unit/test_evidence_routes.py` — SSE headers

**Why `static.py` is its own file:** `tests/unit/test_api_programs.py:13` builds `TestClient(app)` against the imported singleton. A mount decided at import time cannot be exercised both ways in one test session. A `mount_frontend(app, dist)` function can be called on a fresh `FastAPI()` inside a test with a `tmp_path` bundle, which keeps the existing tests untouched.

---

## Task 1: Configuration settings

**Files:**
- Modify: `src/curriculum_agent/config.py:17-53`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: nothing
- Produces: `settings.serve_frontend: bool`, `settings.frontend_dist: Path`, `settings.cors_origins: list[str]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_config.py`:

```python
def test_frontend_serving_is_off_by_default():
    s = Settings(_env_file=None)
    assert s.serve_frontend is False


def test_frontend_dist_defaults_to_the_vite_output_dir():
    s = Settings(_env_file=None)
    assert s.frontend_dist == Path("frontend/dist")


def test_cors_origins_default_to_the_vite_dev_server():
    # Dev must keep working unchanged: this is the literal the middleware
    # used to carry hardcoded in main.py.
    s = Settings(_env_file=None)
    assert s.cors_origins == ["http://localhost:5173"]


def test_cors_origins_can_be_emptied_for_same_origin_serving():
    s = Settings(_env_file=None, cors_origins=[])
    assert s.cors_origins == []
```

Add `from pathlib import Path` to the imports at the top of the file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'serve_frontend'`

- [ ] **Step 3: Add the settings**

In `src/curriculum_agent/config.py`, add `from pathlib import Path` to the imports, then add these fields to `Settings` after `llm_max_concurrency`:

```python
    # Serve the built React bundle from this process, making the API and the UI
    # one origin. False in dev, where Vite serves the UI on 5173 and proxies here.
    serve_frontend: bool = False
    frontend_dist: Path = Path("frontend/dist")
    # Was hardcoded in main.py. Same-origin serving needs no entry at all, so the
    # demo sets this empty; the default keeps the Vite dev server working.
    cors_origins: list[str] = ["http://localhost:5173"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Verify nothing else regressed**

Run: `uv run pytest tests/unit -q` then `uv run ruff check src/ tests/` and `uv run mypy src/`
Expected: all pass, no mypy errors

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/config.py tests/unit/test_config.py
git commit -m "feat(config): add frontend-serving and CORS settings"
```

---

## Task 2: SPA static mount

**Files:**
- Create: `src/curriculum_agent/api/static.py`
- Test: `tests/unit/test_api_static.py`

**Interfaces:**
- Consumes: nothing from Task 1 (the flag is read in Task 3, not here)
- Produces: `mount_frontend(app: FastAPI, dist: Path) -> None` and `API_PREFIXES: frozenset[str]`

**Behaviour this must get right:** mounting `StaticFiles` at `/` makes it the handler for every path no router claimed. A client-side route like `/plo-report` has no file on disk and must resolve to `index.html`. A mistyped API path like `/programs/abc/nope` must stay a JSON 404 — returning HTML there would turn a backend bug into a silently blank screen.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_api_static.py`:

```python
from __future__ import annotations

from pathlib import Path

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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_api_static.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curriculum_agent.api.static'`

- [ ] **Step 3: Write the implementation**

Create `src/curriculum_agent/api/static.py`:

```python
"""Serve the built React bundle from the API process, on one origin.

Mounting at "/" makes StaticFiles the handler for every path the routers did
not claim, which is what a BrowserRouter app needs: `/plo-report` has no file
behind it and must still return the app shell so a reload works. The exception
is anything under an API prefix — a mistyped `/programs/...` path has to stay a
JSON 404, because answering it with HTML turns a backend error into a blank
screen with a 200 next to it in the network tab.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

# First path segments owned by the API. Kept here rather than derived from
# app.routes so the rule is readable and a new router cannot silently start
# swallowing a client route.
API_PREFIXES: frozenset[str] = frozenset(
    {"programs", "health", "docs", "redoc", "openapi.json"}
)


class _SPAStaticFiles(StaticFiles):
    """StaticFiles that answers unknown non-API paths with index.html."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            if path.split("/", 1)[0] in API_PREFIXES:
                raise
            return await super().get_response("index.html", scope)


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """Mount `dist` at "/". Call after every include_router.

    Raises RuntimeError when the bundle is absent: a missing build is a
    deployment mistake worth failing on at startup, not a 404 per request that
    looks like a routing bug.
    """
    index = dist / "index.html"
    if not index.is_file():
        raise RuntimeError(
            f"Frontend bundle not found at {dist}. Run `npm run build` in frontend/, "
            "or set SERVE_FRONTEND=false."
        )
    static: Any = _SPAStaticFiles(directory=dist, html=True)
    app.mount("/", static, name="frontend")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_api_static.py -v`
Expected: PASS — all 6 tests

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff format src/ tests/`, `uv run ruff check src/ tests/`, `uv run mypy src/`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/api/static.py tests/unit/test_api_static.py
git commit -m "feat(api): serve the SPA bundle with an API-aware fallback"
```

---

## Task 3: Wire the mount and CORS into the app

**Files:**
- Modify: `src/curriculum_agent/api/main.py:74-91`
- Test: `tests/unit/test_api_main_wiring.py` (create)

**Interfaces:**
- Consumes: `settings.cors_origins`, `settings.serve_frontend`, `settings.frontend_dist` (Task 1); `mount_frontend` (Task 2)
- Produces: nothing new — this is the wiring task

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_api_main_wiring.py`:

```python
from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from curriculum_agent.api.main import app
from curriculum_agent.config import settings


def test_cors_origins_come_from_settings_not_a_literal() -> None:
    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1
    assert cors[0].kwargs["allow_origins"] == settings.cors_origins


def test_no_static_mount_when_serving_is_off() -> None:
    # serve_frontend defaults to False, so importing the app must not mount
    # anything — otherwise every existing TestClient(app) test changes meaning.
    assert settings.serve_frontend is False
    assert not [r for r in app.routes if getattr(r, "name", None) == "frontend"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_api_main_wiring.py -v`
Expected: FAIL on the first test — `allow_origins` is the hardcoded `["http://localhost:5173"]` list object, not `settings.cors_origins`

Note: the assertion compares by value, so it may pass by coincidence if the default matches. Confirm the failure is real by reading `main.py:76`; if the test passes before the change, temporarily set `cors_origins=[]` in the test via `monkeypatch.setattr(settings, "cors_origins", [])` and re-import to see it fail. Do not keep that temporary edit.

- [ ] **Step 3: Change the wiring**

In `src/curriculum_agent/api/main.py`, add to the imports:

```python
from curriculum_agent.api.static import mount_frontend
```

Replace the `allow_origins` line (currently `main.py:76`):

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Then, **after** the `@app.get("/health")` function — the last thing in the file — add:

```python
# Registered last on purpose: the mount claims "/" and everything under it, so
# every router must already be in place or the API disappears behind the bundle.
if settings.serve_frontend:
    mount_frontend(app, settings.frontend_dist)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_api_main_wiring.py -v`
Expected: PASS

- [ ] **Step 5: Verify the whole suite is unaffected**

Run: `uv run pytest tests/unit tests/integration -q`
Expected: all pass — the existing `TestClient(app)` tests must be unchanged because `serve_frontend` is False by default

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check src/ tests/` and `uv run mypy src/`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add src/curriculum_agent/api/main.py tests/unit/test_api_main_wiring.py
git commit -m "feat(api): read CORS from settings and mount the bundle behind a flag"
```

---

## Task 4: SSE headers for the tunnel

**Files:**
- Modify: `src/curriculum_agent/api/routes/evidence.py:59`
- Test: `tests/unit/test_evidence_routes.py`

**Interfaces:**
- Consumes: nothing
- Produces: nothing — a response-header change

**Why:** an intermediary that buffers `text/event-stream` delivers every progress event at once when the stream closes. The UI then looks frozen for the whole classification run and jumps to done. `Cache-Control: no-cache` and `X-Accel-Buffering: no` are the two headers proxies honour.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_evidence_routes.py`:

```python
async def test_classify_stream_sets_anti_buffering_headers() -> None:
    """Calling the route builds the StreamingResponse without touching the DB —
    the generator body does not run until something iterates it."""
    from curriculum_agent.api.routes.evidence import classify_evidence_stream

    resp = await classify_evidence_stream("cs-1")

    assert resp.media_type == "text/event-stream"
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_evidence_routes.py -k anti_buffering -v`
Expected: FAIL — `KeyError: 'cache-control'`

- [ ] **Step 3: Add the headers**

In `src/curriculum_agent/api/routes/evidence.py`, replace the return at line 59:

```python
    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        # Without these, a proxy in front of this process is free to buffer the
        # whole stream and deliver it on close — the per-item progress the UI
        # renders would arrive as one burst at the end.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_evidence_routes.py -v`
Expected: PASS

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/ tests/` and `uv run mypy src/`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/api/routes/evidence.py tests/unit/test_evidence_routes.py
git commit -m "fix(api): keep the classify SSE stream unbuffered through a proxy"
```

---

## Task 5: Relative API base URL

**Files:**
- Modify: `frontend/src/api/client.ts:4`

**Interfaces:**
- Consumes: nothing
- Produces: an axios instance whose requests are same-origin

**Why this is safe in dev:** `frontend/vite.config.ts` already proxies `/programs` and `/health` to `http://localhost:8000`, which is every prefix the client calls. With a relative base URL, dev requests go to 5173 and get proxied; demo requests go to the tunnel hostname and are served by the same process.

- [ ] **Step 1: Make the change**

`frontend/src/api/client.ts` in full:

```typescript
import axios from 'axios'

// Relative on purpose: the API is served from whatever origin served this page —
// the Vite dev server (which proxies /programs and /health to :8000) in dev, and
// the tunnel hostname in a demo. A hardcoded localhost breaks the second case.
const api = axios.create({
  baseURL: '',
})

export default api
```

- [ ] **Step 2: Verify lint and build**

Run: `cd frontend && npm run lint && npm run build`
Expected: clean, except the pre-existing `Pipeline.tsx:221` warning

- [ ] **Step 3: Verify dev still works end to end**

Start the API (`uv run python -m curriculum_agent.api` with the Docker services up), then `cd frontend && npm run dev`. Open `http://localhost:5173`, confirm the programs list loads and the network tab shows requests going to `localhost:5173/programs/...` with a 200.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(ui): call the API on the origin that served the page"
```

---

## Task 6: Service credentials and loopback binds

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

**Interfaces:**
- Consumes: nothing
- Produces: `POSTGRES_PASSWORD` and `MINIO_SECRET_KEY` as required environment variables for the stack

**Read before starting:** changing `POSTGRES_PASSWORD` does **not** rotate the password of an already-initialised database. Postgres reads it only when it creates the data directory. The existing `postgres-data` volume holds real program data and must not be deleted. Step 4 rotates the live password with `ALTER USER`; the compose variable then matches for any future fresh volume.

- [ ] **Step 1: Rewrite the compose file**

`docker-compose.yml` in full:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: ca-postgres
    environment:
      POSTGRES_USER: curriculum
      # ":?" stops the stack when the value is missing, instead of starting it on
      # a default password that is committed to git.
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}
      POSTGRES_DB: curriculum_agent
    ports:
      # Loopback only: the API reaches these over localhost, and nothing else
      # should. The tunnel exposes port 8000 and nothing more.
      - "127.0.0.1:5432:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
    restart: unless-stopped

  minio:
    image: minio/minio:latest
    container_name: ca-minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY:?set MINIO_ACCESS_KEY in .env}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY:?set MINIO_SECRET_KEY in .env}
    ports:
      - "127.0.0.1:9000:9000"
      - "127.0.0.1:9001:9001"
    volumes:
      - minio-data:/data
    restart: unless-stopped

  pgadmin:
    image: dpage/pgadmin4:latest
    container_name: ca-pgadmin
    # Behind a profile: it defaulted to admin@local.com / admin and does not
    # belong in a stack that is reachable from outside the machine.
    profiles: ["debug"]
    environment:
      PGADMIN_DEFAULT_EMAIL: ${PGADMIN_EMAIL:-admin@local.com}
      PGADMIN_DEFAULT_PASSWORD: ${PGADMIN_PASSWORD:?set PGADMIN_PASSWORD in .env}
    ports:
      - "127.0.0.1:5050:80"
    depends_on:
      - postgres
    restart: unless-stopped

volumes:
  postgres-data:
  minio-data:
```

- [ ] **Step 2: Update `.env.example`**

`.env.example` in full:

```
# .env holds secrets only. Everything else (provider, models, base URLs)
# has a working default in curriculum_agent/config.py — override here only
# if your local setup differs.

# --- Docker service credentials (required: docker compose refuses to start
# --- without them) ---
POSTGRES_PASSWORD=change-me
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=change-me
# Only needed when running `docker compose --profile debug up`
# PGADMIN_PASSWORD=change-me

# Must carry the same password as POSTGRES_PASSWORD above.
# POSTGRES_DSN=postgresql+asyncpg://curriculum:change-me@localhost:5432/curriculum_agent

# --- LLM ---
# OPENROUTER_API_KEY=your-key-here   # required when LLM_PROVIDER=openrouter

# --- Demo serving (see docs/demo-runbook.md) ---
# SERVE_FRONTEND=true
# CORS_ORIGINS=[]
# API_KEY=change-me-in-production
```

- [ ] **Step 3: Set the values in your own `.env`**

Add `POSTGRES_PASSWORD`, `MINIO_ACCESS_KEY`, and `MINIO_SECRET_KEY` to the local `.env`. For the first run keep `POSTGRES_PASSWORD` equal to the password already in `POSTGRES_DSN` (`curriculum_dev` unless it was changed) so the running database still connects. `.env` is gitignored — never stage it.

- [ ] **Step 4: Rotate the live Postgres password**

Only after Step 3 works. Pick a new password, then:

```bash
docker exec ca-postgres psql -U curriculum -d curriculum_agent \
  -c "ALTER USER curriculum WITH PASSWORD 'NEW_PASSWORD_HERE';"
```

Then update **both** `POSTGRES_PASSWORD` and the password inside `POSTGRES_DSN` in `.env` to the new value, and restart the API. Do not delete the `postgres-data` volume — it holds real program data.

- [ ] **Step 5: Verify the stack**

```bash
docker compose down
docker compose up -d
docker compose ps
```

Expected: `ca-postgres` and `ca-minio` running, `ca-pgadmin` absent. Confirm the binds are loopback:

```bash
docker compose port postgres 5432
```

Expected: `127.0.0.1:5432`

Then confirm fail-fast works — with `POSTGRES_PASSWORD` commented out in `.env`, `docker compose up -d` must refuse to start with a message naming the variable. Restore the value afterwards.

- [ ] **Step 6: Verify the app still connects**

Run: `uv run alembic upgrade head` then `uv run pytest tests/unit -q`
Expected: migrations report no pending revisions, tests pass

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "fix(compose): source service credentials from .env and bind to loopback"
```

---

## Task 7: Demo startup script

**Files:**
- Create: `scripts/start-demo.ps1`

**Interfaces:**
- Consumes: `SERVE_FRONTEND` and `CORS_ORIGINS` from Task 1, the compose changes from Task 6
- Produces: a running API on `127.0.0.1:8000` with the bundle built and served

**Why not reuse `start-dev.ps1`:** it sets `API_HOST = "0.0.0.0"` (line 74), which publishes the API on every interface and lets anyone on the network bypass the tunnel entirely; and it hard-fails when Ollama is not running (lines 34-42), which is irrelevant when the provider is OpenRouter. Leave that file alone.

- [ ] **Step 1: Write the script**

Create `scripts/start-demo.ps1`:

```powershell
#Requires -Version 5.1
<#
.SYNOPSIS
  Start the demo environment: DB services + built UI served by the API on loopback.
.DESCRIPTION
  Differs from start-dev.ps1 in three ways that matter: the API binds to
  127.0.0.1 (the tunnel is the only way in), reload is off, and Ollama is not
  required because the demo runs on OpenRouter. Prints the cloudflared command
  to run next. See docs/demo-runbook.md.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\.."

function Write-Step { param([string]$msg) Write-Host ">> $msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$msg) Write-Host "   OK: $msg" -ForegroundColor Green }
function Write-Fail { param([string]$msg) Write-Host "   FAIL: $msg" -ForegroundColor Red; exit 1 }

# --- 1. Check the OpenRouter key is configured ---
Write-Step "Checking LLM configuration..."
if (-not (Test-Path ".env")) { Write-Fail ".env not found. Copy .env.example and fill it in." }
$envText = Get-Content ".env" -Raw
if ($envText -notmatch '(?m)^\s*OPENROUTER_API_KEY\s*=\s*\S') {
    Write-Fail "OPENROUTER_API_KEY is not set in .env. The demo runs on OpenRouter."
}
Write-Ok "OpenRouter key present"

# --- 2. Start Docker DB services ---
Write-Step "Starting DB services (postgres, minio)..."
docker compose up -d --remove-orphans
if ($LASTEXITCODE -ne 0) { Write-Fail "docker compose up failed" }
Write-Ok "Containers started"

# --- 3. Wait for postgres ready ---
Write-Step "Waiting for postgres..."
$timeout = 30
$elapsed = 0
while ($elapsed -lt $timeout) {
    $null = docker exec ca-postgres pg_isready -U curriculum -d curriculum_agent 2>&1
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 1
    $elapsed++
}
if ($elapsed -ge $timeout) { Write-Fail "Postgres not ready after ${timeout}s" }
Write-Ok "Postgres ready"

# --- 4. Run migrations ---
Write-Step "Running Alembic migrations..."
uv run alembic upgrade head
if ($LASTEXITCODE -ne 0) { Write-Fail "Migration failed" }
Write-Ok "Migrations applied"

# --- 5. Build the frontend ---
# Built here rather than assumed: the API serves whatever is in frontend/dist,
# and a stale bundle is invisible until someone reports missing UI.
Write-Step "Building the React bundle..."
Push-Location frontend
npm run build
$buildFailed = $LASTEXITCODE -ne 0
Pop-Location
if ($buildFailed) { Write-Fail "npm run build failed" }
Write-Ok "Bundle built to frontend/dist"

# --- 6. Start the API on loopback ---
# 127.0.0.1, not 0.0.0.0: the Cloudflare Tunnel is the only intended way in, and
# an interface-wide bind lets anyone on the LAN skip Cloudflare Access entirely.
# Launched through the package entrypoint, not the uvicorn CLI — see
# src/curriculum_agent/api/__main__.py.
Write-Step "Starting FastAPI on 127.0.0.1:8000..."
$env:API_HOST = "127.0.0.1"
$env:API_PORT = "8000"
$env:API_RELOAD = "false"
$env:SERVE_FRONTEND = "true"
$env:CORS_ORIGINS = "[]"
$proc = Start-Process -FilePath "uv" `
    -ArgumentList "run", "python", "-m", "curriculum_agent.api" `
    -PassThru -NoNewWindow
$proc.Id | Out-File -FilePath ".uvicorn.pid" -Encoding utf8
Write-Ok "API started (PID $($proc.Id))"

Write-Host ""
Write-Host "=== Demo environment ready ===" -ForegroundColor Yellow
Write-Host "  Local:  http://127.0.0.1:8000"
Write-Host ""
Write-Host "  Next, in another terminal:" -ForegroundColor Yellow
Write-Host "    cloudflared tunnel --url http://localhost:8000"
Write-Host ""
Write-Host "  Then put the tunnel hostname behind Cloudflare Access."
Write-Host "  See docs/demo-runbook.md."
Write-Host ""
Write-Host "  Stop: .\scripts\stop-dev.ps1"
```

- [ ] **Step 2: Verify the script runs**

Run: `.\scripts\start-demo.ps1`
Expected: every step reports OK, the bundle builds, and the summary prints. `.uvicorn.pid` exists.

- [ ] **Step 3: Verify the bind is loopback**

Run: `netstat -ano | Select-String ":8000"`
Expected: the listening entry shows `127.0.0.1:8000`, **not** `0.0.0.0:8000`. If it shows `0.0.0.0`, stop and fix before going further — that is the one condition the whole security model rests on.

- [ ] **Step 4: Verify the app is served on one origin**

Open `http://127.0.0.1:8000` in a browser. Expected: the UI loads, the programs list renders, and `http://127.0.0.1:8000/health` returns `{"status":"ok"}`. Reload on a client route such as `http://127.0.0.1:8000/plo-report` — it must render, not 404.

- [ ] **Step 5: Verify the fail-fast path**

Temporarily comment out `OPENROUTER_API_KEY` in `.env` and run the script again. Expected: it stops at step 1 with the OpenRouter message and starts nothing. Restore the key.

- [ ] **Step 6: Stop and commit**

```bash
git add scripts/start-demo.ps1
git commit -m "feat(scripts): add a loopback-bound demo startup script"
```

---

## Task 8: Demo runbook

**Files:**
- Create: `docs/demo-runbook.md`

**Interfaces:**
- Consumes: everything from Tasks 1-7
- Produces: the operator procedure — this is the only place the tunnel and Access steps are written down

- [ ] **Step 1: Write the runbook**

Create `docs/demo-runbook.md`:

````markdown
# Demo Runbook

Procedure for exposing the curriculum design agent to a small invited group.
Design rationale: `docs/superpowers/specs/2026-08-12-demo-deployment-design.md`.

## What this setup is and is not

Everyone who gets through Cloudflare Access shares one dataset. There are no user
accounts. Any authorised person can read and delete any program. That is
acceptable for an invited demo and unacceptable for anything wider.

**The API has no authentication of its own.** `API_KEY` stays unset because the
frontend does not send `X-API-Key`; setting it would make every write fail with
401. Cloudflare Access is the only barrier, so three conditions must hold:

1. Port 8000 is never exposed directly — the tunnel is the only way in.
2. `cloudflared` points at `http://localhost:8000`.
3. The Access policy is an explicit email allowlist, not "anyone with the link".

## Before the demo

1. **Back up the database.** Everyone can delete any program.

   ```bash
   docker exec ca-postgres pg_dump -U curriculum curriculum_agent > backup-YYYY-MM-DD.sql
   ```

2. **Confirm `.env` has:** `POSTGRES_PASSWORD`, `MINIO_ACCESS_KEY`,
   `MINIO_SECRET_KEY`, `OPENROUTER_API_KEY`. Leave `API_KEY` unset.

3. **Start the stack:**

   ```powershell
   .\scripts\start-demo.ps1
   ```

4. **Confirm the bind is loopback:**

   ```powershell
   netstat -ano | Select-String ":8000"
   ```

   It must read `127.0.0.1:8000`. If it reads `0.0.0.0:8000`, stop — the machine
   is reachable without Access.

## Tunnel and Access

1. Install `cloudflared` and log in:

   ```bash
   cloudflared tunnel login
   ```

2. Start the tunnel:

   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```

   It prints a `*.trycloudflare.com` hostname. **That hostname is public until
   Access is applied.** Treat the next step as part of starting the tunnel, not
   as something to do later.

3. In the Cloudflare Zero Trust dashboard, add a self-hosted Access application
   for that hostname with a policy of **Allow / Emails / the invited addresses**.

4. Verify from a browser signed in to an address that is *not* on the list. You
   must be stopped. If you reach the app, the policy is wrong — take the tunnel
   down before doing anything else.

## During the demo

Watch for these two, which the setup cannot prevent:

- **Slow progress on stakeholder needs.** The classify stream sends per-item
  events; if progress arrives in one burst at the end, the anti-buffering
  headers are not reaching the client. The run still completes correctly.
- **Someone deleting another person's program.** There is no ownership check.
  Restore from the backup if it happens.

## After the demo

1. Stop the tunnel (Ctrl-C) — this is what actually revokes access.
2. Stop the app:

   ```powershell
   .\scripts\stop-dev.ps1
   ```

3. Remove the Access application if the hostname will not be reused.
4. Keep the backup file until the exported results have been checked.

## Known gaps

Recorded so they are not mistaken for oversights. Closing them is separate work.

- GET routes carry no `require_api_key`, so all data is readable by anyone past Access.
- Any authorised user can delete any program.
- `Dockerfile` still installs CUDA and torch, which this branch does not use. It
  is not on this deployment path; a production deployment needs it rewritten.
````

- [ ] **Step 2: Verify the runbook against reality**

Walk the "Before the demo" section top to bottom on the machine. Every command must run as written. Fix any that do not.

- [ ] **Step 3: Commit**

```bash
git add docs/demo-runbook.md
git commit -m "docs: add the demo deployment runbook"
```

---

## Verification

After every task, from a clean working tree:

```bash
uv run pytest tests/unit tests/integration -q
uv run ruff check src/ tests/
uv run mypy src/
cd frontend && npm run lint && npm run build
```

Expected: all pass; the only frontend warning is the pre-existing one at `Pipeline.tsx:221`.

Manual checks that no test covers, run through the tunnel — not localhost:

- [ ] Create a program end to end and reach the PLO report.
- [ ] Watch `classify-stream` deliver progress incrementally, not as one burst on completion.
- [ ] Reload a deep link (`/plo-report`) and confirm it renders instead of 404.
- [ ] Open the tunnel hostname from a browser whose account is not on the Access allowlist and confirm it is blocked.
