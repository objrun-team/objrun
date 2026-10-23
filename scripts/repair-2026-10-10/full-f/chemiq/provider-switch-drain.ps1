$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskOut=Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/chemiq'
Set-Location -LiteralPath $taskRoot
$taskActive=Get-Content -LiteralPath (Join-Path $taskOut 'active-run.json') -Raw|ConvertFrom-Json
$taskControl=Get-Content -LiteralPath (Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/control.json') -Raw|ConvertFrom-Json
$taskParent=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskActive.pid)"
if($taskParent.CommandLine -notlike '*full-f/chemiq/run.ts*'){throw 'Parent runner identity mismatch'}
Add-Type -TypeDefinition @'
using System;using System.Runtime.InteropServices;public static class ChemIQSwitchFreeze{[DllImport("kernel32.dll")]public static extern IntPtr OpenProcess(uint a,bool b,uint c);[DllImport("kernel32.dll")]public static extern bool CloseHandle(IntPtr h);[DllImport("ntdll.dll")]public static extern int NtSuspendProcess(IntPtr h);}
'@
$taskFrozen=@()
foreach($taskDirectory in Get-ChildItem -LiteralPath $taskActive.output -Directory|Where-Object Name -Match '^task-\d+$'){
 $taskPath=Join-Path $taskDirectory.FullName 'process.json';if(!(Test-Path $taskPath)){continue}
 $taskRegistration=Get-Content -LiteralPath $taskPath -Raw|ConvertFrom-Json
 $taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskRegistration.pid)";if(!$taskProcess){continue}
 $taskAge=[Math]::Abs(($taskProcess.CreationDate.ToUniversalTime()-([DateTime]$taskRegistration.startedAtUtc).ToUniversalTime()).TotalSeconds)
 if($taskRegistration.runId -ne $taskActive.runId -or $taskProcess.CommandLine -notlike '*app*src*main.ts*' -or $taskAge -gt 10){throw 'Engine PID/birth/command identity mismatch'}
 $taskHandle=[ChemIQSwitchFreeze]::OpenProcess(0x0800,$false,[uint32]$taskRegistration.pid)
 if($taskHandle -eq [IntPtr]::Zero){throw 'Cannot open engine'}
 try{if([ChemIQSwitchFreeze]::NtSuspendProcess($taskHandle) -ne 0){throw 'Engine suspend failed'}}finally{[void][ChemIQSwitchFreeze]::CloseHandle($taskHandle)}
 $taskFrozen+=@{pid=$taskRegistration.pid;index=$taskRegistration.taskIndex;birthUtc=$taskProcess.CreationDate.ToUniversalTime().ToString('o');command=$taskProcess.CommandLine}
}
if(!$taskFrozen.Count){throw 'No live owned engines to suspend'}
@{protocol='chemiq-provider-switch-producer-freeze-v1';atUtc=[DateTime]::UtcNow.ToString('o');runId=$taskActive.runId;output=$taskActive.output;runnerPid=$taskActive.pid;engines=$taskFrozen;runnerAndProxyKeptAlive=$true;providerRequestsNotKilled=$true}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $taskOut 'provider-switch-suspended.json') -Encoding utf8
$taskStable=$null;$taskUntil=[DateTime]::UtcNow.AddMinutes(10)
while([DateTime]::UtcNow -lt $taskUntil){
 $taskState=Get-Content -LiteralPath (Join-Path $taskActive.output 'journal/api-state.json') -Raw|ConvertFrom-Json
 $taskBroker=Get-Content -LiteralPath $taskControl.broker.healthPath -Raw|ConvertFrom-Json
 $taskLane=$taskBroker.lanes|Where-Object runId -eq $taskActive.runId
 $taskEvents=Get-Content -LiteralPath (Join-Path $taskActive.output 'journal/currency/cash-events.jsonl')|ForEach-Object{$_|ConvertFrom-Json}
 $taskCashStarts=@($taskEvents|Where-Object kind -eq start);$taskCashFinishes=@($taskEvents|Where-Object kind -eq finish)
 $taskDrained=$taskState.acceptedRequestCount -eq $taskState.finishedRequestCount -and $taskState.reservedUpperBoundUsd -eq 0 -and $taskCashStarts.Count -eq $taskCashFinishes.Count -and $taskLane.active -eq 0
 if($taskDrained){if(!$taskStable){$taskStable=[DateTime]::UtcNow};if(([DateTime]::UtcNow-$taskStable).TotalSeconds -ge 5){break}}else{$taskStable=$null}
 Start-Sleep -Milliseconds 500
}
if(!$taskDrained -or !$taskStable -or ([DateTime]::UtcNow-$taskStable).TotalSeconds -lt 5){throw 'Requests not durably drained; engines stay suspended, runner/proxy alive, no request killed'}
& bun (Join-Path $PSScriptRoot 'snapshot-switch.mjs');if($LASTEXITCODE -ne 0){throw 'Task snapshot failed; no engine killed'}
foreach($taskEngine in $taskFrozen){
 $taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskEngine.pid)";if(!$taskProcess){continue}
 if($taskProcess.CommandLine -ne $taskEngine.command -or $taskProcess.CreationDate.ToUniversalTime().ToString('o') -ne $taskEngine.birthUtc){throw 'Engine identity changed; no kill'}
 Stop-Process -Id $taskEngine.pid
}
@{protocol='chemiq-provider-switch-drained-engine-stop-v1';atUtc=[DateTime]::UtcNow.ToString('o');runId=$taskActive.runId;runnerPid=$taskActive.pid;accepted=$taskState.acceptedRequestCount;finished=$taskState.finishedRequestCount;brokerLaneActive=0;cashStarts=$taskCashStarts.Count;cashFinishes=$taskCashFinishes.Count;enginesStopped=$taskFrozen;runnerNativeFinallyExpected=$true;unknownRetained=$true}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $taskOut 'provider-switch-drained.json') -Encoding utf8
