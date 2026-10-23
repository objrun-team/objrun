$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskOut=Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/chemiq'
$taskApproval=Get-Content (Join-Path $taskOut 'task39-reserve450-entry-approval.json') -Raw|ConvertFrom-Json
if(!$taskApproval.approved -or $taskApproval.onlyIndex -ne 39 -or $taskApproval.retainedValid -ne 815){throw 'Concrete reviewed scope missing'}
foreach($taskPin in (@($taskApproval.sourcePins)+@($taskApproval.commonSourcePins))){if((Get-Item -LiteralPath $taskPin.path).Length -ne $taskPin.bytes -or (Get-FileHash -LiteralPath $taskPin.path -Algorithm SHA256).Hash.ToLower() -ne $taskPin.sha256){throw 'Root-reviewed pin mismatch'}}
$taskControl=Get-Content (Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/control.json') -Raw|ConvertFrom-Json
if(!$taskControl.paidReady -or !$taskControl.dockerBenchResume.chemiq -or $taskControl.broker.pid -ne $taskApproval.connectionPid -or $taskControl.broker.runId -ne $taskApproval.connectionRunId){throw 'Original shared broker readiness changed'}
$taskStatus=Get-Content (Join-Path $taskOut 'status.json') -Raw|ConvertFrom-Json
if($taskStatus.completed -ne 815 -or $taskStatus.pendingRequests -ne 0 -or !$taskStatus.accountingClosed){throw 'Native closure and retained815 required'}
$taskPrevious=Get-Content (Join-Path $taskOut 'active-run.json') -Raw|ConvertFrom-Json
if($taskPrevious.pid -and (Get-Process -Id $taskPrevious.pid -ErrorAction SilentlyContinue)){throw 'Previous runner alive'}
if(Test-Path (Join-Path $taskOut 'task39-reserve450-launch-issued.json')){throw 'Single launch already issued'}
$taskHealth=Invoke-RestMethod http://127.0.0.1:17918/health -TimeoutSec 15
if(!$taskHealth.ok -or $taskHealth.items -ne 816 -or $taskHealth.level -ne 0 -or $taskHealth.opsin.rest_fallback -or $taskHealth.opsin.jar_sha256 -ne 'd25bc08f41b8f6fcd6f35e18ab83f3b8d9218cdb003d55c5f74aaefe2e0c68ab'){throw 'Original grader mismatch'}
$taskStamp=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$taskHistory=Join-Path $taskOut "reserve450-prelaunch-$taskStamp"
New-Item -ItemType Directory -Path $taskHistory|Out-Null
foreach($taskName in @('active-run.json','background-process.json','status.json')){Copy-Item -LiteralPath (Join-Path $taskOut $taskName) -Destination (Join-Path $taskHistory $taskName)}
$taskBun=(& bun -p 'process.execPath').Trim()
$taskProcess=Start-Process -FilePath $taskBun -ArgumentList @('scripts/benchmark-campaign/full-f/chemiq/run-task39-reserve450-relace.ts','relace') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskOut "reserve450-relace-$taskStamp.stdout.log") -RedirectStandardError (Join-Path $taskOut "reserve450-relace-$taskStamp.stderr.log") -PassThru
@{pid=$taskProcess.Id;startedAtUtc=[DateTime]::UtcNow.ToString('o');script='scripts/benchmark-campaign/full-f/chemiq/run-task39-reserve450-relace.ts';supplier='relace';windowStyle='Hidden';independentOfCodexToolSession=$true;singleMaterialExperiment=$true;noAutomaticSequence=$true;historicalProcessEvidence=$taskHistory}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $taskOut 'background-process.json') -Encoding utf8
Write-Output "ChemIQ only39 reserve450 submit Relace hidden PID $($taskProcess.Id)"

