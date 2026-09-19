#Requires -Version 5.1
<#
.SYNOPSIS
  Start the FastAPI backend against data services that are already running.
.DESCRIPTION
  The API process, on its own. It starts no container and runs no migration: the
  database is start-services.ps1's job, and this refuses to run rather than
  quietly bringing one up, so a failure says "the database is not running" once
  instead of appearing 20 seconds later as a connection error from inside
  uvicorn.

  It does check the schema revision. An API against a database one migration
  behind fails on the first query that touches the new column, which reads as a
  code bug rather than as a step that was skipped.
.PARAMETER Port
  Port to bind. Default 8000.
.PARAMETER NoReload
  Turn off the file watcher. Reload is on by default for development.
#>
param([int]$Port = 8000, [switch]$NoReload)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# pyproject.toml, .env and the package are all resolved from the repo root.
Set-Location "$PSScriptRoot\.."

# Port checks, process discovery, and the pidfile contract - see the file header
# for why the pid Start-Process returns is not the one that binds the port.
. "$PSScriptRoot\_api-process.ps1"

function Write-Step { param([string]$msg) Write-Host ">> $msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$msg) Write-Host "   OK: $msg" -ForegroundColor Green }
function Write-Fail { param([string]$msg) Write-Host "   FAIL: $msg" -ForegroundColor Red; exit 1 }

# --- 1. Python ---
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

# --- 2. Ollama, but only if a slot actually resolves to it ---
# Every provider slot defaults to a hosted endpoint now, so a hard Ollama check
# failed the start over a dependency the run would never have used. Asked of the
# config rather than assumed either way: describe_target prints what each of the
# five slots resolved to, from the same list warmup_models reads.
Write-Step "Checking LLM providers..."
$target = & uv run python -c "from curriculum_agent.llm import describe_target; print(describe_target())" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Could not read the LLM configuration. Is .env present and valid?"
}
if ($target -like '*provider=ollama*') {
    $null = & ollama list 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Fail ("A provider slot is set to ollama but Ollama is not running. " +
            "Start it from the system tray, or point that slot elsewhere in .env.")
    }
    Write-Ok "Ollama running (a slot needs it)"
} else {
    Write-Ok "No slot uses Ollama - not checking it"
}

# --- 3. The database this API is about to talk to ---
# Checked here, not started here. Running docker compose up on every backend
# start is what made a code-change restart wait on Docker.
Write-Step "Checking data services..."
$null = docker exec ca-postgres pg_isready -U curriculum -d curriculum_agent 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Postgres is not accepting connections. Run .\scripts\start-services.ps1 first."
}
Write-Ok "Postgres ready"

Write-Step "Checking schema revision..."
$headRev = (& uv run alembic heads 2>$null) -join " "
$current = (& uv run alembic current 2>$null) -join " "
# Both commands print "<revision> (head)". Compare the revision id rather than
# the whole line, which also carries branch labels.
$headId = if ($headRev -match '([0-9a-f]{8,})') { $Matches[1] } else { $null }
if ($null -eq $headId) {
    Write-Fail "Could not read the migration head. Is alembic.ini reachable from the repo root?"
}
if ($current -notlike "*$headId*") {
    Write-Fail ("The database is not at the migration head ($headId). Run " +
        ".\scripts\start-services.ps1, which migrates, or: uv run alembic upgrade head")
}
Write-Ok "Schema at head ($headId)"

# --- 4. The port has to be ours to take ---
Write-Step "Checking port $Port..."
$null = Clear-PortForApi -Port $Port
Write-Ok "Port $Port free"

# --- 5. Start it ---
# Through the package entrypoint, not the uvicorn CLI: on Windows the CLI builds
# its event loop before importing the app, leaving psycopg with a
# ProactorEventLoop it refuses to use. See src/curriculum_agent/api/__main__.py.
Write-Step "Starting FastAPI..."
$env:API_HOST = "0.0.0.0"
$env:API_PORT = "$Port"
$env:API_RELOAD = if ($NoReload) { "false" } else { "true" }
$proc = Start-Process -FilePath "uv" `
    -ArgumentList "run", "python", "-m", "curriculum_agent.api" `
    -PassThru -NoNewWindow
Write-Ok "Launched (uv wrapper PID $($proc.Id))"

# --- 6. Confirm it answers, then record the pid that is actually listening ---
# The pidfile is written here and nowhere else. Start-Process hands back the uv
# wrapper's pid, layers above the process that owns the socket, and a run that
# dies on startup would otherwise leave that dead pid behind for the stop script
# to "stop" - which is how a working API ends up unstoppable.
Write-Step "Waiting for the API to answer on /health..."
if (-not (Wait-ApiHealthy -Port $Port -TimeoutSeconds 20)) {
    Write-Host "   API never answered - stopping whatever it left behind" -ForegroundColor Yellow
    $null = Stop-ApiProcess -Port $Port
    Write-Fail ("API did not answer on http://127.0.0.1:$Port/health within 20s. " +
        "Read the output above for the real error.")
}
Write-Ok "API is answering on /health"

$listenerPid = Save-ApiPid -Port $Port
if ($null -eq $listenerPid) {
    Write-Fail "API answered /health but nothing is listening on $Port - refusing to write a pidfile"
}
Write-Ok "Listening on $Port (PID $listenerPid, recorded in .uvicorn.pid)"

Write-Host ""
Write-Host "=== Backend ready ===" -ForegroundColor Yellow
Write-Host "  API:      http://localhost:$Port"
Write-Host "  API docs: http://localhost:$Port/docs"
Write-Host ""
Write-Host "  UI:   .\scripts\start-frontend.ps1"
Write-Host "  Stop: .\scripts\stop-backend.ps1"
