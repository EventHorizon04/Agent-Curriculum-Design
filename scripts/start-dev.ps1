#Requires -Version 5.1
<#
.SYNOPSIS
  Start local dev environment: DB services (Docker) + FastAPI (local)
.DESCRIPTION
  Checks prerequisites, starts postgres/qdrant/minio via Docker Compose,
  runs Alembic migrations, then starts uvicorn in the background.
  React UI must be started separately: cd frontend && npm run dev
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step { param([string]$msg) Write-Host ">> $msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$msg) Write-Host "   OK: $msg" -ForegroundColor Green }
function Write-Fail { param([string]$msg) Write-Host "   FAIL: $msg" -ForegroundColor Red; exit 1 }

# --- 1. Check Python >= 3.11 ---
Write-Step "Checking Python version..."
try {
    $pyVer = & uv run python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
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

# --- 3. Start Docker DB services ---
Write-Step "Starting DB services (postgres, qdrant, minio)..."
docker compose up -d --remove-orphans
if ($LASTEXITCODE -ne 0) { Write-Fail "docker compose up failed" }
Write-Ok "Containers started"

# --- 4. Wait for postgres ready ---
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

# --- 5. Run migrations ---
Write-Step "Running Alembic migrations..."
uv run alembic upgrade head
if ($LASTEXITCODE -ne 0) { Write-Fail "Migration failed" }
Write-Ok "Migrations applied"

# --- 6. Start uvicorn in background ---
Write-Step "Starting FastAPI (uvicorn)..."
$proc = Start-Process -FilePath "uv" `
    -ArgumentList "run", "uvicorn", "curriculum_agent.api.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000" `
    -PassThru -NoNewWindow
$proc.Id | Out-File -FilePath ".uvicorn.pid" -Encoding utf8
Write-Ok "uvicorn started (PID $($proc.Id))"

# --- Done ---
Write-Host ""
Write-Host "=== Dev environment ready ===" -ForegroundColor Yellow
Write-Host "  API:           http://localhost:8000"
Write-Host "  API docs:      http://localhost:8000/docs"
Write-Host "  MinIO console: http://localhost:9001"
Write-Host "  Qdrant:        http://localhost:6333"
Write-Host ""
Write-Host "  UI (start separately):" -ForegroundColor Yellow
Write-Host "    cd frontend && npm run dev   ->  http://localhost:5173"
Write-Host ""
Write-Host "  Stop: .\scripts\stop-dev.ps1"
