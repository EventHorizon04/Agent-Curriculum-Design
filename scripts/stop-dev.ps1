#Requires -Version 5.1
<#
.SYNOPSIS
  Stop the API and the Docker DB services.
.PARAMETER KeepServices
  Stop the API only and leave postgres/minio/pgadmin running. Use this to restart
  the API after a code change without waiting for the database to come back.
#>
param([switch]$KeepServices)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

Set-Location "$PSScriptRoot\.."

# Process discovery and the pidfile contract  - see the file header for why the
# recorded pid alone cannot stop the listener.
. "$PSScriptRoot\_api-process.ps1"

function Write-Step { param([string]$msg) Write-Host ">> $msg" -ForegroundColor Cyan }

# --- 1. Stop the API ---
# By command-line discovery, not by the recorded pid alone: `uv run python -m
# curriculum_agent.api` is a three-process tree and the socket belongs to the
# grandchild, so stopping the recorded pid used to leave port 8000 bound and the
# next start failing with Errno 10048. Stop-ApiProcess also clears the pidfile.
Write-Step "Stopping the API..."
if (Stop-ApiProcess -Port 8000) {
    Write-Host "   Port 8000 is free" -ForegroundColor Green
} else {
    $owner = Get-PortOwnerPid -Port 8000
    Write-Host ("   WARNING: port 8000 is still held by PID $owner. It is not part " +
        "of this project's API tree  - check it before starting again.") -ForegroundColor Yellow
}

# --- 2. Stop Docker services ---
if ($KeepServices) {
    Write-Step "Leaving Docker services running (-KeepServices)"
    Write-Host "   Restart the API with .\scripts\start-demo.ps1 or .\scripts\start-dev.ps1"
    exit 0
}

# --profile debug, not a bare `down`: pgadmin is declared under that profile in
# docker-compose.yml, so a plain `docker compose down` leaves it running, and the
# network it is still attached to cannot be removed  - "Resource is still in use".
Write-Step "Stopping Docker services..."
docker compose --profile debug down
Write-Host "   Done." -ForegroundColor Green
