$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskOut=Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/chemiq'
Set-Location -LiteralPath $taskRoot
while($true){
 try{
  $taskAction='Check runner; restart only after durable cash and lane closure'
  $taskActive=Get-Content -LiteralPath (Join-Path $taskOut 'active-run.json') -Raw|ConvertFrom-Json
  $taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskActive.pid)"
  if($taskProcess){
   if($taskProcess.CommandLine -notmatch 'full-f/chemiq/(run|run-task39-stream)\.ts'){throw 'Runner PID reused; guardian refuses unrelated process'}
  }else{
   $taskStatus=Get-Content -LiteralPath (Join-Path $taskOut 'status.json') -Raw|ConvertFrom-Json
   if($taskStatus.phase -eq 'complete'){break}
   $taskClosed=Test-Path -LiteralPath (Join-Path $taskActive.output 'lane-close.json')
   $taskCashClosed=Test-Path -LiteralPath (Join-Path $taskActive.output 'currency-close.json')
   $taskControl=Get-Content -LiteralPath (Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/control.json') -Raw|ConvertFrom-Json
   if(!$taskClosed -and $taskCashClosed -and $taskControl.paidReady){
    & bun (Join-Path $PSScriptRoot 'accept-recovered-lane.mjs')
    if($LASTEXITCODE -eq 0){$taskClosed=$true}
   }
   if($taskClosed -and $taskCashClosed -and $taskControl.paidReady -and ($taskControl.provider.slug -eq 'digitalocean' -or $taskControl.provider -eq 'digitalocean')){
    if(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'run.ts.pending')){
     & bun (Join-Path $PSScriptRoot 'install-pending.mjs')
     if($LASTEXITCODE -ne 0){throw 'Pending scheduler did not pass safe-boundary installation checks'}
    }
    $taskResumeAllowed=$true
    $taskRequestPath=Join-Path $taskOut 'round-handoff-request.json'
    $taskWaitPath=Join-Path $taskOut 'round-handoff-wait.json'
    $taskHandoff=$null
    if(Test-Path -LiteralPath $taskRequestPath){
     $taskRequest=Get-Content -LiteralPath $taskRequestPath -Raw|ConvertFrom-Json
     if($taskRequest.requested){$taskHandoff=@{brokerRunId=$taskRequest.brokerRunId;round=$taskRequest.round}}
    }
    if(Test-Path -LiteralPath $taskWaitPath){
     $taskWait=Get-Content -LiteralPath $taskWaitPath -Raw|ConvertFrom-Json
     if($taskWait.runId -eq $taskActive.runId){$taskHandoff=@{brokerRunId=$taskWait.brokerRunId;round=$taskWait.waitUntilRoundGreaterThan}}
    }
    if($taskHandoff){
     $taskHealth=Get-Content -LiteralPath $taskControl.broker.healthPath -Raw|ConvertFrom-Json
     $taskFresh=([DateTime]::UtcNow-([DateTime]$taskHealth.atUtc).ToUniversalTime()).TotalSeconds -lt 30
     $taskParentRefreshed=$taskHealth.runId -ne $taskHandoff.brokerRunId -or $taskHealth.round -gt $taskHandoff.round -or $null -eq $taskHealth.canonicalOwner
     $taskResumeAllowed=$taskHealth.healthy -and $taskFresh -and $taskParentRefreshed
     if(!$taskResumeAllowed){$taskAction='Waiting after closed lane for parent round refresh; no new lane claim'}else{
      @{protocol='chemiq-parent-round-resume-v1';atUtc=[DateTime]::UtcNow.ToString('o');previousRunId=$taskActive.runId;requestedBrokerRunId=$taskHandoff.brokerRunId;requestedRound=$taskHandoff.round;actualBrokerRunId=$taskHealth.runId;actualRound=$taskHealth.round;parentReleased=($null -eq $taskHealth.canonicalOwner);unknownEvidenceRetained=$true}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $taskOut 'round-handoff-resume.json') -Encoding utf8
     }
    }
    $taskHoldPath=Join-Path $taskOut 'upstream-repair-hold.json'
    if(Test-Path -LiteralPath $taskHoldPath){
     $taskHold=Get-Content -LiteralPath $taskHoldPath -Raw|ConvertFrom-Json
     if($taskHold.requested){$taskResumeAllowed=$false;$taskAction='Native lane closed; hold identical upstream failures for material repair; preserve costs and scores'}
    }
    if($taskResumeAllowed){& (Join-Path $PSScriptRoot 'launch.ps1')}
   }
  }
  @{protocol='chemiq-guardian-v1';pid=$PID;atUtc=[DateTime]::UtcNow.ToString('o');watchedRunId=$taskActive.runId;watchedPid=$taskActive.pid;action=$taskAction;independentOfCodexToolSession=$true}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $taskOut 'guardian-status.json') -Encoding utf8
 }catch{
  @{pid=$PID;atUtc=[DateTime]::UtcNow.ToString('o');error=$_.Exception.Message;action='Retain evidence; next check in60s'}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $taskOut 'guardian-status.json') -Encoding utf8
 }
 Start-Sleep -Seconds 60
}
