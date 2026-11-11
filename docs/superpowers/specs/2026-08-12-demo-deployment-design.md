# Demo Deployment Design

**Date:** 2026-08-12
**Status:** Approved for planning

## Goal

Let a small invited group — roughly 5–20 reviewers from one faculty — open the
curriculum design agent in a browser and drive the full pipeline, without
installing anything and without the app leaving the developer's own machine.

## Scope Decisions

Three questions were settled before design, and they remove more work than they add:

1. **Shared data, no per-user isolation.** Everyone sees and edits the same
   programs. No user accounts, no `owner` column, no migration, no query rewrite.
2. **Runs on the developer's Windows machine, exposed through Cloudflare Tunnel.**
   No cloud VM, no infrastructure to provision or pay for.
3. **LLM calls go to OpenRouter.** `llm_provider` already defaults to
   `openrouter`; the host GPU stays out of the request path, so several reviewers
   can work at once without queueing behind one model.

**Explicitly out of scope:** multi-tenancy, per-user auth, rate limiting, cost
controls, a production `Dockerfile`, and any change to pipeline behaviour. The
six stages, the HITL checkpoints, the SMART gate, and the KSEC bucketing
invariant are untouched. Deployment must not change what the agent produces.

## Architecture

Single origin. FastAPI serves both the API and the built React bundle, so the
tunnel points at exactly one port and CORS stops being a concern.

```
external user ──HTTPS──> Cloudflare Access (email allowlist)
                              │
                        Cloudflare Tunnel
                              │
                   cloudflared (Windows host)
                              │
                     127.0.0.1:8000  ← FastAPI, one process
                       ├── /programs/*, /health, /docs → API routers
                       └── /*                          → frontend/dist (SPA)
                              │
                        127.0.0.1 only
                       ├── Postgres :5432  (Docker)
                       └── MinIO    :9000  (Docker)
                              │
                        openrouter.ai
```

Frontend routes (`/intake`, `/stakeholder-needs`, `/skill-extraction`,
`/plo-synthesis`, `/plo-report`, `/pipeline`, and the index) do not collide with
any API prefix, so a catch-all static mount is safe as long as it is registered
**after** every `include_router` call.

## Components

### 1. Static frontend serving — `src/curriculum_agent/api/main.py`

Mount `frontend/dist` at `/` behind a `settings.serve_frontend` flag, after the
routers. The app uses `BrowserRouter`, so a reloaded deep link such as
`/plo-synthesis` arrives at the server as a real path and must fall back to
`index.html` rather than 404. `StaticFiles(html=True)` covers directory index
resolution but not arbitrary client-side paths, so the mount needs an explicit
SPA fallback for unmatched GETs.

Unknown paths under an API prefix must still 404 as JSON. The fallback applies
only to paths the routers did not claim.

When `serve_frontend` is false — the dev default — behaviour is exactly what it
is today: Vite serves the UI on 5173 and proxies to 8000.

### 2. CORS — `main.py:74-80`

`allow_origins` is currently the hardcoded list `["http://localhost:5173"]`. It
becomes `settings.cors_origins`, defaulting to that same value so dev is
unchanged. Under single origin the demo sets it empty; nothing cross-origin
happens.

### 3. API base URL — `frontend/src/api/client.ts:4`

`baseURL: 'http://localhost:8000'` becomes `baseURL: ''`. Requests then go to
whatever origin served the page: `localhost:5173` in dev (where the Vite proxy
forwards `/programs` and `/health` to 8000), and the tunnel hostname in the demo.
The proxy config in `vite.config.ts` already covers both prefixes.

### 4. SSE through the tunnel — `api/routes/evidence.py:59`

`GET /programs/{id}/evidence/classify-stream` returns `text/event-stream`. An
intermediary that buffers the response turns per-item progress into one burst at
the end, which reads as a frozen UI. The `StreamingResponse` gains
`Cache-Control: no-cache` and `X-Accel-Buffering: no`.

This must be verified through the tunnel, not on localhost — localhost cannot
reproduce the failure.

The frontend consumes this with `fetch` and an explicit `Accept` header
(`StakeholderNeeds.tsx:156`), not `EventSource`. That matters: the Cloudflare
Access cookie rides along on a normal fetch, whereas `EventSource` would need
`withCredentials` handling.

### 5. Configuration — `src/curriculum_agent/config.py`

Three new settings, each with a dev-safe default:

| Setting | Default | Purpose |
|---|---|---|
| `serve_frontend` | `False` | Mount the static bundle |
| `frontend_dist` | `Path("frontend/dist")` | Where the bundle lives |
| `cors_origins` | `["http://localhost:5173"]` | Replaces the hardcoded list |

`api_key` already exists and is not changed.

### 6. Service credentials — `docker-compose.yml`

The compose file currently hardcodes `curriculum_dev`, `minioadmin_dev`, and
pgAdmin's `admin`, all of which are committed to git. They move to `.env` with
fail-fast interpolation:

```yaml
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}
MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY:?set MINIO_SECRET_KEY in .env}
```

`:?` makes a missing value stop the stack rather than silently start it on a
default. Published ports bind to loopback (`127.0.0.1:5432:5432`,
`127.0.0.1:9000:9000`, `127.0.0.1:9001:9001`). pgAdmin moves behind a `debug`
profile so it does not start unless explicitly requested.

