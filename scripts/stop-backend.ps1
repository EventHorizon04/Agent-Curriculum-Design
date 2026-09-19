#Requires -Version 5.1
<#
.SYNOPSIS
  Stop the FastAPI backend. Leaves the data services running.
.PARAMETER Port
  Port the API is expected on. Default 8000.
#>
param([int]$Port = 8000)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

Set-Location "$PSScriptRoot\.."

# Process discovery and the pidfile contract - see the file header for why the
# recorded pid alone cannot stop the listener, and why a reload worker has to be
# found by parentage rather than by command line.
. "$PSScriptRoot\_api-process.ps1"

Write-Host ">> Stopping the API..." -ForegroundColor Cyan
if (Stop-ApiProcess -Port $Port) {
    Write-Host "   Port $Port is free" -ForegroundColor Green
    exit 0
}

$owner = Get-PortOwnerPid -Port $Port
Write-Host ("   WARNING: port $Port is still held by PID $owner, which does not answer " +
    "as this project's API - check it before starting again.") -ForegroundColor Yellow
exit 1
