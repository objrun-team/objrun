param([ValidateSet('recovery')][string]$Mode='recovery')
$ErrorActionPreference='Stop'
function Get-PinnedHash([string]$epPath){
  $epHasher=[System.Security.Cryptography.SHA256]::Create()
  $epStream=[System.IO.File]::OpenRead($epPath)
  try{return ([BitConverter]::ToString($epHasher.ComputeHash($epStream))).Replace('-','').ToLowerInvariant()}
  finally{$epStream.Dispose();$epHasher.Dispose()}
}
$epRoot='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$epOut=Join-Path $epRoot "docs\evalplus-20261012\humaneval\objrun-fireworks-v1\$Mode"
New-Item -ItemType Directory -Force -Path $epOut | Out-Null
$epPin=Get-Content -LiteralPath (Join-Path $epRoot 'docs\evalplus-20261012\humaneval\objrun-fireworks-v1-source-pins.json') -Raw|ConvertFrom-Json
foreach($epRow in $epPin.files){if((Get-PinnedHash $epRow.path) -ne $epRow.sha256){throw "ObjRun adapter source changed: $($epRow.path)"}}
$epLive=Get-CimInstance Win32_Process|Where-Object{$_.Name -eq 'bun.exe' -and $_.CommandLine -match 'run-humaneval-objrun-fireworks\.ts'}
$epOldLive=Get-CimInstance Win32_Process|Where-Object{$_.Name -eq 'bun.exe' -and $_.CommandLine -match 'run-humaneval-objrun-adapter\.ts'}
if($epOldLive){throw 'Original HumanEval runner is still live; wait for its natural exit'}
if($epLive){$epLive|Select-Object ProcessId,CreationDate,CommandLine|ConvertTo-Json;exit 0}
$epStamp=Get-Date -Format yyyyMMddTHHmmss
$epProc=Start-Process -FilePath 'C:\Users\y1252\AppData\Roaming\npm\node_modules\bun\bin\bun.exe' -ArgumentList @('run','scripts/evalplus/run-humaneval-objrun-fireworks.ts','humaneval','full',$Mode) -WorkingDirectory $epRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$epOut/stdout-$epStamp.log" -RedirectStandardError "$epOut/stderr-$epStamp.log"
$epIdentity=Get-CimInstance Win32_Process -Filter ('ProcessId='+$epProc.Id)
@{pid=$epProc.Id;processBirthUtc=$epIdentity.CreationDate.ToUniversalTime().ToString('o');provider='Fireworks';createdUtc=[DateTime]::UtcNow.ToString('o');dataset='humaneval';mode=$Mode;version='objrun-fireworks-v1';stdout="$epOut/stdout-$epStamp.log";stderr="$epOut/stderr-$epStamp.log";dockerForbidden=$true}|ConvertTo-Json|Set-Content -LiteralPath "$epOut/launch.json" -Encoding utf8
Get-Content -LiteralPath "$epOut/launch.json" -Raw
