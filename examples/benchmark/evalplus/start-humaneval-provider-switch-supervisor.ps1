$ErrorActionPreference='Stop'
function Get-PinnedHash([string]$epPath){
  $epHasher=[System.Security.Cryptography.SHA256]::Create()
  $epStream=[System.IO.File]::OpenRead($epPath)
  try{return ([BitConverter]::ToString($epHasher.ComputeHash($epStream))).Replace('-','').ToLowerInvariant()}
  finally{$epStream.Dispose();$epHasher.Dispose()}
}
$epRoot='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$epNew=Join-Path $epRoot 'docs\evalplus-20261012\humaneval\objrun-fireworks-v1'
New-Item -ItemType Directory -Force -Path $epNew|Out-Null
$epLive=Get-CimInstance Win32_Process|Where-Object{$_.Name -eq 'powershell.exe' -and $_.CommandLine -match 'supervise-humaneval-provider-switch\.ps1'}
if($epLive){$epLive|Select-Object ProcessId,CreationDate,CommandLine|ConvertTo-Json;exit 0}
$epPins=Get-Content -LiteralPath (Join-Path $epRoot 'docs\evalplus-20261012\humaneval\objrun-fireworks-v1-source-pins.json') -Raw|ConvertFrom-Json
foreach($epPin in $epPins.files){if((Get-PinnedHash $epPin.path) -ne $epPin.sha256){throw ('Provider switch source changed: '+$epPin.path)}}
$epStamp=Get-Date -Format yyyyMMddTHHmmss
$epScript=Join-Path $epRoot 'scripts\evalplus\supervise-humaneval-provider-switch.ps1'
$epProcess=Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',$epScript) -WorkingDirectory $epRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$epNew/supervisor-stdout-$epStamp.log" -RedirectStandardError "$epNew/supervisor-stderr-$epStamp.log"
$epIdentity=Get-CimInstance Win32_Process -Filter ('ProcessId='+$epProcess.Id)
@{pid=$epProcess.Id;processBirthUtc=$epIdentity.CreationDate.ToUniversalTime().ToString('o');createdUtc=[DateTime]::UtcNow.ToString('o');provider='Fireworks';stdout="$epNew/supervisor-stdout-$epStamp.log";stderr="$epNew/supervisor-stderr-$epStamp.log";dockerForbidden=$true}|ConvertTo-Json|Set-Content -LiteralPath "$epNew/switch-supervisor-launch.json" -Encoding utf8
Get-Content -LiteralPath "$epNew/switch-supervisor-launch.json" -Raw
