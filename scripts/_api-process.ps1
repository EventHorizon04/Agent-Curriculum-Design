#Requires -Version 5.1
<#
.SYNOPSIS
  Shared helpers for finding, stopping, and recording the API process.
.DESCRIPTION
  Dot-sourced by start-dev.ps1, start-demo.ps1 and stop-dev.ps1. Three facts about
  how the API runs on Windows drive everything in here:

    1. `Start-Process uv` hands back the pid of uv.exe, but the process that
       actually binds the port is its grandchild (uv -> .venv python -> python).
       A pidfile holding the uv pid cannot stop the listener, and the port stays
       taken after a "successful" stop.
    2. All three processes carry "curriculum_agent.api" in their command line, so
       discovery by command line finds the whole tree without walking parents.
    3. A start that loses the race for the port dies seconds later. Writing the
       pidfile before the API is known to answer overwrites a good pid with a dead
       one, and every later stop then silently does nothing.

  Nothing here ever kills a process it has not identified as this project's API.
#>

# uv.exe and both python.exe layers all carry this in their command line.
$script:ApiCommandMatch = '*curriculum_agent.api*'
$script:ApiPidFile = Join-Path (Split-Path -Parent $PSScriptRoot) ".uvicorn.pid"


function Get-ApiProcess {
    <#
    .SYNOPSIS Every process in this project's API tree, or nothing.
    .DESCRIPTION
      Command-line discovery finds the uv wrapper and both python layers, but not
      a reload worker: uvicorn spawns it through multiprocessing, so its command
      line reads `-c "from multiprocessing.spawn import spawn_main; ..."` with no
      mention of this project at all. Stopping the tree by name alone therefore
      killed the reloader and left the worker holding port 8000 while /health went
      on answering 200 — and API_RELOAD is on in every dev start, so that was the
      normal case, not an edge one.

      So the named processes are the seeds, and their descendants come with them.
      Parentage is read from the same CIM snapshot the seeds came from, which is
      what makes a worker whose parent is about to be killed still reachable.
    #>
    $all = @(Get-CimInstance Win32_Process -Filter "Name like '%python%' or Name like '%uv.exe%'")
    $tree = @($all | Where-Object { $_.CommandLine -like $script:ApiCommandMatch })
    if ($tree.Count -eq 0) { return @() }

    # Walk down until no new children appear. Bounded by the snapshot, so it
    # cannot loop forever on a pid that gets reused mid-sweep.
    $growing = $true
    while ($growing) {
        $growing = $false
        $known = @($tree | ForEach-Object { $_.ProcessId })
        foreach ($proc in $all) {
            if ($known -contains $proc.ProcessId) { continue }
            if ($known -contains $proc.ParentProcessId) {
                $tree += $proc
                $growing = $true
            }
        }
    }
    return $tree
}


function Get-PortOwnerPid {
    <#.SYNOPSIS The pid listening on $Port, or $null.#>
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conn) { return [int](@($conn)[0].OwningProcess) }
    return $null
}


function Wait-PortFree {
    <#.SYNOPSIS Poll until nothing listens on $Port. Returns $true if it came free.#>
    param([int]$Port, [int]$TimeoutSeconds = 10)
    $elapsed = 0
    while ($elapsed -lt $TimeoutSeconds) {
        if ($null -eq (Get-PortOwnerPid -Port $Port)) { return $true }
        Start-Sleep -Milliseconds 500
        $elapsed = $elapsed + 0.5
    }
    return ($null -eq (Get-PortOwnerPid -Port $Port))
}


