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

# Port checks, process discovery, and the pidfile contract  - see the file header
# for why the pid Start-Process returns is not the one that binds the port.
. "$PSScriptRoot\_api-process.ps1"

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

# --- 2. Make sure port 8000 is ours to take ---
# Before Docker and the build, not after: an already-bound port used to surface
# 12 steps later as uvicorn's Errno 10048, by which point the script had already
# overwritten the pidfile of the run that was working.
Write-Step "Checking port 8000..."
$null = Clear-PortForApi -Port 8000
Write-Ok "Port 8000 free"

# --- 3. Data services and schema ---
# Delegated rather than repeated: this used to carry its own copy of the compose
# call, the pg_isready loop and the alembic step, which is three places for one
# procedure to drift in.
Write-Step "Starting data services..."
& "$PSScriptRoot\start-services.ps1"
if ($LASTEXITCODE -ne 0) { Write-Fail "Data services did not come up" }

# --- 4. Build the frontend ---
# Built here rather than assumed: the API serves whatever is in frontend/dist,
# and a stale bundle is invisible until someone reports missing UI.
Write-Step "Building the React bundle..."
Push-Location frontend
npm run build
$buildFailed = $LASTEXITCODE -ne 0
Pop-Location
if ($buildFailed) { Write-Fail "npm run build failed" }
Write-Ok "Bundle built to frontend/dist"

# --- 5. Start the API on loopback ---
# 127.0.0.1, not 0.0.0.0: the Cloudflare Tunnel is the only intended way in, and
# an interface-wide bind lets anyone on the LAN skip Cloudflare Access entirely.
# Launched through the package entrypoint, not the uvicorn CLI  - see
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
Write-Ok "API launched (uv wrapper PID $($proc.Id))"

# --- 6. Confirm the API answers, then record the pid that is actually listening ---
# The pidfile is written here and nowhere else. Start-Process hands back the uv
# wrapper's pid, two layers above the process that owns the socket, and a run that
# dies on startup would otherwise leave that dead pid behind for stop-dev.ps1 to
# "stop"  - which is how a working API ends up unstoppable.
Write-Step "Waiting for the API to answer on /health..."
if (-not (Wait-ApiHealthy -Port 8000 -TimeoutSeconds 15)) {
    Write-Host "   API never answered - stopping whatever it left behind" -ForegroundColor Yellow
    $null = Stop-ApiProcess -Port 8000
    Write-Fail ("API did not answer on http://127.0.0.1:8000/health within 15s. " +
        "Read the output above for the real error (missing frontend/dist, a bad " +
        "POSTGRES_DSN, or a missing OpenRouter model are the usual causes).")
}
Write-Ok "API is answering on /health"

$listenerPid = Save-ApiPid -Port 8000
if ($null -eq $listenerPid) {
    Write-Fail "API answered /health but nothing is listening on 8000 - refusing to write a pidfile"
}
Write-Ok "Listening on 127.0.0.1:8000 (PID $listenerPid, recorded in .uvicorn.pid)"

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
