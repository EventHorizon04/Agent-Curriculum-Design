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

# API_KEY must stay unset: the frontend never sends X-API-Key, so a set value
# 401s every write (save, classify, checkpoint approve/reject) mid-demo. Never
# print the value itself, only whether the line is present.
if ($envText -match '(?m)^\s*API_KEY\s*=\s*\S') {
    Write-Fail ("API_KEY is set in .env. The UI sends no X-API-Key header, so this " +
        "401s every write. Comment it out. See docs/demo-runbook.md.")
}
Write-Ok "API_KEY left unset"

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
    # 2>$null, not 2>&1: under $ErrorActionPreference = "Stop", merging a native
    # command's stderr into the success stream can raise a terminating
    # NativeCommandError even on a clean "not ready yet" exit, aborting the
    # script with a message that looks nothing like "Postgres is not up yet".
    $null = docker exec ca-postgres pg_isready -U curriculum -d curriculum_agent 2>$null
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

# --- 7. Confirm the API actually answers ---
# Start-Process only hands back a PID; that process can die a second later
# (missing frontend/dist, port 8000 already bound, a bad DSN) and the operator
# would otherwise only find out once cloudflared is already pointed at a dead
# port. Poll /health for a few seconds before declaring success.
Write-Step "Waiting for the API to answer on /health..."
$healthTimeout = 15
$healthElapsed = 0
$healthy = $false
while ($healthElapsed -lt $healthTimeout) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch {
        # Connection refused / not listening yet — expected until the process
        # finishes starting up (or confirms it has died).
    }
    Start-Sleep -Seconds 1
    $healthElapsed++
}
if (-not $healthy) {
    Write-Fail ("API did not answer on http://127.0.0.1:8000/health within " +
        "${healthTimeout}s. Check that PID $($proc.Id) is still running and read " +
        "its output for the real error (missing frontend/dist, port already " +
        "bound, or a bad POSTGRES_DSN are the usual causes).")
}
Write-Ok "API is answering on /health"

Write-Host ""
Write-Host "=== Demo environment ready ===" -ForegroundColor Yellow
Write-Host "  Local:  http://127.0.0.1:8000"
Write-Host ""
Write-Host "  Next, in another terminal:" -ForegroundColor Yellow
Write-Host "    cloudflared tunnel --url http://127.0.0.1:8000"
Write-Host ""
Write-Host "  Then put the tunnel hostname behind Cloudflare Access."
Write-Host "  See docs/demo-runbook.md."
Write-Host ""
Write-Host "  Stop: .\scripts\stop-dev.ps1"
