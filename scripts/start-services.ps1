#Requires -Version 5.1
<#
.SYNOPSIS
  Start the data services (postgres, minio) and bring the schema to head.
.DESCRIPTION
  The data layer, on its own. Nothing here knows about the API or the UI, and
  neither of those starts a container: a designer restarting the backend after a
  code change should not be waiting on Docker, and `docker compose up` on every
  backend start is what made that the normal experience.

  Migrations live here rather than with the backend because they are a property
  of the database, not of the process that talks to it - two API processes
  against one database must not each try to move the schema. `start-backend.ps1`
  checks the revision and refuses to run against a stale one, which is the half
  of this that belongs over there.
.PARAMETER SkipMigrations
  Start the containers only. For a deliberate downgrade or a hand-run migration.
#>
param([switch]$SkipMigrations)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# docker-compose.yml and alembic.ini are both read relative to the repo root.
Set-Location "$PSScriptRoot\.."

function Write-Step { param([string]$msg) Write-Host ">> $msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$msg) Write-Host "   OK: $msg" -ForegroundColor Green }
function Write-Fail { param([string]$msg) Write-Host "   FAIL: $msg" -ForegroundColor Red; exit 1 }

# --- 1. Containers ---
Write-Step "Starting data services (postgres, minio)..."
docker compose up -d --remove-orphans
if ($LASTEXITCODE -ne 0) {
    Write-Fail ("docker compose up failed. Is Docker Desktop running? " +
        "The containers are the only thing this script starts.")
}
Write-Ok "Containers up"

# --- 2. Postgres actually accepting connections ---
# The container being "up" and postgres being ready are seconds apart, and a
# migration fired into that gap fails with a connection error that reads like a
# bad DSN.
Write-Step "Waiting for postgres..."
$timeout = 30
$elapsed = 0
while ($elapsed -lt $timeout) {
    # 2>$null, not 2>&1: under $ErrorActionPreference = "Stop", merging a native
    # command's stderr into the success stream can raise a terminating
    # NativeCommandError on a clean "not ready yet" exit.
    $null = docker exec ca-postgres pg_isready -U curriculum -d curriculum_agent 2>$null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 1
    $elapsed++
}
if ($elapsed -ge $timeout) { Write-Fail "Postgres not ready after ${timeout}s" }
Write-Ok "Postgres ready"

# --- 3. Schema ---
if ($SkipMigrations) {
    Write-Step "Skipping migrations (-SkipMigrations)"
} else {
    Write-Step "Running Alembic migrations..."
    uv run alembic upgrade head
    if ($LASTEXITCODE -ne 0) { Write-Fail "Migration failed" }
    Write-Ok "Schema at head"
}

Write-Host ""
Write-Host "=== Data services ready ===" -ForegroundColor Yellow
Write-Host "  Postgres:      127.0.0.1:5432"
Write-Host "  MinIO console: http://localhost:9001"
Write-Host ""
Write-Host "  Next: .\scripts\start-backend.ps1   then   .\scripts\start-frontend.ps1"
Write-Host "  Stop: .\scripts\stop-services.ps1   (data survives; it lives in named volumes)"
