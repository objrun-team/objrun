$ErrorActionPreference='Stop'
$ceRoot='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$ceOut=Join-Path $ceRoot 'docs\newbench-20261014\classeval'
New-Item -ItemType Directory -Force -Path $ceOut | Out-Null
$ceLive=Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'bun.exe' -and $_.CommandLine -match 'newbench-20261014[/\\]classeval[/\\]run\.ts'}
if($ceLive){$ceLive | Select-Object ProcessId,CreationDate,CommandLine | ConvertTo-Json; exit 0}
$ceCfg=Get-Content -LiteralPath (Join-Path $ceRoot 'scripts/newbench-20261014/classeval/experiment.json') -Raw|ConvertFrom-Json
$ceStamp=Get-Date -Format yyyyMMddTHHmmss
$ceProc=Start-Process -FilePath 'C:\Users\y1252\AppData\Roaming\npm\node_modules\bun\bin\bun.exe' -ArgumentList @('run','scripts/newbench-20261014/classeval/run.ts','run') -WorkingDirectory $ceRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$ceOut/stdout-$ceStamp.log" -RedirectStandardError "$ceOut/stderr-$ceStamp.log"
@{pid=$ceProc.Id;createdUtc=[DateTime]::UtcNow.ToString('o');entry='scripts/newbench-20261014/classeval/run.ts';stdout="$ceOut/stdout-$ceStamp.log";stderr="$ceOut/stderr-$ceStamp.log";mode='controls, canary, auto full';concurrency=$ceCfg.concurrency}|ConvertTo-Json|Set-Content -LiteralPath "$ceOut/launch.json" -Encoding utf8
Get-Content -LiteralPath "$ceOut/launch.json" -Raw