**Postgres password caveat:** `POSTGRES_PASSWORD` only takes effect when the
data directory is initialised. An existing `postgres-data` volume keeps the old
password, so the new value would break the connection instead of rotating it.
The implementation runs `ALTER USER curriculum WITH PASSWORD ...` against the
running container and updates `POSTGRES_DSN` in `.env` to match. Destroying the
volume is not an option — it holds real program data.

### 7. Demo startup script — `scripts/start-demo.ps1`

`start-dev.ps1` cannot be reused as-is for two reasons: it sets
`API_HOST = "0.0.0.0"` (line 74), which exposes the API on every interface, and
it hard-fails when Ollama is not running (lines 34-42), which is irrelevant when
the provider is OpenRouter.

The demo script is a separate file that:

- binds `API_HOST = "127.0.0.1"` and sets `API_RELOAD = "false"`
- skips the Ollama check; verifies `OPENROUTER_API_KEY` is present instead
- starts Docker services, waits for Postgres, runs `alembic upgrade head`
- runs `npm run build` in `frontend/` so the served bundle matches the source
- starts the API through `python -m curriculum_agent.api` (never the uvicorn CLI
  — the event-loop constraint documented in `api/main.py:18-40` still applies)
- prints the tunnel command to run next

`start-dev.ps1` is left alone.

### 8. Pre-demo backup

Every reviewer can delete any program: `DELETE /programs/{program_id}` has no
ownership check because there is no owner. A `pg_dump` into a timestamped file
before the demo is the entire mitigation, and it is enough for a shared-data
demo. The step goes in the runbook, not in code.

## Security Model

Access control lives entirely at the edge, in Cloudflare Access, configured as an
email allowlist. This is a deliberate trade-off and it needs to be stated plainly
rather than implied.

**The API has no authentication of its own during the demo.** `API_KEY` stays
unset, because `require_api_key` disables itself when the setting is blank
(`deps.py:24`) and the frontend sends no `X-API-Key` header at all — setting a
key would 401 every write in the UI. Access is therefore a single layer, and
three conditions must hold for it to be sufficient:

> Superseded 2026-11-11: every write route now requires X-API-Key and the UI asks for it (plan 2026-11-11-phase-leftovers Task 2).

1. **Port 8000 is never exposed directly.** The only path in is the tunnel. An
   open port bypasses Access completely.
2. **cloudflared targets `http://localhost:8000`**, matching the loopback bind.
3. **Access policy is an explicit email allowlist**, not "anyone with the link".

Two known gaps are accepted for this demo and recorded here so they are not
mistaken for oversights:

- GET routes carry no `require_api_key` dependency, so all program, evidence, and
  PLO data is readable by anyone who passes Access.
- Every authorised user can delete any program.

Both become real problems the moment the audience widens beyond an invited group.
Closing them means an axios interceptor, `require_api_key` on GET routes, and an
ownership column — a separate piece of work, deliberately not bundled here.

## Error Handling

| Failure | Behaviour |
|---|---|
| `frontend/dist` missing while `serve_frontend=True` | Fail at startup with a message naming `npm run build` — not a 404 per request |
| `OPENROUTER_API_KEY` unset | `start-demo.ps1` stops before starting anything |
| `POSTGRES_PASSWORD` / `MINIO_SECRET_KEY` unset | `docker compose` refuses to start (`:?`) |
| Tunnel down | Cloudflare's own error page; the local stack is unaffected |
| SSE stalls | Progress events arrive late but the classification still completes and persists — the stage is resumable |

## Testing

Unit and integration tests stay mocked and offline; none of them may require a
tunnel or a network LLM call.

- `serve_frontend=False` (the default) leaves the app's routes unchanged — assert
  no static mount is registered.
- `serve_frontend=True` against a temporary directory: a client route returns
  `index.html`, an unknown `/programs/...` path still returns a JSON 404, and
  `/health` is unaffected.
- `cors_origins` reaches the middleware instead of the hardcoded literal.
- The SSE response carries `Cache-Control` and `X-Accel-Buffering` headers.
- Config defaults are unchanged for every existing setting.

Manual verification through the tunnel, which automated tests cannot cover:
create a program end to end, watch `classify-stream` deliver incremental
progress, reload a deep link such as `/plo-report`, and confirm an
unauthenticated browser is stopped by Access.

## Files

**Modified**
- `src/curriculum_agent/config.py` — three settings added
- `src/curriculum_agent/api/main.py` — static mount, SPA fallback, CORS from settings
- `src/curriculum_agent/api/routes/evidence.py` — SSE headers
- `frontend/src/api/client.ts` — relative base URL
- `docker-compose.yml` — env-sourced credentials, loopback binds, pgAdmin profile
- `.env.example` — new keys documented

**Added**
- `scripts/start-demo.ps1`
- `docs/demo-runbook.md` — tunnel setup, Access policy, backup, teardown
- tests for the static mount, CORS wiring, and SSE headers

**Untouched**
- every file under `stages/`, `prompts/`, `models.py`, `exporters/`
- `scripts/start-dev.ps1`
- `Dockerfile` — stale (CUDA and torch are unused on this branch) but not on the
  path for this deployment; rewriting it belongs to a production deployment
