param(
  [string]$GpuName = "",
  [int]$PartitionCount = 2,
  [switch]$Reset,
  [switch]$ListOnly
)

$ErrorActionPreference = 'Stop'
Import-Module Hyper-V -ErrorAction Stop

$statePath = Join-Path $PSScriptRoot '.gpu_partition_state.json'
$gpus = Get-VMHostPartitionableGpu
if (-not $gpus) {
  throw 'No partitionable GPUs were found. Ensure Hyper-V GPU partitioning is supported and the driver exposes a partitionable GPU.'
}

if ($ListOnly) {
  $gpus | Select-Object Name, @{n='ValidPartitionCounts';e={$_.ValidPartitionCounts -join ','}}, PartitionCount | Format-Table -AutoSize
  return
}

$gpu = $null
if ($GpuName) {
  $gpu = $gpus | Where-Object { $_.Name -like "*$GpuName*" } | Select-Object -First 1
  if (-not $gpu) {
    throw "No partitionable GPU matched '$GpuName'."
  }
} elseif ($gpus.Count -eq 1) {
  $gpu = $gpus[0]
} else {
  throw 'Multiple partitionable GPUs found. Re-run with -GpuName and use -ListOnly first.'
}

$valid = @($gpu.ValidPartitionCounts | ForEach-Object { [int]$_ })
if (-not $valid.Count) {
  throw 'The selected GPU did not report any valid partition counts.'
}

if ($Reset) {
  if (Test-Path $statePath) {
    $saved = Get-Content $statePath -Raw | ConvertFrom-Json
    if ($saved.Name -eq $gpu.Name -and $saved.OriginalPartitionCount) {
      $PartitionCount = [int]$saved.OriginalPartitionCount
    }
  }
  if (-not $PartitionCount) {
    $PartitionCount = ($valid | Measure-Object -Maximum).Maximum
  }
}

if ($valid -notcontains $PartitionCount) {
  throw "PartitionCount $PartitionCount is not valid for '$($gpu.Name)'. Valid counts: $($valid -join ', ')"
}

$original = [pscustomobject]@{
  Name = $gpu.Name
  OriginalPartitionCount = [int]$gpu.PartitionCount
  SavedAt = (Get-Date).ToString('s')
}
$original | ConvertTo-Json | Set-Content -Path $statePath -Encoding UTF8

Set-VMHostPartitionableGpu -Name $gpu.Name -PartitionCount $PartitionCount
$updated = Get-VMHostPartitionableGpu | Where-Object { $_.Name -eq $gpu.Name } | Select-Object -First 1
$updated | Select-Object Name, @{n='ValidPartitionCounts';e={$_.ValidPartitionCounts -join ','}}, PartitionCount | Format-Table -AutoSize
