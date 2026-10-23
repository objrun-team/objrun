$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskOut=Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/chemiq'
$taskUntil=[DateTime]::UtcNow.AddMinutes(10)
while(!(Test-Path (Join-Path $taskOut 'safe-stop.json')) -and [DateTime]::UtcNow -lt $taskUntil){Start-Sleep -Seconds 5}
if(!(Test-Path (Join-Path $taskOut 'safe-stop.json'))){throw 'Drain stop not completed; leave all financial evidence unchanged'}
$taskActive=Get-Content -LiteralPath (Join-Path $taskOut 'active-run.json') -Raw|ConvertFrom-Json
$taskState=Get-Content -LiteralPath (Join-Path $taskActive.output 'journal/api-state.json') -Raw|ConvertFrom-Json
if($taskState.reservedUpperBoundUsd -ne 0 -or $taskState.acceptedRequestCount -ne $taskState.finishedRequestCount){throw 'Paid journal must stay drained'}
foreach($taskDirectory in Get-ChildItem -LiteralPath $taskActive.output -Directory|Where-Object Name -Match '^task-\d+$'){
 $taskRegistration=Join-Path $taskDirectory.FullName 'process.json'
 if(!(Test-Path $taskRegistration)){continue}
 $taskRegistered=Get-Content -LiteralPath $taskRegistration -Raw|ConvertFrom-Json
 $taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskRegistered.pid)"
 if(!$taskProcess){continue}
 $taskAge=[Math]::Abs(($taskProcess.CreationDate.ToUniversalTime()-[DateTime]::Parse($taskRegistered.startedAtUtc).ToUniversalTime()).TotalSeconds)
 if($taskProcess.CommandLine -notlike '*app*src*main.ts*' -or $taskAge -gt 10){throw 'Child process identity mismatch; do not stop unrelated PID'}
 Stop-Process -Id $taskRegistered.pid
}
Set-Location -LiteralPath $taskRoot
& bun scripts/benchmark-campaign/full-f/chemiq/recover-drained.ts
if($LASTEXITCODE -ne 0){throw 'Independent recovery did not close lane'}
