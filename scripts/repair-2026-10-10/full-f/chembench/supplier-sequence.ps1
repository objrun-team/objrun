$ErrorActionPreference='Stop'
$seqRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../../..')).Path
$seqOut=Join-Path $seqRoot 'docs/repair-2026-10-10/full-f-rerun/chembench'
$seqOrder=@('relace','dekallm','wafer')
function Read-SeqJson($path){Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json}
function Write-SeqJson($path,$value){[IO.File]::WriteAllText($path,($value|ConvertTo-Json -Depth 30),(New-Object Text.UTF8Encoding($false)))}
function Phase($name,$data){Write-SeqJson (Join-Path $seqOut 'supplier-sequence-status.json') @{atUtc=[DateTime]::UtcNow.ToString('o');phase=$name;pid=$PID;details=$data;index=277}}
function Live-Receipt($receipt){
 if(!(Test-Path -LiteralPath $receipt)){return $null};$r=Read-SeqJson $receipt
 $p=Get-CimInstance Win32_Process -Filter "ProcessId=$($r.pid)"
 if($p -and $p.CommandLine.Contains($r.entry) -and [Math]::Abs(($p.CreationDate.ToUniversalTime()-[DateTime]::Parse($r.startedAtUtc).ToUniversalTime()).TotalSeconds) -lt 10){return $p};return $null
}
function Gate {
 $a=Read-SeqJson (Join-Path $seqOut 'supplier-sequence-authorization.json')
 $c=Read-SeqJson (Join-Path $seqRoot 'docs/repair-2026-10-10/full-f-rerun/control.json')
 if(!$a.armed -or !$a.rootReady -or !$a.userAuthorized -or $a.index -ne 277 -or ($a.approvedOrder -join ',') -ne ($seqOrder -join ',') -or $a.brokerRunId -ne $c.broker.runId -or $a.brokerPid -ne $c.broker.pid -or !$c.paidReady){throw 'Root ready/current broker/approved order gate closed'}
 $p=Get-CimInstance Win32_Process -Filter "ProcessId=$($a.brokerPid)"
 if(!$p -or !$p.CommandLine.Contains('digitalocean-broker-cb-suppliers.ts') -or [Math]::Abs(($p.CreationDate.ToUniversalTime()-[DateTime]::Parse($a.brokerCreatedAtUtc).ToUniversalTime()).TotalSeconds) -gt 1){throw 'Supplier broker PID/creation/entry mismatch'}
 $h=Invoke-RestMethod ($c.broker.endpoint+'/health') -TimeoutSec 10
 if(!$h.healthy -or $h.pid -ne $a.brokerPid -or $h.runId -ne $a.brokerRunId -or $h.transportPolicy.chembench -ne 'upstream-sse-approved-supplier-complete-aggregation-v1'){throw 'Supplier broker health mismatch'}
 if(Live-Receipt (Join-Path $seqOut 'supervisor-process.json')){throw 'Ordinary guardian alive'}
 return $a
}
$seqLock=$null
$seqOwn=$false
try {
 $seqLock=[IO.File]::Open((Join-Path $seqOut 'supplier-sequence.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
 $seqBorn=(Get-CimInstance Win32_Process -Filter "ProcessId=$PID").CreationDate.ToUniversalTime().ToString('o')
 Write-SeqJson (Join-Path $seqOut 'supplier-sequence-process.json') @{pid=$PID;entry=$PSCommandPath;startedAtUtc=$seqBorn;hidden=$true;kind='single-supplier-sequence'}
 $seqAuth=Gate
 if(Live-Receipt (Join-Path $seqOut 'runner-process.json')){throw 'Existing runner alive'}
 $seqProgressPath=Join-Path $seqOut 'supplier-sequence-progress.json'
 if(Test-Path $seqProgressPath){throw 'Sequence already attempted; inspect durable progress, never repeat automatically'}
 $seqOwn=$true
 $baseline=& bun (Join-Path $PSScriptRoot 'supplier-sequence-audit.ts') --baseline
 if($LASTEXITCODE -ne 0){throw 'Frozen500/retained499 baseline failed'}
 $seqBaselinePath=Join-Path $seqOut 'supplier-sequence-retention-baseline.json'
 Write-SeqJson $seqBaselinePath ($baseline|ConvertFrom-Json)
 $seqProgress=@{brokerRunId=$seqAuth.brokerRunId;approvedOrder=$seqOrder;attempts=@()}
 Write-SeqJson $seqProgressPath $seqProgress
 foreach($slug in $seqOrder){
  $null=Gate
  $terminal=Read-SeqJson (Join-Path $seqOut 'results/task-277.json')
  if($terminal.acceptance.valid -or $terminal.terminalProtocolFailure -or $terminal.terminalTimeoutFailure){Phase 'terminal_preserved' $terminal.runId;break}
  foreach($other in $seqOrder){$path=Join-Path $seqOut "$other-last-authorization.json";$a=Read-SeqJson $path;$a.armed=$false;Write-SeqJson $path $a}
  $path=Join-Path $seqOut "$slug-last-authorization.json";$a=Read-SeqJson $path;$a.armed=$true;$a|Add-Member brokerRunId $seqAuth.brokerRunId -Force;Write-SeqJson $path $a
  $holdPath=Join-Path $seqOut 'upstream-timeout-hold.json';$hold=Read-SeqJson $holdPath;$hold.requested=$false;$hold|Add-Member releaseReason "Root-approved one-segment supplier sequence: $slug" -Force;Write-SeqJson $holdPath $hold
  $attempt=@{slug=$slug;phase='launch_reserved';atUtc=[DateTime]::UtcNow.ToString('o')};$seqProgress.attempts+=,$attempt;Write-SeqJson $seqProgressPath $seqProgress
  Phase 'starting_supplier' $attempt
  & (Join-Path $PSScriptRoot "start-$slug-last.ps1")
  $r=Read-SeqJson (Join-Path $seqOut 'runner-process.json');if($r.providerSlug -ne $slug){throw 'Runner receipt supplier mismatch'}
  $attempt.pid=$r.pid;$attempt.phase='running';Write-SeqJson $seqProgressPath $seqProgress;Phase 'running_supplier' $attempt
  while(Live-Receipt (Join-Path $seqOut 'runner-process.json')){Start-Sleep -Seconds 5}
  $a.armed=$false;Write-SeqJson $path $a
  $s=Read-SeqJson (Join-Path $seqOut 'status.json')
  if($s.runnerPid -ne $r.pid -or !$s.runOut){throw 'No authentic completed runner status; no next supplier'}
  $auditText=& bun (Join-Path $PSScriptRoot 'supplier-sequence-audit.ts') $s.runOut $slug $seqBaselinePath
  if($LASTEXITCODE -ne 0){throw 'Native closure audit failed; no next supplier'}
  $audit=$auditText|ConvertFrom-Json
  $health=Invoke-RestMethod ((Read-SeqJson (Join-Path $seqRoot 'docs/repair-2026-10-10/full-f-rerun/control.json')).broker.endpoint+'/health') -TimeoutSec 10
  if($health.runId -ne $seqAuth.brokerRunId){throw 'Broker changed during closure'}
  $lane=@($health.lanes|Where-Object {$_.runId -eq $s.runId})
  if($lane.Count -ne 1 -or !$lane[0].closed -or $lane[0].active -ne 0 -or $lane[0].providerSlug -ne $slug){throw 'Real broker lane not closed/drained/supplier bound'}
  foreach($e in $audit.engines){$live=Get-CimInstance Win32_Process -Filter "ProcessId=$($e.pid)";if($live -and $live.CommandLine.Contains('app/src/main.ts')){throw 'Owned engine remains alive'}}
  $attempt.phase='native_closed';$attempt.audit=$audit;Write-SeqJson $seqProgressPath $seqProgress;Phase 'supplier_native_closed' $attempt
  if($audit.decision -eq 'terminal'){Phase 'terminal' $audit;break}
  if($audit.decision -ne 'next_supplier'){throw 'No authorization for alternative supplier'}
 }
 Phase 'sequence_stopped' $seqProgress
} catch {if($seqLock){Phase 'sequence_error' @{error=$_.Exception.Message}};throw}
finally {
 if($seqOwn){
 foreach($slug in $seqOrder){$path=Join-Path $seqOut "$slug-last-authorization.json";if(Test-Path $path){$a=Read-SeqJson $path;$a.armed=$false;Write-SeqJson $path $a}}
 $path=Join-Path $seqOut 'upstream-timeout-hold.json';$hold=Read-SeqJson $path;$hold.requested=$true;Write-SeqJson $path $hold
 $path=Join-Path $seqOut 'supplier-sequence-authorization.json';$a=Read-SeqJson $path;$a.armed=$false;Write-SeqJson $path $a
 }
 if($seqLock){$seqLock.Dispose()}
}
