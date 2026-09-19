#Requires -Version 5.1
<#
.SYNOPSIS
  Start the React dev server (Vite) on http://localhost:5173.
.DESCRIPTION
  Runs in the foreground and stays there - the watcher is the point, and Ctrl+C
  is how it stops. That is why there is no stop-frontend.ps1.

  It does not start the backend. The UI loads and renders without one; every page
  then reports the API as unreachable, which is a clearer failure than a UI that
  will not come up at all.
.PARAMETER Install
  Run npm install first. Needed on a fresh clone, or after dependencies change.
#>
param([switch]$Install)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\..\frontend"

function Write-Step { param([string]$msg) Write-Host ">> $msg" -ForegroundColor Cyan }

if ($Install -or -not (Test-Path "node_modules")) {
    Write-Step "Installing npm dependencies..."
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   FAIL: npm install failed" -ForegroundColor Red
        exit 1
    }
}

# Said before Vite takes over the terminal: once the dev server is running its
# own output is all that is visible, and a backend that is down then shows up
# only as failed requests in the browser console.
$apiUp = $false
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2 -UseBasicParsing
    $apiUp = ($resp.StatusCode -eq 200)
} catch {
    $apiUp = $false
}
if (-not $apiUp) {
    Write-Host ("   NOTE: nothing is answering on http://127.0.0.1:8000 - the UI will load " +
        "but every page will report the API as unreachable. Start it with " +
        ".\scripts\start-backend.ps1") -ForegroundColor Yellow
}

Write-Step "Starting Vite on http://localhost:5173 (Ctrl+C to stop)..."
npm run dev
