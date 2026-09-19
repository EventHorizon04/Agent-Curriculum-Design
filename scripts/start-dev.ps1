#Requires -Version 5.1
<#
.SYNOPSIS
  Start data services and the backend in one go. Convenience wrapper.
.DESCRIPTION
  Exactly start-services.ps1 followed by start-backend.ps1, in that order and
  with nothing of its own. Use the two directly when only one of them needs to
  move - a backend restart after a code change is the common case, and it has no
  business waiting on Docker.

  The UI is not started here. Vite runs in the foreground and holds the
  terminal, so it gets its own script and its own window:
  .\scripts\start-frontend.ps1
.PARAMETER Port
  Port for the API. Default 8000.
#>
param([int]$Port = 8000)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\.."

& "$PSScriptRoot\start-services.ps1"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& "$PSScriptRoot\start-backend.ps1" -Port $Port
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "  UI (separate terminal): .\scripts\start-frontend.ps1  ->  http://localhost:5173" -ForegroundColor Yellow
Write-Host "  Stop everything:        .\scripts\stop-dev.ps1"
