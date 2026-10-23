param([switch]$Inspect)
$ErrorActionPreference='Stop'
$chemRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../../..')).Path
$chemOut=Join-Path $chemRoot 'docs/repair-2026-10-10/full-f-rerun/chembench'
function Read-ChemJson([string]$path){Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json}
if($Inspect){
  $chemState=Read-ChemJson (Join-Path $chemOut 'status.json')
  @{supervisorPolicy='same frozen run.ts; closed segment resumes unfinished tasks';stage=$chemState.stage;externalCalls=0;inspectOnly=$true}|ConvertTo-Json
  exit
}
$chemSupervisorReceipt=Join-Path $chemOut 'supervisor-process.json'
if(Test-Path -LiteralPath $chemSupervisorReceipt){
  $chemPrevious=Read-ChemJson $chemSupervisorReceipt
  $chemPreviousProc=Get-CimInstance Win32_Process -Filter "ProcessId=$($chemPrevious.pid)"
  if($chemPreviousProc -and $chemPreviousProc.CommandLine -like '*chembench*supervise.ps1*'){throw 'Supervisor already active'}
}
@{pid=$PID;entry=$PSCommandPath;startedAtUtc=[DateTime]::UtcNow.ToString('o');kind='background-segment-supervisor';hidden=$true}|ConvertTo-Json|Set-Content -LiteralPath $chemSupervisorReceipt -Encoding UTF8
while($true){
  try{
    $chemState=Read-ChemJson (Join-Path $chemOut 'status.json')
    if($chemState.fullScheduleExhausted -or $chemState.stage -in @('complete','complete_with_protocol_failures')){break}
    $chemRunnerReceipt=Join-Path $chemOut 'runner-process.json'
    $chemRunner=$null
    if(Test-Path -LiteralPath $chemRunnerReceipt){
      $chemRunnerInfo=Read-ChemJson $chemRunnerReceipt
      $chemCandidate=Get-CimInstance Win32_Process -Filter "ProcessId=$($chemRunnerInfo.pid)"
      if($chemCandidate -and $chemCandidate.CommandLine -like '*chembench*run.ts*'){$chemRunner=$chemCandidate}
    }
    if(-not $chemRunner){
      $chemControl=Read-ChemJson (Join-Path $chemRoot 'docs/repair-2026-10-10/full-f-rerun/control.json')
      $chemHold=$false
      $chemHandoffPath=Join-Path $chemOut 'round-handoff-request.json'
      if(Test-Path -LiteralPath $chemHandoffPath){
        $chemHandoff=Read-ChemJson $chemHandoffPath
        $chemBroker=Read-ChemJson $chemControl.broker.healthPath
        if($chemHandoff.requested){
          if(-not $chemBroker.runId -or ($chemBroker.runId -eq $chemHandoff.brokerRunId -and $chemBroker.round -lt 1)){throw 'Parent round evidence unavailable'}
          if($chemHandoff.protocol -ne 'chembench-round-handoff-v1' -or -not $chemHandoff.requestId -or $chemHandoff.releaseAfterRound -lt 1){throw 'Invalid round handoff request'}
          $chemHold=$chemBroker.runId -eq $chemHandoff.brokerRunId -and $chemBroker.round -le $chemHandoff.releaseAfterRound
          if($chemHold){@{atUtc=[datetime]::UtcNow.ToString('o');stage='waiting_parent_round';requestId=$chemHandoff.requestId;brokerRunId=$chemBroker.runId;round=$chemBroker.round;noLaneReclaimed=$true}|ConvertTo-Json|Set-Content (Join-Path $chemOut 'round-handoff-supervisor.json') -Encoding UTF8}
          else{@{atUtc=[datetime]::UtcNow.ToString('o');stage='parent_round_advanced_resume';requestId=$chemHandoff.requestId;brokerRunId=$chemBroker.runId;round=$chemBroker.round}|ConvertTo-Json|Set-Content (Join-Path $chemOut 'round-handoff-supervisor.json') -Encoding UTF8}
        }
      }
      if($chemControl.paidReady -and -not $chemHold){& (Join-Path $PSScriptRoot 'start.ps1')}
    }
    @{pid=$PID;atUtc=[DateTime]::UtcNow.ToString('o');stage=$chemState.stage;runnerPresent=[bool]$chemRunner;parametersChanged=$false;costPolicy='record_and_continue'}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $chemOut 'supervisor-status.json') -Encoding UTF8
  }catch{
    @{pid=$PID;atUtc=[DateTime]::UtcNow.ToString('o');error=$_.Exception.Message}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $chemOut 'supervisor-error.json') -Encoding UTF8
  }
  Start-Sleep -Seconds 60
}
