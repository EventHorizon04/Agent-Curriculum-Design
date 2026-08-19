#Requires -Version 5.1
<#
.SYNOPSIS
  Start local dev environment: DB services (Docker) + FastAPI (local)
.DESCRIPTION
  Checks prerequisites, starts postgres/minio via Docker Compose,
  runs Alembic migrations, then starts uvicorn in the background.
  React UI must be started separately: cd frontend && npm run dev
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Always run from the repo root so alembic.ini, docker-compose.yml, pyproject.toml are found.
Set-Location "$PSScriptRoot\.."

# Port checks, process discovery, and the pidfile contract  - see the file header
# for why the pid Start-Process returns is not the one that binds the port.
. "$PSScriptRoot\_api-process.ps1"

function Write-Step { param([string]$msg) Write-Host ">> $msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$msg) Write-Host "   OK: $msg" -ForegroundColor Green }
function Write-Fail { param([string]$msg) Write-Host "   FAIL: $msg" -ForegroundColor Red; exit 1 }

# --- 1. Check Python >= 3.11 ---
Write-Step "Checking Python version..."
try {
    $pyVer = & uv run python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $parts = $pyVer -split '\.'
    if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 11)) {
        Write-Fail "Python 3.11+ required. Got $pyVer"
    }
    Write-Ok "Python $pyVer"
} catch {
    Write-Fail "uv not found. Install uv: https://docs.astral.sh/uv/"
}

# --- 2. Check Ollama is running ---
Write-Step "Checking Ollama..."
try {
    $null = & ollama list 2>&1
    if ($LASTEXITCODE -ne 0) { throw "exit $LASTEXITCODE" }
    Write-Ok "Ollama running"
} catch {
    Write-Fail "Ollama not running. Start Ollama from the system tray first. https://ollama.com/download/windows"
}

# --- 3. Make sure port 8000 is ours to take ---
# Before Docker and the migrations, not after: an already-bound port used to
# surface at the very end as uvicorn's Errno 10048, by which point the script had
# already overwritten the pidfile of the run that was working.
Write-Step "Checking port 8000..."
$null = Clear-PortForApi -Port 8000
Write-Ok "Port 8000 free"

# --- 4. Start Docker DB services ---
Write-Step "Starting DB services (postgres, minio)..."
docker compose up -d --remove-orphans
if ($LASTEXITCODE -ne 0) { Write-Fail "docker compose up failed" }
Write-Ok "Containers started"

# --- 5. Wait for postgres ready ---
Write-Step "Waiting for postgres..."
$timeout = 30
$elapsed = 0
while ($elapsed -lt $timeout) {
    $result = docker exec ca-postgres pg_isready -U curriculum -d curriculum_agent 2>&1
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 1
    $elapsed++
}
if ($elapsed -ge $timeout) { Write-Fail "Postgres not ready after ${timeout}s" }
Write-Ok "Postgres ready"

# --- 6. Run migrations ---
Write-Step "Running Alembic migrations..."
uv run alembic upgrade head
if ($LASTEXITCODE -ne 0) { Write-Fail "Migration failed" }
Write-Ok "Migrations applied"

# --- 7. Start uvicorn in background ---
# Launched through the package entrypoint, not the uvicorn CLI: on Windows the
# CLI builds its event loop before importing the app, leaving psycopg with a
# ProactorEventLoop it refuses to use. See src/curriculum_agent/api/__main__.py.
Write-Step "Starting FastAPI (uvicorn)..."
$env:API_HOST = "0.0.0.0"
$env:API_PORT = "8000"
$env:API_RELOAD = "true"
$proc = Start-Process -FilePath "uv" `
    -ArgumentList "run", "python", "-m", "curriculum_agent.api" `
    -PassThru -NoNewWindow
Write-Ok "uvicorn launched (uv wrapper PID $($proc.Id))"

# --- 8. Confirm it answers, then record the pid that is actually listening ---
# The pidfile is written here and nowhere else. Start-Process hands back the uv
# wrapper's pid, layers above the process that owns the socket, and a run that
# dies on startup would otherwise leave that dead pid behind for stop-dev.ps1 to
# "stop"  - which is how a working API ends up unstoppable.
Write-Step "Waiting for the API to answer on /health..."
if (-not (Wait-ApiHealthy -Port 8000 -TimeoutSeconds 20)) {
    Write-Host "   API never answered - stopping whatever it left behind" -ForegroundColor Yellow
    $null = Stop-ApiProcess -Port 8000
    Write-Fail ("API did not answer on http://127.0.0.1:8000/health within 20s. " +
        "Read the output above for the real error (a bad POSTGRES_DSN or an " +
        "Ollama model that is not pulled are the usual causes).")
}
Write-Ok "API is answering on /health"

$listenerPid = Save-ApiPid -Port 8000
if ($null -eq $listenerPid) {
    Write-Fail "API answered /health but nothing is listening on 8000 - refusing to write a pidfile"
}
Write-Ok "Listening on 8000 (PID $listenerPid, recorded in .uvicorn.pid)"

# --- Done ---
Write-Host ""
Write-Host "=== Dev environment ready ===" -ForegroundColor Yellow
Write-Host "  API:           http://localhost:8000"
Write-Host "  API docs:      http://localhost:8000/docs"
Write-Host "  MinIO console: http://localhost:9001"
Write-Host ""
Write-Host "  UI (start separately):" -ForegroundColor Yellow
Write-Host "    cd frontend && npm run dev   ->  http://localhost:5173"
Write-Host ""
Write-Host "  Stop: .\scripts\stop-dev.ps1"
