#Requires -Version 5.1
<#
.SYNOPSIS
  Stop the data services (postgres, minio).
.DESCRIPTION
  Containers only - the API is a separate process and a separate script.
  Stopping the database under a running API leaves it answering 500s rather than
  stopping, so this refuses while one is listening unless -Force says otherwise.

  Named volumes are never touched. docker compose down removes the containers
  and the network; the data lives in postgres-data and minio-data and survives
  every stop. Erasing those is docker compose down -v, which this script
  deliberately does not offer: there is no undo, and nobody reaches for a stop
  script meaning to delete a program's evidence.
.PARAMETER Force
  Stop the containers even though the API is still listening.
#>
param([switch]$Force)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\.."
. "$PSScriptRoot\_api-process.ps1"

$apiPid = Get-PortOwnerPid -Port 8000
if ($null -ne $apiPid -and -not $Force) {
    Write-Host ("   The API is still listening on 8000 (PID $apiPid). Stopping postgres " +
        "underneath it leaves it answering 500s.") -ForegroundColor Yellow
    Write-Host "   Run .\scripts\stop-backend.ps1 first, or pass -Force." -ForegroundColor Yellow
    exit 1
}

Write-Host ">> Stopping data services..." -ForegroundColor Cyan
docker compose down
if ($LASTEXITCODE -ne 0) {
    Write-Host "   docker compose down reported an error - inspect with: docker ps -a" -ForegroundColor Yellow
    exit 1
}
Write-Host "   Containers removed. Named volumes (and every program in them) kept." -ForegroundColor Green
