param(
  [ValidateSet("start", "stop", "restart", "status", "foreground")]
  [string]$Action = "start",
  [int]$Port = 8767,
  [string]$Bind = "127.0.0.1",
  [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $PSScriptRoot "host_service.pid"
$LogFile = Join-Path $PSScriptRoot "host_service.log"
$ErrLogFile = Join-Path $PSScriptRoot "host_service.err.log"
$ScriptPath = Join-Path $PSScriptRoot "host_service.py"

function Get-DefaultHostServicePythonCandidates {
  $parentRoot = Split-Path -Parent $Root
  return @(
    (Join-Path $Root ".venv\Scripts\python.exe"),
    (Join-Path $Root "venv\Scripts\python.exe"),
    (Join-Path $parentRoot ".venv\Scripts\python.exe"),
    (Join-Path $parentRoot "venv\Scripts\python.exe"),
    (Join-Path $Root ".venv/bin/python"),
    (Join-Path $Root "venv/bin/python"),
    (Join-Path $parentRoot ".venv/bin/python"),
    (Join-Path $parentRoot "venv/bin/python")
  )
}

function Test-PythonHasModule {
  param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string]$ModuleName
  )
  try {
    $null = & $PythonExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$ModuleName') else 1)" 2>$null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

function Resolve-HostServicePython {
  $requested = [string]$Python
  $isDefaultRequest = [string]::IsNullOrWhiteSpace($requested) -or $requested -eq "python"
  if (-not $isDefaultRequest) {
    return $requested
  }
  foreach ($candidate in Get-DefaultHostServicePythonCandidates) {
    if (-not $candidate) { continue }
    if (-not (Test-Path $candidate)) { continue }
    if (Test-PythonHasModule -PythonExe $candidate -ModuleName "huggingface_hub") {
      return $candidate
    }
  }
  return "python"
}

function Test-HostServiceHealth {
  try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://$Bind`:$Port/health" -TimeoutSec 3
    return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300)
  } catch {
    return $false
  }
}

function Get-HostServiceListenerPids {
  $pids = @()
  try {
    $lines = netstat -ano -p tcp | Select-String ":$Port"
    foreach ($match in $lines) {
      $line = ([string]$match.Line -replace '^\s+', '').Trim()
      $parts = $line -split "\s+"
      if ($parts.Count -lt 5) { continue }
      if ([string]$parts[3] -ne "LISTENING") { continue }
      $pidText = $parts[-1]
      $foundPid = 0
      if ([int]::TryParse($pidText, [ref]$foundPid) -and $foundPid -gt 0) {
        if ($pids -notcontains $foundPid) {
          $pids += $foundPid
        }
      }
    }
  } catch {}
  return $pids
}

function Get-HostServiceProcess {
  if (-not (Test-Path $PidFile)) { return $null }
  try {
    $savedPid = [int](Get-Content $PidFile -ErrorAction Stop | Select-Object -First 1)
    $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
    if ($proc) { return $proc }
  } catch {}
  try {
    $escaped = [Regex]::Escape($ScriptPath)
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
      $_.Name -match '^python(\.exe)?$' -and $_.CommandLine -match $escaped
    }
    $match = $procs | Sort-Object CreationDate -Descending | Select-Object -First 1
    if ($match) {
      $proc = Get-Process -Id ([int]$match.ProcessId) -ErrorAction SilentlyContinue
      if ($proc) {
        try { Set-Content -LiteralPath $PidFile -Value $proc.Id -Force } catch {}
        return $proc
      }
    }
  } catch {}
  return $null
}

function Remove-StalePid {
  if ((Test-Path $PidFile) -and -not (Get-HostServiceProcess)) {
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
  }
}

