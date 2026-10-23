$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskOut=Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/chemiq'
Set-Location -LiteralPath $taskRoot
$taskOldControl=Get-Content 'docs/repair-2026-10-10/full-f-rerun/control.json' -Raw|ConvertFrom-Json
$taskOldBroker=(Get-Content (Join-Path $taskOut 'transport-switch-closed.json') -Raw|ConvertFrom-Json).oldBrokerRunId
while($true){
 try{
  $taskC=Get-Content 'docs/repair-2026-10-10/full-f-rerun/control.json' -Raw|ConvertFrom-Json
  if(!$taskC.paidReady -or $taskC.provider.slug -ne 'digitalocean' -or $taskC.broker.runId -eq $taskOldBroker){Start-Sleep -Seconds 15;continue}
  $taskH=Get-Content $taskC.broker.healthPath -Raw|ConvertFrom-Json
  if(!$taskH.healthy -or $taskH.runId -ne $taskC.broker.runId -or ([DateTime]::UtcNow-([DateTime]$taskH.atUtc).ToUniversalTime()).TotalSeconds -gt 30){Start-Sleep -Seconds 15;continue}
  $taskB=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskC.broker.pid)"
  if(!$taskB -or $taskB.CommandLine -notlike '*full-f/shared/digitalocean-broker*.ts*--serve*'){throw 'New broker process identity mismatch'}
  $taskClosed=Get-Content (Join-Path $taskOut 'transport-switch-closed.json') -Raw|ConvertFrom-Json
  $taskActive=Get-Content (Join-Path $taskOut 'active-run.json') -Raw|ConvertFrom-Json
  if($taskActive.runId -ne $taskClosed.runId){break}
  if(Get-CimInstance Win32_Process -Filter "ProcessId=$($taskActive.pid)"){throw 'Old runner still exists'}
  if(!$taskClosed.cashAccountingClosed -or !$taskClosed.laneClosed -or $taskClosed.pending -ne 0){throw 'Native closure proof incomplete'}
  $taskRequest=Join-Path $taskOut 'round-handoff-request.json'
  Copy-Item -LiteralPath $taskRequest -Destination (Join-Path $taskActive.output 'transport-switch-original-handoff-request.json')
  @{protocol='chemiq-round-handoff-request-v1';requested=$false;reason='Root new shared broker published after safe CB-only SSE migration; own600s nonstream unchanged';atUtc=[DateTime]::UtcNow.ToString('o');newBrokerRunId=$taskC.broker.runId}|ConvertTo-Json|Set-Content $taskRequest -Encoding utf8
  $taskWait=Join-Path $taskOut 'round-handoff-wait.json'
  if(Test-Path $taskWait){$taskW=Get-Content $taskWait -Raw|ConvertFrom-Json;if($taskW.runId -eq $taskActive.runId){Move-Item -LiteralPath $taskWait -Destination (Join-Path $taskActive.output 'transport-switch-original-handoff-wait.json')}}
  $taskG=Get-Content (Join-Path $taskOut 'guardian-process.json') -Raw|ConvertFrom-Json
  $taskExisting=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskG.pid)"
  if($taskExisting){if($taskExisting.CommandLine -notlike '*full-f/chemiq/guardian.ps1*'){throw 'Guardian PID reused'}}else{
   $taskExe=(Get-Process -Id $PID).Path
   $taskGuard=Start-Process -FilePath $taskExe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','scripts/repair-2026-10-10/full-f/chemiq/guardian.ps1') -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru
   @{pid=$taskGuard.Id;startedAtUtc=[DateTime]::UtcNow.ToString('o');script='scripts/repair-2026-10-10/full-f/chemiq/guardian.ps1';digitalOceanOnly=$true;acceptsVerifiedCoordinatorRecovery=$true;windowStyle='Hidden'}|ConvertTo-Json|Set-Content (Join-Path $taskOut 'guardian-process.json') -Encoding utf8
  }
  @{atUtc=[DateTime]::UtcNow.ToString('o');oldBrokerRunId=$taskOldBroker;newBrokerRunId=$taskC.broker.runId;guardianResumed=$true;oldUnknownRetained=$true}|ConvertTo-Json|Set-Content (Join-Path $taskOut 'transport-switch-resume.json') -Encoding utf8
  break
 }catch{@{atUtc=[DateTime]::UtcNow.ToString('o');error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $taskOut 'transport-switch-resume-error.json') -Encoding utf8;Start-Sleep -Seconds 15}
}
