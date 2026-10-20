# Demo package for customer machines

Date: 2026-10-20
Status: awaiting approval

## Intent

A customer wants to try the curriculum design agent on their own computer,
without us in the loop. We hand them a package; they run one script; the app
opens in their browser with the programs we have already run loaded, and they
can run new ones end to end.

This is a **demo**, not a deployment. The existing demo (`scripts/start-demo.ps1`
+ Cloudflare tunnel, `docs/demo-runbook.md`) runs on *our* machine and needs our
dev toolchain (uv, Node, Python). The package removes that: everything the
customer needs runs inside Docker.

## Who and where

- The customer, on their own Windows laptop or PC. All target machines are
  Windows.
- They start and stop it by running a script. The script drives Docker.
- One person on one machine. Nothing is shared over the network.

## Goals

1. **One-step start.** The customer runs one script and gets a working app in
   the browser. No Python, Node, uv, Ollama, or GPU on their machine — only
   Docker Desktop and an internet connection.
2. **Preloaded examples.** On first start the database already contains every
   program we have run, with all its rows (evidence, skills, Needs, PLOs,
   reviews, jobs, sessions). All of this data is publishable: the project holds
   no personal data and is planned for open-source release. This explicitly
   includes the TCISM program — its evidence text, the `llm_cache` rows quoting
   it, and the LangGraph checkpoint threads holding its `AgentState`. The
   `.gitignore` entry for the TCISM source files predates this decision (user,
   2026-10-20) and does not restrict what the package ships.
3. **Full pipeline works.** New programs can be run through every stage. LLM
   calls go to the cloud providers (OpenRouter / OpenTyphoon) using **our** API
   keys, shipped in the package.
4. **Data survives restarts.** Stopping and starting again keeps the customer's
   own work (Docker named volume). A separate reset script returns to the
   shipped examples.
5. **Reproducible packaging on our side.** One script on our machine produces
   the package from the current repo and the current local database.

## Non-goals

- Production readiness: authentication, user accounts, multi-user use, scaling,
  CI, backups, TLS.
- Cloudflare tunnel / remote access.
- macOS or Linux hosts.
- Local LLMs (Ollama) or GPU support.
- Changing pipeline behaviour.
- Updating an installed package in place while keeping the customer's data
  (a new package is a fresh install; see "Calls made").

## Anti-goals (failure even if it "works")

- The customer has to install a dev toolchain or edit config by hand to start.
- The app is reachable from other machines on the customer's network (it has no
  auth — the API binds loopback only, exactly as the current demo does).
- Our `.env` with keys, or the package output, gets committed to git.
- The package build silently ships an empty or stale database.
- The dev workflow (`start-services.ps1` / `start-backend.ps1` / `start-frontend.ps1`,
  `start-demo.ps1`) changes or breaks.

## Constraints

- `APP_ENV` stays `development` in the package.
  `_refuse_development_credentials_in_production` requires `API_KEY` under
  `production`, and the frontend never sends `X-API-Key`, so `production` would
  401 every write. Same reasoning as `docs/demo-runbook.md`.
- The API must be started through `python -m curriculum_agent.api`, not the
  uvicorn CLI (see the module docstring). Inside a Linux container the loop
  problem it works around does not occur, but the entrypoint also reads
  `API_HOST` / `API_PORT` and is the documented way in.
- `SERVE_FRONTEND=true` with `FRONTEND_DIST` pointing at the built bundle; the
  API then serves the UI on the same origin (`api/static.py`), so no CORS setup.
- Schema is owned by Alembic (`alembic upgrade head`). Current single head:
  `d1e2f3a4b5c6`. **`migrations/env.py` reads its URL only from `alembic.ini`**,
  which hardcodes the dev DSN on `127.0.0.1` with the dev password — inside the
  `app` container that is the wrong host and the wrong password. The container
  entrypoint must hand Alembic the package DSN (e.g. `env.py` preferring
  `POSTGRES_DSN` when set, or a `-x` override). Whatever is chosen must leave
  `uv run alembic upgrade head` from the repo root behaving exactly as today.
- Inside the container the API binds `0.0.0.0` (the `__main__.py` default);
  loopback-only comes from publishing the port as `127.0.0.1:<port>:8000`. Do
  **not** copy `API_HOST=127.0.0.1` from `start-demo.ps1` — inside a container it
  would make the published port unreachable.
- The LangGraph checkpoint tables live in their own `langgraph` schema
  (`postgres_dsn_langgraph`); a database dump must include it.
- MinIO is configured but **nothing imports `data/minio_store.py`** at runtime,
  so the package does not run MinIO. (Our call — see "Calls made".)
- The current `Dockerfile` is stale (CUDA base, torch, a non-existent `.[gpu]`
  extra, `pip install .` before `COPY src/`, `--reload`). Both
  `docs/demo-runbook.md:153` and the 2026-08-12 demo spec already note it as
  stale and unused.

## Decided

- **Target:** Windows hosts only; PowerShell scripts, plus a `.cmd` wrapper per
  script so a double-click works regardless of the PowerShell execution policy
  (`powershell -NoProfile -ExecutionPolicy Bypass -File ...`).
- **Runtime:** Docker Desktop. Containers: `postgres` and `app` (API + built UI).
- **LLM:** cloud APIs with our keys, prefilled in the package's `.env`.
- **Data:** the whole local database, every program, shipped as a seed.
- **Access:** loopback only, no auth.

### Security note on the shipped keys

