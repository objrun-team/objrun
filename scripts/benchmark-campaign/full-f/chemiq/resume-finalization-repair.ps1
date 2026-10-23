$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskOut=Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/chemiq'
Set-Location -LiteralPath $taskRoot
$taskActive=Get-Content (Join-Path $taskOut 'active-run.json') -Raw|ConvertFrom-Json
$taskPrepared=Get-Content (Join-Path $taskOut 'pending-recovery-scheduler.json') -Raw|ConvertFrom-Json
while($true){
 try{
  $taskNow=Get-Content (Join-Path $taskOut 'active-run.json') -Raw|ConvertFrom-Json
  if($taskNow.runId -ne $taskActive.runId){break}
  $taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskActive.pid)"
  if($taskProcess){if($taskProcess.CommandLine -notlike '*full-f/chemiq/run.ts*'){throw 'Refuse reused PID'};Start-Sleep -Seconds 15;continue}
  if(!(Test-Path (Join-Path $taskActive.output 'currency-close.json')) -or !(Test-Path (Join-Path $taskActive.output 'lane-close.json'))){Start-Sleep -Seconds 15;continue}
  if(Test-Path (Join-Path $PSScriptRoot 'run.ts.pending')){& bun (Join-Path $PSScriptRoot 'install-pending.mjs');if($LASTEXITCODE -ne 0){throw 'Safe installation not complete'}}
  $taskReceipt=Get-Content (Join-Path $taskOut 'recovery-scheduler-installed.json') -Raw|ConvertFrom-Json
  $taskHash=(Get-FileHash (Join-Path $PSScriptRoot 'run.ts') -Algorithm SHA256).Hash.ToLowerInvariant()
  if($taskReceipt.previousRunId -ne $taskActive.runId -or $taskHash -ne $taskPrepared.sha256 -or $taskReceipt.sourceSha256 -ne $taskHash){throw 'Installed repair receipt/hash mismatch'}
  $taskWait=Join-Path $taskOut 'round-handoff-wait.json'
  if(Test-Path $taskWait){$taskWaitData=Get-Content $taskWait -Raw|ConvertFrom-Json;if($taskWaitData.runId -ne $taskActive.runId){throw 'Unrelated handoff wait'};Move-Item -LiteralPath $taskWait -Destination (Join-Path $taskActive.output 'finalization-repair-original-handoff-wait.json')}
  $taskRequest=Join-Path $taskOut 'round-handoff-request.json'
  Copy-Item -LiteralPath $taskRequest -Destination (Join-Path $taskActive.output 'finalization-repair-original-handoff-request.json')
  @{protocol='chemiq-round-handoff-request-v1';requested=$false;reason='Own finalization observer repair installed after native journal/cash/lane closure; guardian may resume in same healthy parent';atUtc=[DateTime]::UtcNow.ToString('o');previousRunId=$taskActive.runId;installedSourceSha256=$taskHash}|ConvertTo-Json|Set-Content $taskRequest -Encoding utf8
  @{protocol='chemiq-finalization-repair-resume-ready-v1';atUtc=[DateTime]::UtcNow.ToString('o');previousRunId=$taskActive.runId;nativeCashAndLaneClosed=$true;installedSourceSha256=$taskHash;guardianResumes=$true}|ConvertTo-Json|Set-Content (Join-Path $taskOut 'finalization-repair-resume-ready.json') -Encoding utf8
  break
 }catch{ @{atUtc=[DateTime]::UtcNow.ToString('o');error=$_.Exception.Message;originalRunId=$taskActive.runId}|ConvertTo-Json|Set-Content (Join-Path $taskOut 'finalization-repair-resumer-status.json') -Encoding utf8;Start-Sleep -Seconds 15 }
}