function Start-HostService {
  $ResolvedPython = Resolve-HostServicePython
  $existing = Get-HostServiceProcess
  if ($existing) {
    if (Test-HostServiceHealth) {
      Write-Host "llama host service already running (PID $($existing.Id))"
      return
    }
    Write-Warning "llama host service process $($existing.Id) is present but not healthy; restarting it"
    Stop-Process -Id $existing.Id -Force -ErrorAction SilentlyContinue
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
  }
  $listeners = @(Get-HostServiceListenerPids)
  if ($listeners.Count -gt 0) {
    throw "Port $Port is already in use by PID(s): $($listeners -join ', '). Run stop or restart first."
  }
  $LauncherPath = Join-Path $PSScriptRoot "host_service_launcher.py"
  $launcherArgs = @(
    $LauncherPath,
    "--python", $ResolvedPython,
    "--script", $ScriptPath,
    "--root", $Root,
    "--pid-file", $PidFile,
    "--stdout", $LogFile,
    "--stderr", $ErrLogFile,
    "--bind", $Bind,
    "--port", "$Port"
  )
  & $ResolvedPython @launcherArgs | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "failed to launch llama host service; check $LogFile and $ErrLogFile"
  }
  Start-Sleep -Seconds 1
  $launchedPid = ""
  try {
    if (Test-Path $PidFile) {
      $launchedPid = [string](Get-Content $PidFile -ErrorAction Stop | Select-Object -First 1)
    }
  } catch {
    $launchedPid = ""
  }
  if (-not (Test-HostServiceHealth)) {
    throw "llama host service exited during startup; check $LogFile and $ErrLogFile"
  }
  if ($launchedPid) {
    Write-Host "llama host service started on http://$Bind`:$Port (PID $launchedPid, python $ResolvedPython)"
  } else {
    Write-Host "llama host service started on http://$Bind`:$Port (python $ResolvedPython)"
  }
}

function Stop-HostService {
  $targets = @()
  $existing = Get-HostServiceProcess
  if ($existing) {
    $targets += $existing.Id
  }
  $listeners = @(Get-HostServiceListenerPids)
  foreach ($targetPid in $listeners) {
    if ($targets -notcontains $targetPid) {
      $targets += $targetPid
    }
  }
  if ($targets.Count -eq 0) {
    Remove-StalePid
    Write-Host "llama host service is not running"
    return
  }
  foreach ($targetPid in $targets) {
    Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
  }
  Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
  Write-Host "llama host service stopped (PID(s): $($targets -join ', '))"
}

function Wait-HostServiceStopped {
  param([int]$TimeoutSec = 10)
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    $listeners = @(Get-HostServiceListenerPids)
    if ($listeners.Count -eq 0) {
      return $true
    }
    Start-Sleep -Milliseconds 250
  }
  return $false
}

function Restart-HostService {
  Write-Host "restarting llama host service on http://$Bind`:$Port"
  Stop-HostService
  if (-not (Wait-HostServiceStopped -TimeoutSec 10)) {
    $listeners = @(Get-HostServiceListenerPids)
    throw "Port $Port is still in use after stop (PID(s): $($listeners -join ', '))"
  }
  Write-Host "starting llama host service..."
  Start-HostService
}

function Show-Status {
  $existing = Get-HostServiceProcess
  $listeners = @(Get-HostServiceListenerPids)
  if ($existing) {
    Write-Host "running pid=$($existing.Id) listeners=$($listeners -join ',') url=http://$Bind`:$Port"
  } elseif (Test-HostServiceHealth) {
    Write-Host "running listeners=$($listeners -join ',') url=http://$Bind`:$Port"
  } else {
    Remove-StalePid
    Write-Host "stopped"
  }
}

switch ($Action) {
  "start" { Start-HostService }
  "stop" { Stop-HostService }
  "restart" { Restart-HostService }
  "status" { Show-Status }
  "foreground" {
    $ResolvedPython = Resolve-HostServicePython
    $env:LLMLOADER2_LLAMA_MANAGER_BIND = $Bind
    $env:LLMLOADER2_LLAMA_MANAGER_PORT = "$Port"
    $env:LLMLOADER2_LLAMA_MANAGER_ROOT = $Root
    if (-not $env:LLMLOADER2_AUTH_ME_URL) {
      $env:LLMLOADER2_AUTH_ME_URL = "http://localhost:8000/v1/auth/me"
    }
    & $ResolvedPython -u $ScriptPath
  }
}
