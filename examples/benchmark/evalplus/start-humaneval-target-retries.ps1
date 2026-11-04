$ErrorActionPreference='Stop'
$epRoot='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$epHe=Join-Path $epRoot 'docs\evalplus-20261012\humaneval'
$epOut=Join-Path $epHe 'objrun-retry-to-target-v1'
function Get-PinnedHash([string]$epPath){
 $epHash=[System.Security.Cryptography.SHA256]::Create();$epStream=[System.IO.File]::OpenRead($epPath)
 try{return ([BitConverter]::ToString($epHash.ComputeHash($epStream))).Replace('-','').ToLowerInvariant()}
 finally{$epStream.Dispose();$epHash.Dispose()}
}
$epLive=Get-CimInstance Win32_Process|Where-Object{($_.Name -eq 'python.exe' -and $_.CommandLine -match 'supervise-humaneval-target-retries\.py' -and $_.CommandLine -notmatch '--verify') -or ($_.Name -eq 'bun.exe' -and $_.CommandLine -match 'run-humaneval-objrun-(target-retry|adapter|fireworks)\.ts')}
if($epLive){$epLive|Select-Object ProcessId,Name,CreationDate,CommandLine|ConvertTo-Json;exit 0}
foreach($epManifest in @('source-pins.json','humaneval\objrun-adapter-v1-source-pins.json','humaneval\objrun-fireworks-v1-source-pins.json','humaneval\final-verification-source-pins.json','humaneval\objrun-retry-to-target-v1-source-pins.json')){
 $epPins=Get-Content -LiteralPath (Join-Path $epRoot ('docs\evalplus-20261012\'+$epManifest)) -Raw|ConvertFrom-Json
 foreach($epPin in $epPins.files){if((Get-PinnedHash $epPin.path) -ne $epPin.sha256){throw ('FrozenSourceChanged:'+ $epPin.path)}}
}
$epStamp=Get-Date -Format yyyyMMddTHHmmss
$epScript=Join-Path $epRoot 'scripts\evalplus\supervise-humaneval-target-retries.py'
$epProc=Start-Process -FilePath 'D:\ProgramData\anaconda3\python.exe' -ArgumentList @('-u',$epScript) -WorkingDirectory $epRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$epOut/supervisor-stdout-$epStamp.log" -RedirectStandardError "$epOut/supervisor-stderr-$epStamp.log"
$epIdentity=Get-CimInstance Win32_Process -Filter ('ProcessId='+$epProc.Id)
@{pid=$epProc.Id;processBirthUtc=$epIdentity.CreationDate.ToUniversalTime().ToString('o');createdUtc=[DateTime]::UtcNow.ToString('o');stdout="$epOut/supervisor-stdout-$epStamp.log";stderr="$epOut/supervisor-stderr-$epStamp.log";maxRounds=10;minimumPassed=157;upperTarget=160;dockerForbidden=$true}|ConvertTo-Json|Set-Content -LiteralPath "$epOut/launch.json" -Encoding utf8
Get-Content -LiteralPath "$epOut/launch.json" -Raw