function Stop-ApiProcess {
    <#
    .SYNOPSIS Stop every process in this project's API tree and clear the pidfile.
    .DESCRIPTION
      Kills by command-line discovery rather than by the recorded pid: the pidfile
      may name a process that never bound, or one layer of a three-process tree.
      The recorded pid is still tried, in case a run predates this script.
      Returns $true when the port is free afterwards.
    #>
    param([int]$Port = 8000, [int]$TimeoutSeconds = 10)

    $targets = @(Get-ApiProcess)
    if ($targets.Count -gt 0) {
        foreach ($p in $targets) {
            Write-Host "   Stopping PID $($p.ProcessId) ($($p.Name))" -ForegroundColor Yellow
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "   No running API process found" -ForegroundColor Yellow
    }

    # The pidfile is a hint, not the source of truth. A pid recorded by an older
    # version of these scripts is the uv wrapper, which discovery above already
    # covered; this only catches a tree that has drifted from the name filter.
    if (Test-Path $script:ApiPidFile) {
        # -Raw returns $null for a file that exists but is empty (a start killed
        # mid-write leaves one), and .Trim() on $null is a terminating error under
        # Set-StrictMode - the same failure shape as the port-owner lookup below.
        $recorded = Get-Content $script:ApiPidFile -Raw -ErrorAction SilentlyContinue
        $recorded = if ($null -eq $recorded) { '' } else { $recorded.Trim() }
        if ($recorded -match '^\d+$') {
            $recordedPid = [int]$recorded
            if ($targets.ProcessId -notcontains $recordedPid) {
                Stop-Process -Id $recordedPid -Force -ErrorAction SilentlyContinue
            }
        }
        Remove-Item $script:ApiPidFile -Force -ErrorAction SilentlyContinue
    }

    if (Wait-PortFree -Port $Port -TimeoutSeconds $TimeoutSeconds) { return $true }

    # Still held. Ask the port whether what holds it is this project's API: an
    # orphaned worker whose parent died in an earlier stop is no longer reachable
    # by parentage, and nothing else would ever free it. /health answering with
    # this API's payload is the identification — the same evidence Clear-PortForApi
    # trusts — and without it nothing is killed, because "something is on my port"
    # is not a reason to terminate a stranger's process.
    $owner = Get-PortOwnerPid -Port $Port
    if ($null -eq $owner) { return $true }
    try {
        $health = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" `
            -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        $isOurApi = ($health.Content -like '*"status"*"ok"*')
    }
    catch { $isOurApi = $false }

    if (-not $isOurApi) { return $false }

    Write-Host ("   Stopping PID $owner - orphaned API worker still serving on " +
        "$Port") -ForegroundColor Yellow
    Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
    return (Wait-PortFree -Port $Port -TimeoutSeconds $TimeoutSeconds)
}


function Clear-PortForApi {
    <#
    .SYNOPSIS Make $Port available, or stop the script with a message that says why.
    .DESCRIPTION
      Frees the port only when this project's API is what holds it. Anything else
      on 8000 belongs to someone else and is reported, never killed  - that is the
      difference between "restart my API" and "terminate whatever is in my way".
    #>
    param([int]$Port = 8000)

    $owner = Get-PortOwnerPid -Port $Port
    if ($null -eq $owner) { return $true }

    $ours = @(Get-ApiProcess) | Where-Object { $_.ProcessId -eq $owner }
    if (-not $ours) {
        # Two different situations reach here, and they need different advice.
        #
        # Get-ApiProcess asks CIM, so a process CIM cannot see is never "ours"
        # however plainly it is this project's API — a run started from an
        # elevated shell or another user's session is invisible to both CIM and
        # Get-Process from here, which is also why reading .ProcessName off the
        # result used to end the script with a PropertyNotFoundStrict error under
        # Set-StrictMode instead of printing this message at all.
        #
        # So ask the port itself. If /health answers with this API's payload, the
        # port is held by a run of this project that this shell merely cannot
        # query, and saying "not this project's API" would be a lie that sends the
        # designer looking for the wrong process.
        $proc = Get-Process -Id $owner -ErrorAction SilentlyContinue
        $name = if ($null -eq $proc) { 'name unreadable from this shell' } else { $proc.ProcessName }

        $isOurApi = $false
        try {
            $health = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" `
                -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
            $isOurApi = ($health.Content -like '*"status"*"ok"*')
        }
        catch { $isOurApi = $false }

        if ($isOurApi) {
            Write-Host ("   FAIL: port $Port already serves this project's API (PID $owner, " +
                "$name), but this shell cannot stop it - the process was started somewhere " +
                "this one cannot see (an elevated shell, or another user's session). Stop it " +
                "where it was started, or from an elevated shell run " +
                "``Stop-Process -Id $owner -Force``.") -ForegroundColor Red
        }
        else {
            Write-Host ("   FAIL: port $Port is held by PID $owner ($name), which is not " +
                "this project's API. Free the port yourself; this script will not kill a " +
                "process it does not own. Inspect it with " +
                "``Get-NetTCPConnection -LocalPort $Port``.") -ForegroundColor Red
        }
        exit 1
    }

    Write-Host "   Port $Port held by a previous API run (PID $owner) - stopping it" -ForegroundColor Yellow
    if (-not (Stop-ApiProcess -Port $Port)) {
        Write-Host ("   FAIL: port $Port is still in use after stopping the previous " +
            "run. Something is holding the socket; check with " +
            "``Get-NetTCPConnection -LocalPort $Port``.") -ForegroundColor Red
        exit 1
    }
    return $true
}


function Save-ApiPid {
    <#
    .SYNOPSIS Record the pid that actually listens on $Port.
    .DESCRIPTION
      Called only after /health answers, and it records the port's owner rather
      than the pid Start-Process returned  - those are different processes, and
      only the former can be stopped to free the port. ASCII, no BOM: the file
      holds digits and is read back with a plain [int] cast.
    #>
    param([int]$Port = 8000)
    $listener = Get-PortOwnerPid -Port $Port
    if ($null -eq $listener) { return $null }
    Set-Content -Path $script:ApiPidFile -Value $listener -Encoding ascii
    return $listener
}


function Wait-ApiHealthy {
    <#.SYNOPSIS Poll /health. Returns $true once it answers 200.#>
    param([int]$Port = 8000, [int]$TimeoutSeconds = 15)
    $elapsed = 0
    while ($elapsed -lt $TimeoutSeconds) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) { return $true }
        } catch {
            # Connection refused until the process finishes starting, or forever
            # if it has already died. The caller reports the difference.
        }
        Start-Sleep -Seconds 1
        $elapsed++
    }
    return $false
}
