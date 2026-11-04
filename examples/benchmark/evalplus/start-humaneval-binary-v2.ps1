$ErrorActionPreference='Stop'
$hbRoot='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$hbHome=Join-Path $hbRoot 'docs/evalplus-20261012/humaneval/binary-v1'
$hbOut=Join-Path $hbHome 'full'
$hbBun='C:\Users\y1252\AppData\Roaming\npm\node_modules\bun\bin\bun.exe'
foreach($hbName in @('source-pins.json','length-recovery-v2-source-pins.json')){
 $hbPins=Get-Content -LiteralPath "$hbHome/$hbName" -Raw|ConvertFrom-Json
 foreach($hbRow in $hbPins.files){if((Get-FileHash -LiteralPath $hbRow.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hbRow.sha256){throw "Frozen source changed: $($hbRow.path)"}}
}
$hbLive=Get-CimInstance Win32_Process|Where-Object{$_.Name -eq 'bun.exe' -and $_.CommandLine -match 'run-humaneval-binary(?:-v2)?\.ts["\s]+full'}
if($hbLive){$hbLive|Select-Object ProcessId,CreationDate,CommandLine|ConvertTo-Json;return}
$hbDispatch=Get-ChildItem -LiteralPath "$hbOut/calls" -Filter dispatch.json -Recurse -File
foreach($hbCall in $hbDispatch){if(-not(Test-Path -LiteralPath (Join-Path $hbCall.DirectoryName 'receipt.json'))){throw "Pending dispatch: $($hbCall.FullName)"}}
& "$hbRoot/examples/benchmark/evalplus/start-humaneval-binary.ps1" -GraderOnly
& $hbBun run examples/benchmark/evalplus/run-humaneval-binary-v2.ts preflight
if($LASTEXITCODE -ne 0){throw 'Recovery preflight failed'}
$hbLock=Join-Path $hbOut 'runner-lock.json'
if(Test-Path -LiteralPath $hbLock){throw 'Unexpected runner lock; inspect its owner before recovery'}
$hbStamp=Get-Date -Format yyyyMMddTHHmmssfff
Copy-Item -LiteralPath "$hbOut/launch.json" -Destination "$hbOut/launch.before-v2-$hbStamp.json"
Copy-Item -LiteralPath "$hbOut/status.json" -Destination "$hbOut/status.before-v2-$hbStamp.json"
$hbProc=Start-Process -FilePath $hbBun -ArgumentList @('run','examples/benchmark/evalplus/run-humaneval-binary-v2.ts','full') -WorkingDirectory $hbRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$hbOut/stdout-v2-$hbStamp.log" -RedirectStandardError "$hbOut/stderr-v2-$hbStamp.log"
@{pid=$hbProc.Id;createdUtc=[DateTime]::UtcNow.ToString('o');command='run-humaneval-binary-v2.ts full';adapterVersion='length-recovery-v2';stdout="$hbOut/stdout-v2-$hbStamp.log";stderr="$hbOut/stderr-v2-$hbStamp.log";dockerForbidden=$true}|ConvertTo-Json|Set-Content -LiteralPath "$hbOut/launch.json" -Encoding utf8
Get-Content -LiteralPath "$hbOut/launch.json" -Raw
