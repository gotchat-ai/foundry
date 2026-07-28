param(
  [string]$Python = "python",
  [int]$Port = 8095,
  [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Stop-ExistingSetupWizard {
  param([int]$ListenPort)
  try {
    $listeners = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue
  } catch {
    $listeners = @()
  }
  foreach ($listener in @($listeners)) {
    $pidValue = [int]($listener.OwningProcess)
    if (-not $pidValue -or $pidValue -eq $PID) {
      continue
    }
    try {
      $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $pidValue" -ErrorAction Stop
      $cmd = [string]($proc.CommandLine)
      if ($cmd -notmatch "setup_wizard_app\.py") {
        Write-Warning "Port $ListenPort is in use by PID $pidValue, but it does not look like the setup wizard. Leaving it running."
        continue
      }
      Write-Host "Stopping stale setup wizard on port $ListenPort (PID $pidValue)"
      Stop-Process -Id $pidValue -Force -ErrorAction Stop
      Start-Sleep -Milliseconds 500
    } catch {
      Write-Warning "Could not stop stale setup wizard PID ${pidValue}: $($_.Exception.Message)"
    }
  }
}

Stop-ExistingSetupWizard -ListenPort $Port

$ArgsList = @((Join-Path $Root "setup_wizard_app.py"), "--port", "$Port")
if ($NoOpen) {
  $ArgsList += "--no-open"
}

& $Python @ArgsList
