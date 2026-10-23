$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskOut=Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/chemiq'
$taskControl=Get-Content (Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/control.json') -Raw|ConvertFrom-Json
if(!$taskControl.paidReady -or !$taskControl.dockerBenchResume.chemiq -or !@($taskControl.broker.sourcePins|Where-Object {$_.path -like '*digitalocean-broker-cq-suppliers.ts'}).Count){throw 'Original sole supplier broker not ready'}
$taskReady=Get-Content (Join-Path $taskOut 'task39-handoff-relace-entry-ready.json') -Raw|ConvertFrom-Json
if(!$taskReady.ready -or !$taskReady.buildPassed -or !$taskReady.singleBoundedExperiment){throw 'Material single-variable entry readiness missing'}
foreach($taskPin in $taskReady.sourcePins){if((Get-FileHash -LiteralPath $taskPin.path -Algorithm SHA256).Hash.ToLower() -ne $taskPin.sha256){throw 'Frozen handoff entry pin changed'}}
$taskStatus=Get-Content (Join-Path $taskOut 'status.json') -Raw|ConvertFrom-Json
if($taskStatus.completed -ne 815 -or $taskStatus.pendingRequests -ne 0){throw 'Retained815 and pending0 required'}
$taskPrevious=Get-Content (Join-Path $taskOut 'active-run.json') -Raw|ConvertFrom-Json
if(Get-Process -Id $taskPrevious.pid -ErrorAction SilentlyContinue){throw 'Previous runner still alive'}
$taskBoundary=Get-Content (Join-Path $taskOut 'task39-supplier-boundary-wafer.json') -Raw|ConvertFrom-Json
if(!$taskBoundary.nativeVerified -or !$taskBoundary.laneClosed -or $taskBoundary.pending -ne 0){throw 'Previous native closure missing'}
$taskOnce=Join-Path $taskOut 'task39-handoff-relace-launch-issued.json'
if(Test-Path -LiteralPath $taskOnce){throw 'Single material experiment already issued; no blind repeat'}
$taskHealth=Invoke-RestMethod 'http://127.0.0.1:17918/health' -TimeoutSec 15
if(!$taskHealth.ok -or $taskHealth.items -ne 816 -or $taskHealth.level -ne 0 -or $taskHealth.opsin.rest_fallback -or $taskHealth.opsin.jar_sha256 -ne 'd25bc08f41b8f6fcd6f35e18ab83f3b8d9218cdb003d55c5f74aaefe2e0c68ab'){throw 'Original grader identity mismatch'}
$taskBun=(& bun -p 'process.execPath').Trim();$taskStamp=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
@{atUtc=[DateTime]::UtcNow.ToString('o');phase='issued';onlyIndex=39;materialOneVariable=$true;provider='relace';noAutomaticSequence=$true}|ConvertTo-Json|Set-Content -LiteralPath $taskOnce -Encoding utf8
$taskProcess=Start-Process -FilePath $taskBun -ArgumentList @('scripts/repair-2026-10-10/full-f/chemiq/run-task39-handoff-relace.ts','relace') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskOut "handoff-relace-$taskStamp.stdout.log") -RedirectStandardError (Join-Path $taskOut "handoff-relace-$taskStamp.stderr.log") -PassThru
@{pid=$taskProcess.Id;startedAtUtc=[DateTime]::UtcNow.ToString('o');script='scripts/repair-2026-10-10/full-f/chemiq/run-task39-handoff-relace.ts';supplier='relace';windowStyle='Hidden';independentOfCodexToolSession=$true;singleMaterialExperiment=$true;noAutomaticSequence=$true}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $taskOut 'background-process.json') -Encoding utf8
Write-Output "ChemIQ only39 material handoff Relace hidden PID $($taskProcess.Id)"
