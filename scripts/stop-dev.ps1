#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

function Write-Step { param([string]$msg) Write-Host ">> $msg" -ForegroundColor Cyan }

# Resolve project root (one level up from scripts/)
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

# --- 1. Kill uvicorn ---
Write-Step "Stopping uvicorn..."
$pidFile = Join-Path $ProjectRoot ".uvicorn.pid"
if (Test-Path $pidFile) {
    $savedPid = [int](Get-Content $pidFile -Raw).Trim()
    try {
        Stop-Process -Id $savedPid -Force -ErrorAction Stop
        Write-Host "   Stopped PID $savedPid" -ForegroundColor Green
    } catch {
        Write-Host "   PID $savedPid not found (already stopped)" -ForegroundColor Yellow
    }
    Remove-Item $pidFile -Force
} else {
    Write-Host "   No .uvicorn.pid found - stopping by name"
    Get-Process -Name "uvicorn" -ErrorAction SilentlyContinue | Stop-Process -Force
}

# --- 2. Docker compose down ---
Write-Step "Stopping Docker services..."
docker compose down
Write-Host "   Done." -ForegroundColor Green
