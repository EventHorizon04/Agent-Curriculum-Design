# Demo Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One script on our machine produces a zip; on a customer's Windows PC with only Docker Desktop, one double-click starts the app in the browser with every stored program preloaded.

**Architecture:** A new multi-stage `Dockerfile` builds one `app` image (built UI + API, migrations on start). A customer-side template folder (`packaging/demo/`) holds a compose file and PowerShell/`.cmd` scripts. A Python builder (`scripts/demo_package.py`) builds the image, dumps the local DB as an init seed, `docker save`s both images, writes an allowlisted `.env`, and zips the lot.

**Tech Stack:** Docker / Compose v2, `python:3.11-slim` + uv, `node:22-alpine`, `postgres:16-alpine`, PowerShell 5.1, pytest.

**Spec:** `docs/superpowers/specs/2026-10-20-demo-package-design.md`

## Global Constraints

- Work on branch `feat/demo-package`. Never commit to `main`. The working tree carries unrelated uncommitted changes (CLAUDE.md, `.claude/`, `.scratch/`): `git add` only the files a task names, never `git add -A` / `.`.
- `APP_ENV=development` in the package (production would 401 every write — spec "Constraints").
- Container API binds `0.0.0.0`; loopback-only comes from publishing `127.0.0.1:${APP_PORT}:8000`. Never set `API_HOST=127.0.0.1` in the container.
- Postgres publishes **no** port in the package compose.
- Package `.env` sets **no** `*_PROVIDER` / `*_MODEL` line; it is written from an explicit allowlist, never copied from another env file.
- LLM keys come from `.env.demo` (gitignored), never from `.env`.
- Images: `linux/amd64` only. Postgres image tag `postgres:16-alpine` everywhere.
- Each package is a fresh install: `COMPOSE_PROJECT_NAME=curriculum-demo-<version>`, app image `curriculum-demo-app:<version>`, `<version>` = `YYYYMMDD-HHMM`.
- Dev workflow (`start-services.ps1`, `start-backend.ps1`, `start-frontend.ps1`, `start-demo.ps1`, `uv run alembic upgrade head`) must behave exactly as today.
- `.ps1` files in `packaging/demo/` are saved **UTF-8 with BOM** (PowerShell 5.1 reads BOM-less files as ANSI and garbles Thai) and set `[Console]::OutputEncoding = [Text.Encoding]::UTF8` first. User-facing messages are Thai.
- `docker/entrypoint.sh` must have LF line endings (CRLF makes the container fail with `no such file or directory`); enforce with `.gitattributes`.
- App port in the package: `8765` (default; customer may edit `APP_PORT` in `.env`).
- Package output under `dist/demo-package/` (already gitignored by `dist/`).

## Review Focus

