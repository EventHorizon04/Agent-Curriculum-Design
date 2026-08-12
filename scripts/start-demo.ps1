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
