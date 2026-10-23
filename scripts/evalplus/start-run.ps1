param([Parameter(Mandatory=$true)][ValidateSet('humaneval','mbpp')] [string]$Dataset,[ValidateSet('pilot','full')][string]$Phase='full')
$ErrorActionPreference='Stop'
$epRoot='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$epDir=Join-Path $epRoot "docs/evalplus-20261012/$Dataset/$Phase"
New-Item -ItemType Directory -Force -Path $epDir | Out-Null
# No Docker, Docker Desktop, Compose, containers or automatic container fallback.
if(Test-Path -LiteralPath "$epDir/runner-lock.json") {
 $epLock=Get-Content -LiteralPath "$epDir/runner-lock.json" -Raw | ConvertFrom-Json
 $epLive=Get-CimInstance Win32_Process -Filter "ProcessId=$($epLock.pid)"
 if($epLive -and $epLive.CommandLine -like "*evalplus-20261012*run.ts*$Dataset*$Phase*") { $epLive | Select-Object ProcessId,CreationDate,CommandLine | ConvertTo-Json; exit 0 }
}
$epStamp=Get-Date -Format yyyyMMddTHHmmss
$epProc=Start-Process -FilePath 'C:\Users\y1252\AppData\Roaming\npm\node_modules\bun\bin\bun.exe' -ArgumentList @('run','scripts/evalplus/run.ts',$Dataset,$Phase) -WorkingDirectory $epRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$epDir/stdout-$epStamp.log" -RedirectStandardError "$epDir/stderr-$epStamp.log"
@{pid=$epProc.Id;createdUtc=[DateTime]::UtcNow.ToString('o');dataset=$Dataset;phase=$Phase;stdout="$epDir/stdout-$epStamp.log";stderr="$epDir/stderr-$epStamp.log";dockerForbidden=$true} | ConvertTo-Json | Set-Content -LiteralPath "$epDir/launch.json" -Encoding utf8
Get-Content -LiteralPath "$epDir/launch.json" -Raw
