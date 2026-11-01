param([switch]$WaitForBroker,[switch]$Task39Stream)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskOut = Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/chemiq'
$taskStorageHoldPath=Join-Path $taskOut 'storage-paid-hold.json'
if(Test-Path -LiteralPath $taskStorageHoldPath){
  $taskStorageHold=Get-Content -LiteralPath $taskStorageHoldPath -Raw|ConvertFrom-Json
  if($taskStorageHold.requested){throw 'ChemIQ storage hold: require root storage recovery and actual original grader readiness before paid launch'}
}
$taskActive = Join-Path $taskOut 'active-run.json'
if (Test-Path $taskActive) {
  $taskPrevious = Get-Content -LiteralPath $taskActive -Raw | ConvertFrom-Json
  $taskRunning = Get-Process -Id $taskPrevious.pid -ErrorAction SilentlyContinue
  if ($taskRunning) { Write-Output "ChemIQ runner already alive: $($taskPrevious.pid)"; exit 0 }
}
$taskControlPath = Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/control.json'
while ($true) {
  $taskControl = Get-Content -LiteralPath $taskControlPath -Raw | ConvertFrom-Json
  if ($taskControl.paidReady -eq $true -and ($taskControl.provider.slug -eq 'digitalocean' -or $taskControl.provider -eq 'digitalocean')) { break }
  if (!$WaitForBroker) { Write-Output 'ChemIQ queued: shared paidReady is false'; exit 0 }
  Start-Sleep -Seconds 600
}
$taskValidation = Get-Content -LiteralPath (Join-Path $taskOut 'environment-validation.json') -Raw | ConvertFrom-Json
if (!$taskValidation.valid -or $taskValidation.checked -ne 816) { throw 'ChemIQ real grader validation is incomplete' }
$taskHealth = Invoke-RestMethod 'http://127.0.0.1:17918/health'
if ($taskHealth.items -ne 816 -or $taskHealth.opsin.profile -ne 'local-2.8' -or $taskHealth.opsin.rest_fallback -ne $false) { throw 'ChemIQ grader health mismatch' }
$taskBun = (& bun -p 'process.execPath').Trim()
$taskEntry='scripts/benchmark-campaign/full-f/chemiq/run.ts'
if($Task39Stream){
  if(!@($taskControl.broker.sourcePins|Where-Object {$_.path -like '*digitalocean-broker-cq-stream.ts'}).Count){throw 'Task39 stream requires new shared broker'}
  $taskReady=Get-Content (Join-Path $taskOut 'task39-stream-entry-ready.json') -Raw|ConvertFrom-Json
  if(!$taskReady.ready -or !$taskReady.buildPassed){throw 'Scoped entry not ready'}
  foreach($taskPin in @($taskReady.entryPin,$taskReady.scopeTemplatePin,$taskReady.adapterPin)){
    if((Get-FileHash -LiteralPath $taskPin.path -Algorithm SHA256).Hash.ToLower() -ne $taskPin.sha256){throw 'Scoped entry frozen pin changed'}
  }
  $taskEntry='scripts/benchmark-campaign/full-f/chemiq/run-task39-stream.ts'
}
$taskTimestamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$taskProcess = Start-Process -FilePath $taskBun -ArgumentList @($taskEntry) -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskOut "runner-$taskTimestamp.stdout.log") -RedirectStandardError (Join-Path $taskOut "runner-$taskTimestamp.stderr.log") -PassThru
@{pid=$taskProcess.Id;startedAtUtc=[DateTime]::UtcNow.ToString('o');executable=$taskBun;script=$taskEntry;windowStyle='Hidden';independentOfHostToolSession=$true} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskOut 'background-process.json') -Encoding utf8
Write-Output "ChemIQ full816 independent runner PID: $($taskProcess.Id)"
