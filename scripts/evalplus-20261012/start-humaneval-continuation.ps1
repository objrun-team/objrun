param([int]$WaitForPid=0)
$ErrorActionPreference='Stop'
$epRoot='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$epOut=Join-Path $epRoot 'docs\evalplus-20261012\humaneval\full'
$epPin=Get-Content -LiteralPath (Join-Path $epRoot 'docs\evalplus-20261012\humaneval\continuation-source-pins.json') -Raw | ConvertFrom-Json
foreach ($epRow in $epPin.files) { if ((Get-FileHash -LiteralPath $epRow.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $epRow.sha256) { throw "HumanEval continuation source changed: $($epRow.path)" } }
if ($WaitForPid -gt 0) {
  $epOriginal=Get-CimInstance Win32_Process -Filter "ProcessId=$WaitForPid"
  if ($epOriginal -and ($epOriginal.Name -ne 'bun.exe' -or $epOriginal.CommandLine -notmatch 'run\.ts\s+humaneval\s+full')) { throw 'Wait target is not the authorized HumanEval runner.' }
  $epBorn=if($epOriginal){$epOriginal.CreationDate}else{$null}
  @{pid=$PID;createdUtc=[DateTime]::UtcNow.ToString('o');waitingForRunner=$WaitForPid;waitingForBirth=$epBorn;dockerForbidden=$true} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $epOut 'continuation-supervisor.json') -Encoding utf8
  while ($epOriginal) {
    Start-Sleep -Seconds 10
    $epOriginal=Get-CimInstance Win32_Process -Filter "ProcessId=$WaitForPid"
    if ($epOriginal -and $epOriginal.CreationDate -ne $epBorn) { throw 'Wait target PID was reused.' }
  }
}
$epLive=Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'bun.exe' -and $_.CommandLine -match 'run(?:-humaneval-continuation)?\.ts\s+humaneval\s+full' }
if ($epLive) { $epLive | Select-Object ProcessId,CreationDate,CommandLine | ConvertTo-Json; exit 0 }
$epPending=@(Get-ChildItem -LiteralPath (Join-Path $epOut 'calls') -Recurse -Filter dispatch.json | Where-Object { -not (Test-Path -LiteralPath (Join-Path $_.DirectoryName 'receipt.json')) })
if ($epPending.Count) { throw 'Unreceipted dispatches need reconciliation before continuation.' }
foreach ($epRow in $epPin.files) { if ((Get-FileHash -LiteralPath $epRow.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $epRow.sha256) { throw "HumanEval continuation source changed: $($epRow.path)" } }
$epStamp=Get-Date -Format yyyyMMddTHHmmss
$epProc=Start-Process -FilePath 'C:\Users\y1252\AppData\Roaming\npm\node_modules\bun\bin\bun.exe' -ArgumentList @('run','scripts/evalplus-20261012/run-humaneval-continuation.ts','humaneval','full') -WorkingDirectory $epRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$epOut/stdout-$epStamp.log" -RedirectStandardError "$epOut/stderr-$epStamp.log"
@{pid=$epProc.Id;createdUtc=[DateTime]::UtcNow.ToString('o');dataset='humaneval';phase='full';stdout="$epOut/stdout-$epStamp.log";stderr="$epOut/stderr-$epStamp.log";dockerForbidden=$true;runner='HumanEval continuation; one transient interface retry per request; task-local failures'} | ConvertTo-Json | Set-Content -LiteralPath "$epOut/launch.json" -Encoding utf8
Get-Content -LiteralPath "$epOut/launch.json" -Raw
