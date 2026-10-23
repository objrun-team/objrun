param([Parameter(Mandatory=$true)][int]$BuildPid)
$ErrorActionPreference = 'Stop'
$skbRoot = 'F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$skbHome = Join-Path $skbRoot 'docs\repair-2026-10-10\full-f-rerun\skillsbench'
$skbProcess = Get-Process -Id $BuildPid -ErrorAction SilentlyContinue
if ($null -ne $skbProcess) { Wait-Process -Id $BuildPid }
$skbStatus = Get-Content -LiteralPath (Join-Path $skbHome 'status.json') -Raw | ConvertFrom-Json
if ($skbStatus.environmentPreparation.pid -ne $BuildPid -or $skbStatus.environmentPreparation.stage -ne 'images_built_cold_controls_pending') { exit 2 }
$skbPointer = Join-Path $skbHome 'environment-preparation\3d-scan-calc\latest.json'
if (-not (Test-Path -LiteralPath $skbPointer)) { exit 2 }
Set-Location -LiteralPath $skbRoot
$skbBunExe = (bun -e 'console.log(process.execPath)').Trim()
$skbControl = Start-Process -FilePath $skbBunExe -ArgumentList @('scripts/repair-2026-10-10/full-f/skillsbench/prepare_environment.ts','3d-scan-calc','--controls-only') -WorkingDirectory $skbRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $skbHome 'controls-worker.stdout.log') -RedirectStandardError (Join-Path $skbHome 'controls-worker.stderr.log') -PassThru
@{protocol='skillsbench-preparation-background-process-v1';pid=$skbControl.Id;role='zero-model-original-grader-controls';taskId='3d-scan-calc';startedAtUtc=[DateTime]::UtcNow.ToString('o');modelCalls=0} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $skbHome 'controls-worker-process.json')
Wait-Process -Id $skbControl.Id
