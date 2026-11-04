$ErrorActionPreference='Stop'
$ceRoot='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$ceSrc=Join-Path $ceRoot 'examples/benchmark/code-benchmarks/classeval'
$ceOut=Join-Path $ceRoot 'docs/newbench-20261014/classeval'
$ceLaunch=Get-Content -LiteralPath (Join-Path $ceOut 'launch.json') -Raw|ConvertFrom-Json
$ceOldPid=[int]$ceLaunch.pid
$ceUntil=[DateTime]::UtcNow.AddMinutes(20)
$ceStop=Join-Path $ceOut 'stop-after-current-tasks.json'
if(Test-Path -LiteralPath $ceStop){throw 'An existing stop request must remain in effect.'}
Write-Output "Waiting for ClassEval ObjRun receipts before changing concurrency; old PID $ceOldPid."
while(Get-Process -Id $ceOldPid -ErrorAction SilentlyContinue){
  if([DateTime]::UtcNow -gt $ceUntil){throw 'Safe drain timed out; existing experiment left running.'}
  $ceStatus=Get-Content -LiteralPath (Join-Path $ceOut 'status.json') -Raw|ConvertFrom-Json
  if(@($ceStatus.active|Where-Object{$_.arm -eq 'objrun'}).Count -eq 0){break}
  Start-Sleep -Seconds 1
}
if(Get-Process -Id $ceOldPid -ErrorAction SilentlyContinue){
  @{requestedAtUtc=[DateTime]::UtcNow.ToString('o');reason='User requested total concurrency 8; drain current baseline task';owner='concurrency-switch-8'}|ConvertTo-Json|Set-Content -LiteralPath $ceStop -Encoding utf8
  Write-Output 'ObjRun receipts settled; draining the current baseline task.'
  while(Get-Process -Id $ceOldPid -ErrorAction SilentlyContinue){
    if([DateTime]::UtcNow -gt $ceUntil){throw 'Runner drain timed out; checkpoint stop request retained.'}
    Start-Sleep -Seconds 1
  }
}
$ceArchive=Join-Path $ceOut ('recovery/concurrency-8-'+(Get-Date -Format yyyyMMddTHHmmss))
New-Item -ItemType Directory -Force -Path $ceArchive|Out-Null
foreach($ceFile in @('run.ts','experiment.json','grader_service.py','start.ps1')){
  Copy-Item -LiteralPath (Join-Path $ceSrc $ceFile) -Destination (Join-Path $ceArchive $ceFile)
}
foreach($ceFile in @('source-pins.json','status.json','RUNNING.md','launch.json')){
  Copy-Item -LiteralPath (Join-Path $ceOut $ceFile) -Destination (Join-Path $ceArchive $ceFile)
}
$cePins=@(Get-ChildItem -LiteralPath (Join-Path $ceOut 'results') -Recurse -Filter '*.json'|ForEach-Object{
  $ceRecord=Get-Content -LiteralPath $_.FullName -Raw|ConvertFrom-Json
  if($ceRecord.grade.valid){@{path=$_.FullName;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}}
})
@{atUtc=[DateTime]::UtcNow.ToString('o');oldPid=$ceOldPid;concurrency=8;validResultPins=$cePins;perTaskDollarCap=$null}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $ceArchive 'checkpoint.json') -Encoding utf8
foreach($ceFile in @('run.ts','experiment.json','grader_service.py','start.ps1')){
  Copy-Item -LiteralPath (Join-Path $ceSrc "concurrency-8-stage/$ceFile.pending") -Destination (Join-Path $ceSrc $ceFile)
}
Set-Location -LiteralPath $ceRoot
& bun test examples/benchmark/code-benchmarks/classeval/interface-policy.test.ts examples/benchmark/code-benchmarks/classeval/task-slots.test.ts
if($LASTEXITCODE -ne 0){throw 'Concurrency verification failed; experiment remains checkpointed.'}
& python -m py_compile examples/benchmark/code-benchmarks/classeval/grader_service.py
if($LASTEXITCODE -ne 0){throw 'Grader compile failed; experiment remains checkpointed.'}
& bun build examples/benchmark/code-benchmarks/classeval/run.ts --target=bun --outfile examples/benchmark/code-benchmarks/classeval/run.build.js
if($LASTEXITCODE -ne 0){throw 'Runner build failed; experiment remains checkpointed.'}
& bun run examples/benchmark/code-benchmarks/classeval/run.ts pin
if($LASTEXITCODE -ne 0){throw 'Source pinning failed; experiment remains checkpointed.'}
if(Test-Path -LiteralPath $ceStop){
  $ceOwnedStop=Get-Content -LiteralPath $ceStop -Raw|ConvertFrom-Json
  if($ceOwnedStop.owner -ne 'concurrency-switch-8'){throw 'A separate stop request must remain in effect.'}
  Remove-Item -LiteralPath $ceStop
}
& (Join-Path $ceSrc 'start.ps1')
$ceNewLaunch=Get-Content -LiteralPath (Join-Path $ceOut 'launch.json') -Raw|ConvertFrom-Json
@{atUtc=[DateTime]::UtcNow.ToString('o');stage='restarted';oldPid=$ceOldPid;newPid=$ceNewLaunch.pid;concurrency=8;graderConcurrency=8;archive=$ceArchive;perTaskDollarCap=$null}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $ceOut 'concurrency-change.json') -Encoding utf8
Write-Output "ClassEval restarted at shared concurrency 8; PID $($ceNewLaunch.pid)."
