#Requires -Version 5.1
<#
.SYNOPSIS
  Stop the backend and the data services. Convenience wrapper.
.DESCRIPTION
  stop-backend.ps1 then stop-services.ps1, in that order - the API has to let go
  of the database before the database goes away, or it spends its last seconds
  answering 500s.

  Named volumes are untouched: containers are removed, the data stays. Use the
  two scripts directly when only one layer should stop.
.PARAMETER KeepServices
  Stop the API only and leave postgres/minio running. The usual choice while
  working: restarting the backend after a code change should not cost a database
  restart.
.PARAMETER Port
  Port the API is expected on. Default 8000.
#>
param([switch]$KeepServices, [int]$Port = 8000)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

Set-Location "$PSScriptRoot\.."

& "$PSScriptRoot\stop-backend.ps1" -Port $Port
$apiStopped = ($LASTEXITCODE -eq 0)

if ($KeepServices) {
    Write-Host ">> Leaving data services running (-KeepServices)" -ForegroundColor Cyan
    Write-Host "   Restart the backend with .\scripts\start-backend.ps1"
    exit 0
}

if (-not $apiStopped) {
    # Something still holds the port and did not answer as this API. Stopping
    # postgres now would take the database out from under whatever that is,
    # which is a worse state than leaving both running for someone to look at.
    Write-Host ("   Not stopping the data services while port $Port is still held. " +
        "Deal with that process first, or run .\scripts\stop-services.ps1 -Force.") -ForegroundColor Yellow
    exit 1
}

& "$PSScriptRoot\stop-services.ps1"
exit $LASTEXITCODE
