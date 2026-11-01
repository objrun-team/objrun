param([ValidateSet('relace','dekallm','wafer')][string]$Supplier='relace')
$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskOut=Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/chemiq'
$taskControl=Get-Content (Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/control.json') -Raw|ConvertFrom-Json
if(!$taskControl.paidReady -or !$taskControl.dockerBenchResume.chemiq -or !@($taskControl.broker.sourcePins|Where-Object {$_.path -like '*digitalocean-broker-cq-suppliers.ts'}).Count){throw 'Await root safe scoped supplier broker readiness'}
$taskReady=Get-Content (Join-Path $taskOut 'task39-supplier-entry-ready.json') -Raw|ConvertFrom-Json
if(!$taskReady.ready -or !$taskReady.buildPassed){throw 'Scoped supplier entry not validated'}
foreach($taskPin in $taskReady.sourcePins){if((Get-FileHash -LiteralPath $taskPin.path -Algorithm SHA256).Hash.ToLower() -ne $taskPin.sha256){throw 'Supplier entry source proof changed'}}
$taskStatus=Get-Content (Join-Path $taskOut 'status.json') -Raw|ConvertFrom-Json
if($taskStatus.completed -ne 815){throw 'Must retain815 and only pending39'}
$taskPrevious=Get-Content (Join-Path $taskOut 'active-run.json') -Raw|ConvertFrom-Json
if(Get-Process -Id $taskPrevious.pid -ErrorAction SilentlyContinue){throw 'Previous ChemIQ runner is still alive'}
$taskHistory=@(Get-ChildItem -LiteralPath (Join-Path $taskOut 'runs') -Directory|ForEach-Object {$p=Join-Path $_.FullName 'manifest.json';if(Test-Path $p){$m=Get-Content $p -Raw|ConvertFrom-Json;if(@('relace','dekallm','wafer') -contains $m.settings.providerSlug -and (Test-Path (Join-Path $_.FullName 'stream-task-scope.json'))){[pscustomobject]@{provider=$m.settings.providerSlug;output=$_.FullName}}}})
if(@($taskHistory|Where-Object {$_.provider -eq $Supplier}).Count){throw 'No blind repeat of an already attempted approved supplier'}
$taskOrder=@('relace','dekallm','wafer');$taskPosition=[Array]::IndexOf($taskOrder,$Supplier)
for($taskI=0;$taskI -lt $taskPosition;$taskI++){$taskPrior=$taskHistory|Where-Object {$_.provider -eq $taskOrder[$taskI]};if(!$taskPrior){throw 'Supplier sequence prerequisite not attempted'};if(!(Test-Path (Join-Path $taskPrior.output 'currency-close.json'))){throw 'Prior supplier native closure absent'}}
$taskHealth=Invoke-RestMethod 'http://127.0.0.1:17918/health' -TimeoutSec 15
if(!$taskHealth.ok -or $taskHealth.items -ne 816 -or $taskHealth.level -ne 0 -or $taskHealth.opsin.rest_fallback -or $taskHealth.opsin.jar_sha256 -ne 'd25bc08f41b8f6fcd6f35e18ab83f3b8d9218cdb003d55c5f74aaefe2e0c68ab'){throw 'Original grader identity mismatch'}
$taskBun=(& bun -p 'process.execPath').Trim();$taskStamp=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$taskProcess=Start-Process -FilePath $taskBun -ArgumentList @('scripts/benchmark-campaign/full-f/chemiq/run-task39-supplier.ts',$Supplier) -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskOut "supplier-$Supplier-$taskStamp.stdout.log") -RedirectStandardError (Join-Path $taskOut "supplier-$Supplier-$taskStamp.stderr.log") -PassThru
@{pid=$taskProcess.Id;startedAtUtc=[DateTime]::UtcNow.ToString('o');script='scripts/benchmark-campaign/full-f/chemiq/run-task39-supplier.ts';supplier=$Supplier;windowStyle='Hidden';independentOfHostToolSession=$true}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $taskOut 'background-process.json') -Encoding utf8
Write-Output "ChemIQ only39 supplier $Supplier hidden PID $($taskProcess.Id)"
