$ErrorActionPreference = 'Stop'
$stopHome = Join-Path (Get-Location).Path 'docs/repair-2026-10-10/full-f-rerun'
$stopControl = Get-Content -LiteralPath (Join-Path $stopHome 'control.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$stopHealth = Get-Content -LiteralPath $stopControl.broker.healthPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $stopHealth.dispatchPaused -or $stopHealth.activeRequests -ne 0 -or $stopHealth.queuedRequests -ne 0 -or @($stopHealth.resourceSlots).Count -ne 0) { throw 'broker_not_idle_for_human_stop' }
$stopPid = [int]$stopControl.broker.pid
if ($stopPid -ne 311252 -or $stopControl.broker.runId -ne 'repair-2026-10-11T11-50-05-363Z') { throw 'original_broker_identity_mismatch' }
$stopNative = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $stopPid)
if (-not $stopNative -or $stopNative.Name -ne 'bun.exe' -or $stopNative.CreationDate.ToUniversalTime().ToString('o') -ne '2026-10-11T11:50:05.2493020Z' -or $stopNative.CommandLine -notlike '*full-f*shared*digitalocean-broker-dynamic-sixteen-actual-disk.next.ts*--serve*') { throw 'original_broker_CIM_mismatch' }
$stopFolder = Join-Path $stopHome ('root-human-stop-broker/' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ'))
New-Item -ItemType Directory -Path $stopFolder | Out-Null
Copy-Item -LiteralPath $stopControl.broker.healthPath -Destination (Join-Path $stopFolder 'original-health-before-stop.json')
$stopPins = @()
foreach ($stopLane in $stopHealth.lanes) {
  if ($stopLane.closed) { continue }
  foreach ($stopRelative in @('cash/cash-config.json','cash/cash-events.jsonl','journal/api-events.jsonl','journal/journal-config.json','journal/journal-state.json')) {
    $stopPath = Join-Path $stopLane.output $stopRelative
    if (Test-Path -LiteralPath $stopPath -PathType Leaf) {
      $stopHash = (Get-FileHash -LiteralPath $stopPath -Algorithm SHA256).Hash.ToLowerInvariant()
      $stopCopy = Join-Path $stopFolder ($stopLane.slug + '-' + $stopRelative.Replace('/','-'))
      Copy-Item -LiteralPath $stopPath -Destination $stopCopy
      if ((Get-FileHash -LiteralPath $stopCopy -Algorithm SHA256).Hash.ToLowerInvariant() -ne $stopHash) { throw 'cash_preservation_sha_mismatch' }
      $stopPins += [pscustomobject]@{path=$stopPath;archivePath=$stopCopy;sha256=$stopHash;bytes=(Get-Item -LiteralPath $stopPath).Length}
    }
  }
}
$stopRecord = [ordered]@{atUtc=[DateTime]::UtcNow.ToString('o');humanRequestedStop=$true;pid=$stopPid;birthUtc=$stopNative.CreationDate.ToUniversalTime().ToString('o');commandSha256=$null;activeRequests=0;queuedRequests=0;resources=0;openCashLaneCount=@($stopHealth.lanes | Where-Object {-not $_.closed}).Count;cashNormallyReleased=$false;originalCanonicalLockDeleted=$false;note='Human requested process stop after task/resource shutdown. Original incomplete cash journal retained, not a normal cash closure or invoice. No Docker/WSL operations.';cashPins=$stopPins}
$stopHasher = [System.Security.Cryptography.SHA256]::Create()
$stopRecord.commandSha256 = ([BitConverter]::ToString($stopHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($stopNative.CommandLine)))).Replace('-','').ToLowerInvariant()
$stopRecord | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $stopFolder 'stop-intent.json') -Encoding UTF8
Stop-Process -Id $stopPid -ErrorAction Stop
Start-Sleep -Milliseconds 400
if (Get-CimInstance Win32_Process -Filter ('ProcessId=' + $stopPid)) { throw 'broker_still_alive' }
$stopRecord.processAbsentVerified=$true
$stopRecord | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $stopFolder 'stop-receipt.json') -Encoding UTF8
[pscustomobject]@{receiptPath=(Join-Path $stopFolder 'stop-receipt.json');pid=$stopPid;processAbsentVerified=$true;openCashLaneCount=$stopRecord.openCashLaneCount;cashNormallyReleased=$false;modelCalls=0} | ConvertTo-Json -Compress
