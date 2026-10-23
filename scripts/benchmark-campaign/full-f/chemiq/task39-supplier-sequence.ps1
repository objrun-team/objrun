$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskOut=Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/chemiq'
Set-Location -LiteralPath $taskRoot
$taskBun=(& bun -p 'process.execPath').Trim()
try {
 $taskInitial=Get-Content (Join-Path $taskOut 'background-process.json') -Raw|ConvertFrom-Json
 $taskOrder=@('relace','dekallm','wafer');$taskStart=[Array]::IndexOf($taskOrder,$taskInitial.supplier)
 if($taskStart -lt 0){throw 'Unapproved supplier sequence start'}
 foreach($taskSupplier in $taskOrder[$taskStart..2]) {
  $taskBackground=Get-Content (Join-Path $taskOut 'background-process.json') -Raw|ConvertFrom-Json
  if($taskBackground.supplier -ne $taskSupplier){throw 'Unexpected supplier sequence identity'}
  while(Get-Process -Id $taskBackground.pid -ErrorAction SilentlyContinue){Start-Sleep -Seconds 5}
  & $taskBun 'scripts/benchmark-campaign/full-f/chemiq/verify-task39-supplier-boundary.mjs'
  if($LASTEXITCODE -ne 0){throw 'Supplier native boundary verification failed'}
  & $taskBun 'scripts/benchmark-campaign/full-f/chemiq/inspect.ts'
  if($LASTEXITCODE -ne 0){throw 'Supplier journal inspection failed'}
  & $taskBun 'scripts/benchmark-campaign/full-f/chemiq/heartbeat-audit.mjs'
  if($LASTEXITCODE -ne 0){throw 'Supplier total fees audit failed'}
  $taskStatus=Get-Content (Join-Path $taskOut 'status.json') -Raw|ConvertFrom-Json
  $taskBoundary=Get-Content (Join-Path $taskOut "task39-supplier-boundary-$taskSupplier.json") -Raw|ConvertFrom-Json
  if($taskStatus.completed -eq 816 -or $taskBoundary.terminalProtocolFailure){break}
  if($taskSupplier -eq 'wafer'){throw 'Approved supplier sequence exhausted; retain815 and evidence'}
  $taskNext=if($taskSupplier -eq 'relace'){'dekallm'}else{'wafer'}
  & (Join-Path $PSScriptRoot 'launch-task39-supplier.ps1') -Supplier $taskNext
 }
 @{atUtc=[DateTime]::UtcNow.ToString('o');phase='native-complete-awaiting-final-audit';validScored=$taskStatus.completed;terminalProtocolFailure=$taskBoundary.terminalProtocolFailure;blindDigitalOceanRetries=$false}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $taskOut 'task39-supplier-sequence-result.json') -Encoding utf8
} catch {
 @{atUtc=[DateTime]::UtcNow.ToString('o');phase='stopped';error=$_.Exception.Message;blindDigitalOceanRetries=$false}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $taskOut 'task39-supplier-sequence-result.json') -Encoding utf8
 exit 1
}
