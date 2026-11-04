$ErrorActionPreference='Stop'
$epRoot='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$epOut=Join-Path $epRoot 'docs\evalplus-20261012\humaneval\full'
$epPin=Get-Content -LiteralPath (Join-Path $epRoot 'docs\evalplus-20261012\humaneval\independent-fixed5-source-pins.json') -Raw | ConvertFrom-Json
foreach($epRow in $epPin.files){if((Get-FileHash -LiteralPath $epRow.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $epRow.sha256){throw "Fixed-five source changed: $($epRow.path)"}}
$epLive=Get-CimInstance Win32_Process|Where-Object{$_.Name -eq 'bun.exe' -and $_.CommandLine -match '(?:run(?:-humaneval-continuation(?:-v2)?)?\.ts\s+humaneval\s+full|run-humaneval-fixed5\.ts)'}
if($epLive){$epLive|Select-Object ProcessId,CreationDate,CommandLine|ConvertTo-Json;exit 0}
$epStamp=Get-Date -Format yyyyMMddTHHmmss
$epProc=Start-Process -FilePath 'C:\Users\y1252\AppData\Roaming\npm\node_modules\bun\bin\bun.exe' -ArgumentList @('run','examples/benchmark/evalplus/run-humaneval-fixed5.ts','humaneval','full') -WorkingDirectory $epRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$epOut/stdout-fixed5-$epStamp.log" -RedirectStandardError "$epOut/stderr-fixed5-$epStamp.log"
@{pid=$epProc.Id;createdUtc=[DateTime]::UtcNow.ToString('o');dataset='humaneval';phase='full';stdout="$epOut/stdout-fixed5-$epStamp.log";stderr="$epOut/stderr-fixed5-$epStamp.log";dockerForbidden=$true;runner='Independent fixed five; max_tokens=16384; correct solution stops task'}|ConvertTo-Json|Set-Content -LiteralPath "$epOut/launch.json" -Encoding utf8
Get-Content -LiteralPath "$epOut/launch.json" -Raw
