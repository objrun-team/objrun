$ErrorActionPreference='Stop'
$epRoot='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$epHe=Join-Path $epRoot 'docs\evalplus-20261012\humaneval'
$epNew=Join-Path $epHe 'objrun-fireworks-v1'
$epState=Join-Path $epNew 'switch-supervisor.json'
$epPython='D:\ProgramData\anaconda3\python.exe'
function Get-PinnedHash([string]$epPath){
  $epHasher=[System.Security.Cryptography.SHA256]::Create()
  $epStream=[System.IO.File]::OpenRead($epPath)
  try{return ([BitConverter]::ToString($epHasher.ComputeHash($epStream))).Replace('-','').ToLowerInvariant()}
  finally{$epStream.Dispose();$epHasher.Dispose()}
}

function Save-State($epValue){
  $epValue.pid=$PID
  $epValue.atUtc=[DateTime]::UtcNow.ToString('o')
  $epTemporary=$epState+'.'+$PID+'.tmp'
  $epValue|ConvertTo-Json -Depth 30|Set-Content -LiteralPath $epTemporary -Encoding utf8
  Move-Item -LiteralPath $epTemporary -Destination $epState -Force
}
function Update-Workflow([string]$epStage,$epChild){
  $epPath=Join-Path $epHe 'workflow-state.json'
  $epWorkflow=Get-Content -LiteralPath $epPath -Raw|ConvertFrom-Json
  $epValues=@{stage=$epStage;providerSwitchSupervisorPid=$PID;providerSwitchAuthorized=$true;atUtc=[DateTime]::UtcNow.ToString('o')}
  if($epChild){
    $epValues.currentRunnerPid=$epChild.pid
    $epValues.activeResultRoot=Join-Path $epNew $epChild.mode
    $epValues.objrunAdapterVersion='objrun-fireworks-v1'
    $epValues.objrunProvider='Fireworks'
    $epValues.objrunResumeCommand=Join-Path $epRoot 'scripts\evalplus\start-humaneval-objrun-fireworks.ps1'
    $epValues.objrunVerificationCommand=Join-Path $epRoot 'scripts\evalplus\verify-humaneval-objrun-fireworks.py'
    $epValues.recoveryPreparationCommand=Join-Path $epRoot 'scripts\evalplus\prepare-humaneval-objrun-fireworks-recovery.py'
    $epValues.recoveryRound=0
    $epValues.objrunProviderSourcePins=Join-Path $epHe 'objrun-fireworks-v1-source-pins.json'
    $epValues.objrunCombinedVerificationCommand=Join-Path $epRoot 'scripts\evalplus\verify-humaneval-supplier-recovery.py'
    $epValues.originalObjrunResultRoot=Join-Path $epHe 'objrun-adapter-v1\full'
    $epValues.supplierSwitchRecoveryOnly=$true
    $epValues.fullRerunAuthorized=$false
  }
  foreach($epName in $epValues.Keys){$epWorkflow|Add-Member -NotePropertyName $epName -NotePropertyValue $epValues[$epName] -Force}
  $epTemporary=$epPath+'.'+$PID+'.tmp'
  $epWorkflow|ConvertTo-Json -Depth 40|Set-Content -LiteralPath $epTemporary -Encoding utf8
  Move-Item -LiteralPath $epTemporary -Destination $epPath -Force
}
try{
  foreach($epPinName in @('source-pins.json','humaneval\objrun-adapter-v1-source-pins.json','humaneval\objrun-validity-recovery-source-pins.json','humaneval\objrun-validity-recovery-v2-source-pins.json','humaneval\objrun-fireworks-v1-source-pins.json')){
    $epPins=Get-Content -LiteralPath (Join-Path $epRoot ('docs\evalplus-20261012\'+$epPinName)) -Raw|ConvertFrom-Json
    foreach($epPin in $epPins.files){if((Get-PinnedHash $epPin.path) -ne $epPin.sha256){throw ('FrozenSourceChanged: '+$epPin.path)}}
  }
  Save-State @{stage='waiting_digitalocean_runner_exit';provider='Fireworks';coreModified=$false}
  while($true){
    $epRaw=& $epPython (Join-Path $epRoot 'scripts\evalplus\prepare-humaneval-objrun-recovery-v2.py')
    if($LASTEXITCODE -ne 0){throw 'Original namespace safety check failed'}
    $epInspection=$epRaw|ConvertFrom-Json
    if(@($epInspection.liveProcesses).Count -gt 0){Start-Sleep -Seconds 15;continue}
    if(@($epInspection.guards).Count -gt 0){throw ('Original namespace needs attention: '+($epInspection.guards -join ', '))}
    break
  }
  $epOld=Join-Path $epHe 'objrun-adapter-v1\full'
  $epOldSummary=Join-Path $epOld 'recovery\validity-pass-0003-completed-summary.json'
  if(-not (Test-Path -LiteralPath $epOldSummary)){
    @{atUtc=[DateTime]::UtcNow.ToString('o');round=3;status=(Get-Content -LiteralPath (Join-Path $epOld 'status.json') -Raw|ConvertFrom-Json);resultRows=@(Get-ChildItem -LiteralPath (Join-Path $epOld 'results\objrun') -Filter '*.json'|ForEach-Object{Get-Content -LiteralPath $_.FullName -Raw|ConvertFrom-Json})}|ConvertTo-Json -Depth 100|Set-Content -LiteralPath $epOldSummary -Encoding utf8
  }
  $epChildRaw=& (Join-Path $epRoot 'scripts\evalplus\start-humaneval-objrun-fireworks.ps1') -Mode recovery
  if($LASTEXITCODE -ne 0){throw 'Fireworks abnormal-task recovery launch failed'}
  $epRecovery=$epChildRaw|ConvertFrom-Json
  Save-State @{stage='fireworks_recovery_running';provider='Fireworks';child=$epRecovery;recoveryOnly=$true;fullRerun=$false;coreModified=$false}
  Update-Workflow 'objrun_fireworks_recovery_running' $epRecovery
}catch{
  Save-State @{stage='needs_attention';provider='Fireworks';error=[string]$_;coreModified=$false}
  Update-Workflow 'objrun_provider_switch_needs_attention' $null
  Write-Error $_
  exit 1
}
