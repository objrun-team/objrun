param()
$ErrorActionPreference='Stop'
$epRoot='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$epOut=Join-Path $epRoot 'docs\evalplus-20261012\mbpp\objrun-adapter-v1\full'
$epPython='D:\ProgramData\anaconda3\python.exe'
$epLive=Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'bun.exe' -and $_.CommandLine -match 'run-mbpp-(objrun-adapter|interface-recovery)\.ts'}
if($epLive){$epLive|Select-Object ProcessId,CreationDate,CommandLine|ConvertTo-Json;exit 0}
$epReady=$false
$epActive=Join-Path $epOut 'recovery\active-pass.json'
if(Test-Path -LiteralPath $epActive){
 $epRef=Get-Content -LiteralPath $epActive -Raw|ConvertFrom-Json
 $epRecord=Get-Content -LiteralPath $epRef.path -Raw|ConvertFrom-Json
 $epReady=$epRecord.state -eq 'ready'
}
if($epReady){& $epPython (Join-Path $epRoot 'scripts\evalplus\prepare-mbpp-interface-recovery.py') --check-ready}
else{
 $epPlanText=& $epPython (Join-Path $epRoot 'scripts\evalplus\prepare-mbpp-interface-recovery.py') --apply
 if($LASTEXITCODE -ne 0){throw 'MBPP recovery preparation failed'}
 $epPlan=$epPlanText|ConvertFrom-Json
 if(-not $epPlan.launchRequired){$epPlanText;exit 0}
 $epRef=Get-Content -LiteralPath $epActive -Raw|ConvertFrom-Json
}
if($LASTEXITCODE -ne 0){throw 'MBPP recovery safety check failed'}
$epStamp=Get-Date -Format yyyyMMddTHHmmss
$epProc=Start-Process -FilePath 'C:\Users\y1252\AppData\Roaming\npm\node_modules\bun\bin\bun.exe' -ArgumentList @('run','scripts/evalplus/run-mbpp-interface-recovery.ts','mbpp','full','full') -WorkingDirectory $epRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$epOut/recovery-stdout-$epStamp.log" -RedirectStandardError "$epOut/recovery-stderr-$epStamp.log"
@{pid=$epProc.Id;createdUtc=[DateTime]::UtcNow.ToString('o');dataset='mbpp';mode='full';version='objrun-adapter-v1';interfaceRecoveryRevision=1;recoveryRound=$epRef.round;stdout="$epOut/recovery-stdout-$epStamp.log";stderr="$epOut/recovery-stderr-$epStamp.log";dockerForbidden=$true}|ConvertTo-Json|Set-Content -LiteralPath "$epOut/launch.json" -Encoding utf8
Get-Content -LiteralPath "$epOut/launch.json" -Raw
