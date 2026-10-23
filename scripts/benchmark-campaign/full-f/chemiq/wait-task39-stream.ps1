$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
Set-Location -LiteralPath $taskRoot
$taskOut=Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/chemiq'
$taskLimit=[DateTime]::UtcNow.AddHours(8)
while([DateTime]::UtcNow -lt $taskLimit){
 $taskControl=Get-Content 'docs/repair-2026-10-10/full-f-rerun/control.json' -Raw|ConvertFrom-Json
 $taskCandidate=@($taskControl.broker.sourcePins|Where-Object {$_.path -like '*digitalocean-broker-cq-stream.ts'})
 if($taskControl.paidReady -and $taskControl.provider.slug -eq 'digitalocean' -and $taskCandidate.Count -eq 1){
  foreach($taskPin in $taskControl.broker.sourcePins){if((Get-FileHash -LiteralPath $taskPin.path -Algorithm SHA256).Hash.ToLower() -ne $taskPin.sha256){throw 'Published broker pin changed; no dispatch'}}
  $taskBroker=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskControl.broker.pid)"
  if(!$taskBroker -or $taskBroker.CommandLine -notlike '*digitalocean-broker-cq-stream.ts*'){throw 'New broker PID/command mismatch'}
  $taskHealth=Get-Content -LiteralPath $taskControl.broker.healthPath -Raw|ConvertFrom-Json
  if($taskHealth.healthy -and $taskHealth.runId -eq $taskControl.broker.runId -and ([DateTime]::UtcNow-([DateTime]$taskHealth.atUtc).ToUniversalTime()).TotalSeconds -lt 30){
   $taskActive=Get-Content (Join-Path $taskOut 'active-run.json') -Raw|ConvertFrom-Json
   if(Get-Process -Id $taskActive.pid -ErrorAction SilentlyContinue){throw 'Existing runner alive; no duplicate stream dispatch'}
   $taskLane=Get-Content (Join-Path $taskActive.output 'lane-close.json') -Raw|ConvertFrom-Json
   $taskApi=Get-Content (Join-Path $taskActive.output 'journal/api-state.json') -Raw|ConvertFrom-Json
   if(!$taskLane.closed -or $taskApi.acceptedRequestCount -ne $taskApi.finishedRequestCount -or @($taskApi.active).Count -or @($taskApi.pending.PSObject.Properties).Count){throw 'Old native requests/lane not closed'}
   & (Join-Path $PSScriptRoot 'launch.ps1') -Task39Stream
   if($LASTEXITCODE){throw 'Task39 scoped launch failed'}
   @{atUtc=[DateTime]::UtcNow.ToString('o');pid=$PID;brokerRunId=$taskControl.broker.runId;brokerPid=$taskControl.broker.pid;action='One scoped task39 launch after published safe shared switch';onlyIndex=39;paidEntry='run-task39-stream.ts';old815NeverRepeated=$true}|ConvertTo-Json|Set-Content (Join-Path $taskOut 'task39-stream-wait-status.json') -Encoding utf8
   exit 0
  }
 }
 @{atUtc=[DateTime]::UtcNow.ToString('o');pid=$PID;action='Waiting for root safe shared CQ stream broker; no paid launch or old identical retry';oldBrokerRunId=$taskControl.broker.runId}|ConvertTo-Json|Set-Content (Join-Path $taskOut 'task39-stream-wait-status.json') -Encoding utf8
 Start-Sleep -Seconds 15
}
throw 'Root shared switch not published within8hours; no paid request was launched'