1. **Docker Desktop installed but not running** (or still starting) → `start.ps1` prints a Thai message saying to open Docker Desktop and exits non-zero within seconds; it must not hang on `docker compose`. Pinned in Task 5, scenario A.
2. **`APP_PORT` already in use** on the customer's machine → `start.ps1` checks the port before `compose up` and prints a Thai message naming the port and the `.env` line to change. Pinned in Task 5, scenario B.
3. **Package unzipped under a path with spaces or Thai characters** (e.g. `C:\Users\ผู้ใช้\Downloads\curriculum demo\`) → every `.cmd` calls `"%~dp0<name>.ps1"` quoted and every script `Set-Location $PSScriptRoot`. Static test in Task 3; live run in Task 5, scenario C.
4. **First start is slow** (`docker load` of ~1 GB plus seeding) → health wait is at least 300 s with a progress line every 10 s; a second start skips `docker load`. Static test in Task 3; live check in Task 5.
5. **`.env.demo` missing, or a key blank** → the builder raises `PackagingError` before building or dumping anything. Unit test in Task 4.

---

### Task 1: Alembic URL override (and commit the spec)

**Files:**
- Create: `src/curriculum_agent/data/migration_url.py`
- Modify: `migrations/env.py` (both `config.get_main_option("sqlalchemy.url")` call sites)
- Test: `tests/unit/test_migration_url.py`
- Commit also: `docs/superpowers/specs/2026-10-20-demo-package-design.md`, this plan

**Interfaces:**
- Produces: `resolve_migration_url(x_args: Mapping[str, str], ini_url: str | None) -> str` — `x_args["url"]` when present and non-blank, else `ini_url`; raises `RuntimeError` when both are missing/blank. Entry point used later: `alembic -x url="$POSTGRES_DSN" upgrade head`.

- [ ] **Step 1: Create branch** — `git switch -c feat/demo-package`; `git branch --show-current` prints `feat/demo-package`.
- [ ] **Step 2: Write failing tests** in `tests/unit/test_migration_url.py`:

```python
def test_x_url_wins_over_ini():
    assert resolve_migration_url({"url": "postgresql+asyncpg://u:p@db:5432/x"}, "ini") == "postgresql+asyncpg://u:p@db:5432/x"

def test_falls_back_to_ini_without_x_url():
    assert resolve_migration_url({}, "ini-url") == "ini-url"

def test_blank_x_url_falls_back_to_ini():
    assert resolve_migration_url({"url": "  "}, "ini-url") == "ini-url"

def test_raises_when_neither_is_set():
    with pytest.raises(RuntimeError):
        resolve_migration_url({}, None)
```

- [ ] **Step 3: Run** `uv run pytest tests/unit/test_migration_url.py -v` — FAIL (module missing).
- [ ] **Step 4: Implement** `resolve_migration_url` in `migration_url.py`; in `env.py` compute `url = resolve_migration_url(context.get_x_argument(as_dictionary=True), config.get_main_option("sqlalchemy.url"))` once and use it at both call sites.
- [ ] **Step 5: Run** the new tests — PASS; then `uv run pytest -q` — all pass; `uv run alembic current` against the dev DB still prints `d1e2f3a4b5c6 (head)` (dev path unchanged).
- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/data/migration_url.py migrations/env.py tests/unit/test_migration_url.py docs/superpowers/specs/2026-10-20-demo-package-design.md docs/superpowers/plans/2026-10-20-demo-package.md
git commit -m "feat: let alembic take its URL from -x url for the demo container"
```

---

### Task 2: App image (`Dockerfile`, `.dockerignore`, entrypoint)

**Files:**
- Replace: `Dockerfile`
- Create: `.dockerignore`, `docker/entrypoint.sh`, `.gitattributes`
- Modify: `docs/demo-runbook.md:153` (drop the "Dockerfile is stale" note)
- Test: `tests/unit/test_docker_build_inputs.py`

**Interfaces:**
- Consumes: Task 1's `-x url` override.
- Produces: an image whose entrypoint runs `alembic -x url="$POSTGRES_DSN" upgrade head` then `exec python -m curriculum_agent.api`; listens on `0.0.0.0:8000`; serves the UI when `SERVE_FRONTEND=true` and `FRONTEND_DIST=/app/frontend/dist`; runs as a non-root user; `WORKDIR /app` with `alembic.ini` and `migrations/` there.

- [ ] **Step 1: Write failing tests** in `tests/unit/test_docker_build_inputs.py`:

```python
REQUIRED_IGNORES = {".env", ".env.*", ".venv", ".scratch", "references", "node_modules", "dist", ".git", "tests"}

def test_dockerignore_keeps_secrets_and_data_out():
    lines = {l.strip().rstrip("/") for l in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
    assert REQUIRED_IGNORES <= lines

def test_entrypoint_has_lf_line_endings():
    assert b"\r" not in (ROOT / "docker" / "entrypoint.sh").read_bytes()

def test_entrypoint_migrates_with_package_dsn_then_execs_api():
    text = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert 'alembic -x url="$POSTGRES_DSN" upgrade head' in text
    assert "exec python -m curriculum_agent.api" in text
    assert text.index("alembic") < text.index("exec python")

def test_dockerfile_does_not_reload_or_use_cuda():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "--reload" not in text and "cuda" not in text.lower() and "torch" not in text
    assert "uv sync --frozen" in text and "USER " in text
```

`ROOT = Path(__file__).resolve().parents[2]`. Note `frontend/dist` is excluded because stage 1 builds it.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_docker_build_inputs.py -v` — FAIL.
- [ ] **Step 3: Write `.gitattributes`** with `*.sh text eol=lf`, then `docker/entrypoint.sh` (`#!/bin/sh`, `set -e`, the two commands above).
- [ ] **Step 4: Write `.dockerignore`** with every entry in `REQUIRED_IGNORES`, one per line.
- [ ] **Step 5: Write `Dockerfile`** — stage `frontend` (`node:22-alpine`, copy `frontend/package*.json`, `npm ci`, copy `frontend/`, `npm run build`); stage `app` (`python:3.11-slim`, uv binary copied from a pinned `ghcr.io/astral-sh/uv:<version>` image, `uv sync --frozen --no-install-project` on `pyproject.toml`+`uv.lock` first for layer caching, then copy `src/`, `migrations/`, `alembic.ini`, `docker/entrypoint.sh`, `uv sync --frozen`; copy `/app/frontend/dist` from stage `frontend`; `ENV PATH=/app/.venv/bin:$PATH`; create and switch to a non-root user; `EXPOSE 8000`; `ENTRYPOINT ["/app/docker/entrypoint.sh"]`).
- [ ] **Step 6: Run tests** — PASS.
- [ ] **Step 7: Build and smoke-test the image**

Run: `docker build --platform linux/amd64 -t curriculum-demo-app:dev .`
Expected: build succeeds.
Run: `docker run --rm --entrypoint sh curriculum-demo-app:dev -c "test ! -e /app/.env && test -f /app/frontend/dist/index.html && python -c 'import curriculum_agent.api.main' && whoami"`
Expected: exit 0, prints a non-`root` user name.

- [ ] **Step 8: Edit `docs/demo-runbook.md:153`** — remove the stale-Dockerfile bullet; `uv run pytest -q` all pass.
- [ ] **Step 9: Commit**

```bash
git add Dockerfile .dockerignore .gitattributes docker/entrypoint.sh tests/unit/test_docker_build_inputs.py docs/demo-runbook.md
git commit -m "feat: multi-stage app image for the demo package"
```

---

### Task 3: Customer-side template (`packaging/demo/`)

**Files:**
- Create: `packaging/demo/docker-compose.yml`, `start.ps1`, `stop.ps1`, `reset.ps1`, `start.cmd`, `stop.cmd`, `reset.cmd`, `README-TH.txt`
- Test: `tests/unit/test_demo_package_template.py`

**Interfaces:**
- Consumes: Task 2's image contract. Reads these `.env` keys (written by Task 4): `COMPOSE_PROJECT_NAME`, `APP_IMAGE`, `APP_PORT`, `POSTGRES_PASSWORD`, plus app env passed through `env_file: .env`.
- Produces: a folder that, together with `.env`, `seed/01-seed.sql.gz` and `images.tar` (from Task 4), is a runnable package. `start.ps1` contract: exit 0 after opening the browser; exit 1 with a Thai message on any precondition failure.

- [ ] **Step 1: Write failing tests** in `tests/unit/test_demo_package_template.py` (`yaml.safe_load` for compose):

```python
def test_postgres_publishes_no_port_and_seeds_from_folder():
    pg = compose()["services"]["postgres"]
    assert "ports" not in pg
    assert pg["image"] == "postgres:16-alpine"
    assert "./seed:/docker-entrypoint-initdb.d:ro" in pg["volumes"]
    # TCP, not the unix socket: during initdb the image runs a temporary server
    # with listen_addresses='' — a socket check reports "ready" while the seed
    # is still loading, and the app's alembic would race it.
    assert "-h 127.0.0.1" in " ".join(pg["healthcheck"]["test"])

def test_app_binds_loopback_only_and_waits_for_healthy_db():
    app = compose()["services"]["app"]
    assert app["ports"] == ["127.0.0.1:${APP_PORT}:8000"]
    assert app["image"] == "${APP_IMAGE}"
    assert app["env_file"] == [".env"] or app["env_file"] == ".env"
    assert app["depends_on"]["postgres"]["condition"] == "service_healthy"

def test_no_minio_or_pgadmin():
    assert set(compose()["services"]) == {"postgres", "app"}

@pytest.mark.parametrize("name", ["start", "stop", "reset"])
def test_ps1_has_bom_and_utf8_console(name):
    raw = (TEMPLATE / f"{name}.ps1").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert "[Console]::OutputEncoding = [Text.Encoding]::UTF8" in raw.decode("utf-8-sig")
    assert "Set-Location $PSScriptRoot" in raw.decode("utf-8-sig")

@pytest.mark.parametrize("name", ["start", "stop", "reset"])
def test_cmd_wrapper_bypasses_policy_with_quoted_path(name):
    text = (TEMPLATE / f"{name}.cmd").read_text(encoding="ascii")
    assert f'-ExecutionPolicy Bypass -File "%~dp0{name}.ps1"' in text

def test_start_loads_images_only_when_missing_and_waits_long_enough():
    text = (TEMPLATE / "start.ps1").read_text(encoding="utf-8-sig")
    assert "docker image inspect" in text and "docker load -i" in text
    assert "$HealthTimeoutSeconds = 300" in text
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_demo_package_template.py -v` — FAIL.
- [ ] **Step 3: Write `docker-compose.yml`** — services `postgres` (`postgres:16-alpine`, `POSTGRES_USER: curriculum`, `POSTGRES_DB: curriculum_agent`, `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}`, named volume `pgdata`, seed mount above, healthcheck `["CMD", "pg_isready", "-h", "127.0.0.1", "-U", "curriculum", "-d", "curriculum_agent"]` with `start_period` long enough for the seed load, e.g. `120s`) and `app` (fields asserted above, `restart: unless-stopped`); top-level `volumes: {pgdata: {}}`. Project name comes from `COMPOSE_PROJECT_NAME` in `.env`.
- [ ] **Step 4: Write `start.ps1`** (UTF-8 BOM) in this order: UTF-8 console, `Set-Location $PSScriptRoot`, read `.env` into a hashtable, `docker` on PATH? else Thai "ไม่พบ Docker — ติดตั้ง Docker Desktop ก่อน" exit 1; `docker info` succeeds? else "เปิด Docker Desktop แล้วรอจนขึ้นว่า running จากนั้นรันใหม่" exit 1; port `APP_PORT` free (`Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue`, skipped when this project's `app` container is already running)? else Thai message naming the port and `APP_PORT=` in `.env`, exit 1; `docker image inspect $APP_IMAGE` fails → `docker load -i images.tar`; `docker compose up -d`; poll `http://127.0.0.1:$port/health` every 2 s up to `$HealthTimeoutSeconds = 300`, printing a progress line every 10 s; on timeout print `docker compose logs --tail 50 app` and a Thai hint, exit 1; on success `Start-Process "http://127.0.0.1:$port/"`.
- [ ] **Step 5: Write `stop.ps1`** (`docker compose down`, volume kept) and `reset.ps1` (Thai confirmation `Read-Host` requiring `y`; then `docker compose down -v`; then `& "$PSScriptRoot\start.ps1"`).
- [ ] **Step 6: Write the three `.cmd` wrappers** — `@echo off`, `powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0<name>.ps1"`, `pause` (so the window stays open on error).
- [ ] **Step 7: Write `README-TH.txt`** (UTF-8 BOM, Thai): requires Docker Desktop + internet; double-click `start.cmd`; first start takes several minutes; URL `http://127.0.0.1:8765/`; `stop.cmd`; `reset.cmd` restores the shipped examples and deletes the customer's own work; for use on this machine only.
- [ ] **Step 8: Run tests** — PASS. Also parse each script: `powershell -NoProfile -Command "$null = [scriptblock]::Create((Get-Content -Raw -Encoding UTF8 packaging/demo/start.ps1))"` (repeat for stop/reset) — no parse error.
- [ ] **Step 9: Commit**

```bash
git add packaging/demo tests/unit/test_demo_package_template.py
git commit -m "feat: customer-side compose and start/stop/reset scripts for the demo package"
```

---

### Task 4: Package builder (`scripts/demo_package.py` + `.ps1` wrapper)

**Files:**
- Create: `scripts/demo_package.py`, `scripts/build-demo-package.ps1`
- Modify: `.gitignore` (add `.env.demo`)
- Test: `tests/unit/test_demo_package_builder.py` (import the script by path with `importlib.util.spec_from_file_location`)

**Interfaces:**
- Consumes: Task 2 `Dockerfile`; Task 3 `packaging/demo/` (copied verbatim); dev container `ca-postgres` (user `curriculum`, db `curriculum_agent`).
- Produces, in `scripts/demo_package.py`:
  - `class PackagingError(RuntimeError)`
  - `POSTGRES_IMAGE = "postgres:16-alpine"`, `APP_PORT = 8765`, `DEMO_KEY_NAMES = ("OPENROUTER_API_KEY", "OPENTYPHOON_API_KEY")`
  - `PACKAGE_ENV_KEYS = ("COMPOSE_PROJECT_NAME", "APP_IMAGE", "APP_PORT", "APP_ENV", "SERVE_FRONTEND", "FRONTEND_DIST", "POSTGRES_PASSWORD", "POSTGRES_DSN", "OPENROUTER_API_KEY", "OPENTYPHOON_API_KEY")`
  - `class DemoKeys(NamedTuple): openrouter: str; opentyphoon: str`
  - `read_demo_keys(path: Path) -> DemoKeys` — reads only `DEMO_KEY_NAMES` from `KEY=VALUE` lines (comments and other keys ignored, surrounding quotes stripped); `PackagingError` if the file is missing or either key is absent/blank.
  - `package_version(now: datetime) -> str` → `now.strftime("%Y%m%d-%H%M")`
  - `render_package_env(*, version: str, keys: DemoKeys, postgres_password: str, app_port: int = APP_PORT) -> str` — exactly the `PACKAGE_ENV_KEYS` lines in that order: `curriculum-demo-{version}`, `curriculum-demo-app:{version}`, port, `development`, `true`, `/app/frontend/dist`, password, `postgresql+asyncpg://curriculum:{password}@postgres:5432/curriculum_agent`, the two keys.
  - `expected_alembic_heads(repo_root: Path) -> set[str]` — via `alembic.script.ScriptDirectory.from_config(Config(repo_root / "alembic.ini"))`.
  - `build_package(repo_root: Path, keys_file: Path, out_dir: Path, now: datetime) -> Path` — returns the zip path.
  - `main(argv: list[str] | None = None) -> int` — `--keys-file` (default `.env.demo`), `--out` (default `dist/demo-package`).

- [ ] **Step 1: Write failing tests:**

```python
def test_read_demo_keys_reads_only_the_two_keys(tmp_path):
    f = tmp_path / ".env.demo"
    f.write_text('# c\nOPENROUTER_API_KEY="or-1"\nOPENTYPHOON_API_KEY=ty-1\nPLO_SYNTHESIS_MODEL=x\n', encoding="utf-8")
    assert dp.read_demo_keys(f) == dp.DemoKeys("or-1", "ty-1")

def test_read_demo_keys_refuses_missing_file(tmp_path):
    with pytest.raises(dp.PackagingError):
        dp.read_demo_keys(tmp_path / "nope")

@pytest.mark.parametrize("body", ["OPENROUTER_API_KEY=or\n", "OPENROUTER_API_KEY=or\nOPENTYPHOON_API_KEY=\n"])
def test_read_demo_keys_refuses_blank_or_absent_key(tmp_path, body):
    f = tmp_path / ".env.demo"; f.write_text(body, encoding="utf-8")
    with pytest.raises(dp.PackagingError):
        dp.read_demo_keys(f)

def test_render_env_is_exactly_the_allowlist():
    text = dp.render_package_env(version="20261020-1530", keys=dp.DemoKeys("or", "ty"), postgres_password="ab12")
    keys = [l.split("=", 1)[0] for l in text.splitlines() if l]
    assert tuple(keys) == dp.PACKAGE_ENV_KEYS
    assert not any(k.endswith(("_PROVIDER", "_MODEL")) or k == "API_HOST" for k in keys)
    assert "COMPOSE_PROJECT_NAME=curriculum-demo-20261020-1530" in text
    assert "APP_IMAGE=curriculum-demo-app:20261020-1530" in text
    assert "APP_ENV=development" in text
    assert "POSTGRES_DSN=postgresql+asyncpg://curriculum:ab12@postgres:5432/curriculum_agent" in text

def test_package_version_format():
    assert dp.package_version(datetime(2026, 10, 20, 15, 30)) == "20261020-1530"

def test_postgres_image_matches_template_compose():
    assert compose_template()["services"]["postgres"]["image"] == dp.POSTGRES_IMAGE

def test_build_refuses_bad_keys_before_any_docker_call(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(dp.subprocess, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(dp.PackagingError):
        dp.build_package(ROOT, tmp_path / "missing", tmp_path / "out", datetime(2026, 10, 20))
    assert calls == []

def test_env_demo_is_gitignored():
    assert subprocess.run(["git", "check-ignore", "-q", ".env.demo"], cwd=ROOT).returncode == 0
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_demo_package_builder.py -v` — FAIL.
- [ ] **Step 3: Implement the pure functions** and add `.env.demo` to `.gitignore` next to `.env`.
- [ ] **Step 4: Implement `build_package`** in this order, every external call through `subprocess.run(..., check=True)`, raising `PackagingError` with a clear English message on each refusal:
  1. `read_demo_keys(keys_file)` (first — before any docker call).
  2. DB at head: `docker exec ca-postgres psql -U curriculum -d curriculum_agent -tAc "select version_num from alembic_version"` ∈ `expected_alembic_heads`; else refuse (DB down also refuses).
  3. `select count(*) from programs` ≥ 1; else refuse.
  4. `version = package_version(now)`; package dir `out_dir / f"curriculum-demo-{version}"`; refuse if it exists.
  5. `docker build --platform linux/amd64 -t curriculum-demo-app:{version} {repo_root}`.
  6. `docker pull --platform linux/amd64 {POSTGRES_IMAGE}`.
  7. Copy `packaging/demo/*` into the package dir.
  8. `docker exec ca-postgres pg_dump -U curriculum -d curriculum_agent --no-owner --no-privileges` → gzip → `seed/01-seed.sql.gz`; refuse if the uncompressed dump has no `COPY public.programs` line.
  9. `.env` = `render_package_env(version=..., keys=..., postgres_password=secrets.token_hex(16))`, written UTF-8 without BOM.
  10. `docker save -o images.tar curriculum-demo-app:{version} {POSTGRES_IMAGE}`.
  11. `shutil.make_archive` → `out_dir / f"curriculum-demo-{version}.zip"` (root folder inside the zip = package dir name).
  12. Print zip path, size in MB, program count, image tag. Never print `.env` contents.
- [ ] **Step 5: Write `scripts/build-demo-package.ps1`** — `Set-Location "$PSScriptRoot\.."`; `uv run python scripts/demo_package.py @args`; exit with its code.
- [ ] **Step 6: Run** the builder tests — PASS; `uv run pytest -q`, `uv run ruff check src/ tests/ scripts/`, `uv run mypy src/` — all clean.
- [ ] **Step 7: Commit**

```bash
git add scripts/demo_package.py scripts/build-demo-package.ps1 tests/unit/test_demo_package_builder.py .gitignore
git commit -m "feat: build-demo-package script producing the customer zip"
```

---

### Task 5: End-to-end verification on a clean install + docs

**Files:**
- Modify: `docs/demo-runbook.md` (new section "แพ็ก demo ให้ลูกค้า / Demo package": create `.env.demo` with dedicated, spending-limited keys; run `.\scripts\build-demo-package.ps1`; what the zip contains; revoke keys after the demo)

**Interfaces:**
- Consumes: everything above. No code produced; this task proves the package.

- [ ] **Step 1: Build** — create `.env.demo` with the demo keys (the user supplies them; do not read `.env`), run `.\scripts\build-demo-package.ps1`. Expected: prints a zip under `dist\demo-package\`, program count `3` (or the current count), size roughly 0.5–1 GB.
- [ ] **Step 2: Scenario C (path with spaces and Thai)** — unzip into `%TEMP%\ทดสอบ demo\`. Remove the app image locally first (`docker image rm curriculum-demo-app:<version>`) so `start.cmd` must `docker load`.
- [ ] **Step 3: Fresh start** — run `start.cmd` from that folder. Expected: loads images, progress lines, browser opens `http://127.0.0.1:8765/`; `GET /health` → `{"status":"ok"}`; `GET /programs/` lists the same program ids as the dev DB.
- [ ] **Step 4: One stage against the real API** — trigger `POST /programs/{id}/plos/review/run` for one shipped program; poll `GET /programs/{id}/jobs` until `succeeded`.
- [ ] **Step 5: Restart keeps data, second start skips load** — `stop.cmd`, `start.cmd`. Expected: no `docker load` line; the review from Step 4 is still there.
- [ ] **Step 6: Scenario B (port busy)** — with the package running, copy the package folder, change only `COMPOSE_PROJECT_NAME` in the copy's `.env` (keep `APP_PORT=8765`), run the copy's `start.cmd` → Thai port-in-use message naming 8765, exit 1, no container of the copy's project started.
- [ ] **Step 7: Scenario A (Docker not running)** — quit Docker Desktop, run `start.cmd` → Thai "เปิด Docker Desktop" message within ~10 s, exit 1.
- [ ] **Step 8: Reset** — `reset.cmd`, answer `y`. Expected: the Step 4 review is gone, the shipped programs are back.
- [ ] **Step 9: Not reachable from the network** — `Get-NetTCPConnection -LocalPort 8765 -State Listen` shows only `127.0.0.1`.
- [ ] **Step 10: Clean up** — `stop.cmd`, `docker compose -p curriculum-demo-<version> down -v` for the test projects; confirm dev stack (`ca-postgres`) untouched and `.\scripts\start-backend.ps1` still starts.
- [ ] **Step 11: Write the runbook section, commit**

```bash
git add docs/demo-runbook.md
git commit -m "docs: how to build and hand over the demo package"
```
