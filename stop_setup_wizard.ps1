param(
  [string]$Python = "python",
  [int]$Port = 8095
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Stop-SetupWizardListener {
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
      if ($cmd -and $cmd -notmatch "setup_wizard_app\.py") {
        continue
      }
      Write-Host "Stopping setup wizard on port $ListenPort (PID $pidValue)"
      Stop-Process -Id $pidValue -Force -ErrorAction Stop
      Start-Sleep -Milliseconds 500
    } catch {
      Write-Warning "Could not stop setup wizard PID ${pidValue}: $($_.Exception.Message)"
    }
  }
}

Write-Host "Stopping GotChat services started by the setup wizard..."
& $Python (Join-Path $Root "setup_wizard_app.py") "--stop-services"
Stop-SetupWizardListener -ListenPort $Port
Write-Host "Done."
