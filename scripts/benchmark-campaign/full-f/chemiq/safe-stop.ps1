$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskOut=Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/chemiq'
$taskActive=Get-Content -LiteralPath (Join-Path $taskOut 'active-run.json') -Raw|ConvertFrom-Json
$taskControl=Get-Content -LiteralPath (Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/control.json') -Raw|ConvertFrom-Json
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ChemIQStop {
 [DllImport("kernel32.dll")] public static extern IntPtr OpenProcess(uint access,bool inherit,uint id);
 [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
 [DllImport("ntdll.dll")] public static extern int NtSuspendProcess(IntPtr h);
 [DllImport("ntdll.dll")] public static extern int NtResumeProcess(IntPtr h);
}
'@
$taskUntil=[DateTime]::UtcNow.AddMinutes(8)
while([DateTime]::UtcNow -lt $taskUntil){
 $taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskActive.pid)"
 if(!$taskProcess){break}
 if($taskProcess.CommandLine -notlike '*full-f/chemiq/run.ts*'){throw 'Owned runner command mismatch'}
 $taskHandle=[ChemIQStop]::OpenProcess(0x0800,$false,[uint32]$taskActive.pid)
 if($taskHandle -eq [IntPtr]::Zero){throw 'Cannot open owned runner for atomic drain check'}
 $taskSuspended=$false
 try {
  if([ChemIQStop]::NtSuspendProcess($taskHandle) -ne 0){throw 'Cannot suspend owned runner briefly for atomic drain check'}
  $taskSuspended=$true
  $taskState=Get-Content -LiteralPath (Join-Path $taskActive.output 'journal/api-state.json') -Raw|ConvertFrom-Json
  $taskEvents=Get-Content -LiteralPath (Join-Path $taskActive.output 'journal/currency/cash-events.jsonl')|ForEach-Object {$_|ConvertFrom-Json}
  $taskStarts=@($taskEvents|Where-Object kind -eq start)
  $taskFinishes=@($taskEvents|Where-Object kind -eq finish)
  $taskBroker=Get-Content -LiteralPath $taskControl.broker.healthPath -Raw|ConvertFrom-Json
  $taskLane=$taskBroker.lanes|Where-Object runId -eq $taskActive.runId
  if($taskState.acceptedRequestCount -eq $taskState.finishedRequestCount -and $taskState.reservedUpperBoundUsd -eq 0 -and $taskStarts.Count -eq $taskFinishes.Count -and @($taskFinishes|Where-Object {$_.data.phase -ne 'known'}).Count -eq 0 -and $taskLane.active -eq 0){
   Stop-Process -Id $taskActive.pid
   $taskSuspended=$false
   @{protocol='chemiq-safe-drained-stop-v1';runId=$taskActive.runId;pid=$taskActive.pid;stoppedAtUtc=[DateTime]::UtcNow.ToString('o');acceptedRequests=$taskState.acceptedRequestCount;finishedRequests=$taskState.finishedRequestCount;reservedUsd=0;brokerLaneActive=0;cashStarts=$taskStarts.Count;cashFinishes=$taskFinishes.Count;reason='Repeated finalization_pending tasks6/9; source unchanged; atomic no-pending-request stop'}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $taskOut 'safe-stop.json') -Encoding utf8
   break
  }
 } finally {
  if($taskSuspended){[void][ChemIQStop]::NtResumeProcess($taskHandle)}
  [void][ChemIQStop]::CloseHandle($taskHandle)
 }
 Start-Sleep -Milliseconds 500
}
if(!(Test-Path (Join-Path $taskOut 'safe-stop.json'))){throw 'No fully drained boundary observed; runner left alive, no paid request killed'}