Anyone holding the package can read the keys (they sit in `.env` and in the
container environment). Use a **dedicated key per provider for this demo**, set a
spending limit on it, and revoke it when the demo ends. The packaging script
must read the keys from a separate input (not our dev `.env`) so a dev key is
never shipped by accident — see "Packaging flow".

## Shape of the solution

### Container image (`Dockerfile`, replaces the stale one)

Multi-stage:

1. **frontend stage** — Node image, `npm ci`, `npm run build` → `frontend/dist`.
2. **python stage** — slim Python 3.11+ image, `uv sync --frozen` from
   `pyproject.toml` + `uv.lock` (pinned deps; `dev` is an optional extra, so it
   is already excluded without a flag), copy `src/`, `migrations/`,
   `alembic.ini`, and the built `frontend/dist` from stage 1.
3. Runs as a non-root user.
4. Entrypoint: wait for Postgres → `alembic upgrade head` → `python -m
   curriculum_agent.api`.

A `.dockerignore` is required: Docker does not read `.gitignore`, and without it
`.env`, `.venv`, `.scratch/`, `references/` and `node_modules` enter the build
context.

### Customer-side compose (`demo-package/docker-compose.yml` or similar)

- `postgres`: `postgres:16-alpine`, named volume, **no published port** (the app
  reaches it on the compose network, so a Postgres already running on the
  customer's machine does not collide).
- `app`: the image above, `depends_on` postgres (healthcheck), env from `.env`,
  published on `127.0.0.1:<port>:8000`.
- Seed: on first initialisation of the empty volume, Postgres loads the shipped
  dump (e.g. via `/docker-entrypoint-initdb.d/`). Alembic then finds the schema
  at head and does nothing.

### Customer scripts (in the package)

- `start.cmd` / `start.ps1` — check Docker Desktop is installed and running
  (clear Thai message if not), `docker compose up -d`, wait for `/health`, open
  the browser at the app URL.
- `stop.cmd` / `stop.ps1` — `docker compose down` (volume kept).
- `reset.cmd` / `reset.ps1` — confirm, then `down -v` and start again, which
  reseeds from the shipped dump.
- A short Thai `README` (อ่านก่อน): prerequisites (Docker Desktop, internet),
  how to start/stop/reset, the URL, and that the app is for local use only.

### Packaging flow (our side, `scripts/build-demo-package.ps1`)

1. Refuse to run if the local DB is down or not at Alembic head.
2. Read the demo LLM keys from a dedicated file (e.g. `.env.demo`, gitignored),
   **not** from `.env`.
3. Build the image.
4. `pg_dump` the local database (all schemas, including `langgraph`) into the
   seed file. Refuse if the dump contains zero programs.
5. Assemble the package folder under a gitignored output path: compose file,
   `.env` (demo keys + a Postgres password + the fixed runtime settings
   `SERVE_FRONTEND`, `FRONTEND_DIST`, `POSTGRES_DSN`, `APP_ENV=development` —
   **no** `*_PROVIDER` / `*_MODEL` lines, so every slot runs on the `SLOTS`
   defaults in `config.py`; the script writes `.env` from an explicit allowlist
   and never copies lines from another env file), seed,
   scripts, README, and the saved image tar (see "Image delivery").
6. Zip it, and print the zip path, size, program count, and image tag.

## Calls made (ours, not the customer's or the user's)

- Drop MinIO from the package: nothing reads or writes it at runtime.
- Drop pgadmin.
- Postgres port not published at all.
- `.cmd` wrappers for double-click.
- Postgres password is a fixed value generated at packaging time and written to
  the package `.env`; the database is not reachable from outside the compose
  network, so it guards nothing beyond the container boundary.
- Ship the full database dump, `langgraph` schema included, rather than a
  curated subset.
- Old `Dockerfile` is replaced, not kept beside the new one.
- **Models: `config.py` defaults only.** The package `.env` sets no provider or
  model, because a model choice lives in `SLOTS` in the repo (CLAUDE.md). Runs
  the customer starts may therefore differ from the shipped examples if those
  were produced under a dev `.env` override; that is accepted.
- **Each package is a fresh install.** The compose project name (and so the
  volume name) carries the package version, e.g. `curriculum-demo-<version>`.
  A newer package unzipped on the same machine starts on its own seeded volume
  instead of silently reusing an older one; the older volume is left in place
  and `reset` / `stop` scripts of a package only touch that package's project.
- **x86-64 only.** Images are built for `linux/amd64`. Windows-on-ARM machines
  are not a target; Docker Desktop there would have to emulate.
- Image size is the builder's to keep reasonable (runtime deps include large
  packages such as playwright and streamlit); trimming `pyproject.toml` is out
  of scope.

## Image delivery (decided, user 2026-10-20)

**Images ship inside the zip.** The packaging script `docker save`s both the
`app` image and `postgres:16-alpine` into one tar in the package. On start, the
customer script runs `docker load` when the expected image tag is not already
present, then `docker compose up`. Nothing is pulled from a registry, so the
only network traffic at runtime is the LLM API calls. A zip of roughly
0.5–1 GB is accepted. Registry push and build-on-customer-machine were rejected.

## Left to the builder

- Exact base images and versions, image tag scheme, app port number.
- Health-wait timeout and messages.
- Seed format (plain SQL vs custom-format + restore script) and how first-init
  detection works, as long as reseeding only happens on an empty volume.
- Whether `docs/demo-runbook.md` gains a section on the package or the package
  gets its own short doc.
- Verification: build the package, then run it on a clean environment (fresh
  volume, no dev toolchain on PATH) and confirm the examples load and one stage
  runs against the real API.
