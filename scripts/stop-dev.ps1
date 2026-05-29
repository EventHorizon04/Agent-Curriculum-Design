#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

function Write-Step { param([string]$msg) Write-Host ">> $msg" -ForegroundColor Cyan }

# --- 1. Kill uvicorn ---
Write-Step "Stopping uvicorn..."
if (Test-Path ".uvicorn.pid") {
    $savedPid = [int](Get-Content ".uvicorn.pid" -Raw).Trim()
    try {
        Stop-Process -Id $savedPid -Force -ErrorAction Stop
        Write-Host "   Stopped PID $savedPid" -ForegroundColor Green
    } catch {
        Write-Host "   PID $savedPid not found (already stopped)" -ForegroundColor Yellow
    }
    Remove-Item ".uvicorn.pid" -Force
} else {
    Write-Host "   No .uvicorn.pid found — stopping by name"
    Get-Process -Name "uvicorn" -ErrorAction SilentlyContinue | Stop-Process -Force
}

# --- 2. Docker compose down ---
Write-Step "Stopping Docker services..."
docker compose down
Write-Host "   Done." -ForegroundColor Green
