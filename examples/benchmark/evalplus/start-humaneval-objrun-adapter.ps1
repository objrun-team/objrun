param([ValidateSet('canary','full')][string]$Mode='full')
$ErrorActionPreference='Stop'
$epRoot='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$epOut=Join-Path $epRoot "docs\evalplus-20261012\humaneval\objrun-adapter-v1\$Mode"
New-Item -ItemType Directory -Force -Path $epOut | Out-Null
$epPin=Get-Content -LiteralPath (Join-Path $epRoot 'docs\evalplus-20261012\humaneval\objrun-adapter-v1-source-pins.json') -Raw|ConvertFrom-Json
foreach($epRow in $epPin.files){if((Get-FileHash -LiteralPath $epRow.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $epRow.sha256){throw "ObjRun adapter source changed: $($epRow.path)"}}
$epLive=Get-CimInstance Win32_Process|Where-Object{$_.Name -eq 'bun.exe' -and $_.CommandLine -match 'run-humaneval-objrun-adapter\.ts'}
if($epLive){$epLive|Select-Object ProcessId,CreationDate,CommandLine|ConvertTo-Json;exit 0}
$epStamp=Get-Date -Format yyyyMMddTHHmmss
$epProc=Start-Process -FilePath 'C:\Users\y1252\AppData\Roaming\npm\node_modules\bun\bin\bun.exe' -ArgumentList @('run','examples/benchmark/evalplus/run-humaneval-objrun-adapter.ts','humaneval','full',$Mode) -WorkingDirectory $epRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$epOut/stdout-$epStamp.log" -RedirectStandardError "$epOut/stderr-$epStamp.log"
@{pid=$epProc.Id;createdUtc=[DateTime]::UtcNow.ToString('o');dataset='humaneval';mode=$Mode;version='objrun-adapter-v1';stdout="$epOut/stdout-$epStamp.log";stderr="$epOut/stderr-$epStamp.log";dockerForbidden=$true}|ConvertTo-Json|Set-Content -LiteralPath "$epOut/launch.json" -Encoding utf8
Get-Content -LiteralPath "$epOut/launch.json" -Raw
