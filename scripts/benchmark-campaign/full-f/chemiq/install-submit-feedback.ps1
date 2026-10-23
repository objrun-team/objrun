$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
Set-Location -LiteralPath $taskRoot
$taskOut=Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/chemiq'
$taskOrigin=Get-Content (Join-Path $taskOut 'active-run.json') -Raw|ConvertFrom-Json
$taskLimit=[DateTime]::UtcNow.AddMinutes(45)
while([DateTime]::UtcNow -lt $taskLimit){
 $taskAlive=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskOrigin.pid)"
 if($taskAlive -and $taskAlive.CommandLine -notlike '*full-f/chemiq/run.ts*'){throw 'Old runner PID reused; no installation'}
 if(!$taskAlive){
  & bun (Join-Path $PSScriptRoot 'install-submit-feedback.mjs') $taskOrigin.runId
  if($LASTEXITCODE -eq 0){
   $taskExisting=Get-CimInstance Win32_Process|Where-Object {$_.CommandLine -like '*-File scripts/benchmark-campaign/full-f/chemiq/guardian.ps1*'}
   if(!$taskExisting){$taskGuard=Start-Process -FilePath (Get-Process -Id $PID).Path -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','scripts/benchmark-campaign/full-f/chemiq/guardian.ps1') -WindowStyle Hidden -PassThru; @{pid=$taskGuard.Id;script='scripts/benchmark-campaign/full-f/chemiq/guardian.ps1';windowStyle='Hidden';digitalOceanOnly=$true;startedAtUtc=[DateTime]::UtcNow.ToString('o');replacesNormallyStoppedGuardian=80484}|ConvertTo-Json|Set-Content (Join-Path $taskOut 'guardian-process.json') -Encoding utf8}
   exit 0
  }
  if($LASTEXITCODE -ne 3){throw 'Native feedback installer failed; preserve evidence and do not launch'}
 }
 @{atUtc=[DateTime]::UtcNow.ToString('o');pid=$PID;runId=$taskOrigin.runId;action='Wait native original runner/process drain then install verified red-green private feedback and recovery; no live source edits'}|ConvertTo-Json|Set-Content (Join-Path $taskOut 'feedback-install-status.json') -Encoding utf8
 Start-Sleep -Seconds 15
}
throw 'Original native closure not reached within45minutes; no installation/launch'
