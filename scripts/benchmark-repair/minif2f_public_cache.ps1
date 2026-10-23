[CmdletBinding()]
param(
    [ValidateSet('Gate', 'Acquire')]
    [string]$Stage = 'Gate',
    [ValidateRange(1,4)]
    [int]$Workers = 4
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$CacheRoot = 'E:\objrun-experiment-cache\01a119ed-fdf7-7c32-b323-de9bab1290b6\minif2f-v415'
$PublicRoot = Join-Path $ProjectRoot '.phase1-data\minif2f-restoration-public'
$ProfilePath = Join-Path $ProjectRoot 'docs\repair-2026-10-08\minif2f-restoration-preflight.json'
$Python = Join-Path $ProjectRoot '.phase1-data\venv\Scripts\python.exe'
$Core = Join-Path $PSScriptRoot 'minif2f_restore.py'
$Worker = Join-Path $PSScriptRoot 'minif2f_public_cache.py'
$Profile = Get-Content -LiteralPath $ProfilePath -Raw | ConvertFrom-Json

function Frozen-Sha([string]$Path) {
    $entry = @($Profile.reviewed_plan_files) | Where-Object path -eq $Path
    if (@($entry).Count -ne 1) { throw 'Public acquisition file is not uniquely present in the reviewed plan.' }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.sha256) { throw 'Reviewed public acquisition source bytes changed.' }
    return $actual
}

Frozen-Sha $Core | Out-Null
Frozen-Sha $Worker | Out-Null
Frozen-Sha $PSCommandPath | Out-Null
if ((Get-FileHash -LiteralPath (Join-Path $PublicRoot 'public-lock.json') -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'ee033a2d51ef5f7dc51b573285df3c2d78689fc9edcaaf8781420525c1d8d857') {
    throw 'Frozen public source lock differs.'
}
# This host-only protocol has no container build/execute stage. The Python
# worker checks the 4096-byte allocation unit, exact ownership/reparse paths,
# fixed actual Bootstrap and 5826-key manifest, public byte lock, other local
# writers, actual E/F reserves, and its genuine share-deny acquisition lease.
# Root must schedule this as the sole owned-root writer: old core/runtime
# wrappers are immutable and do not implement the newly introduced lease.
$phase = if ($Stage -eq 'Gate') { 'gate' } else { 'acquire' }
& $Python -B -X utf8 $Worker $phase --root $CacheRoot --public $PublicRoot --core $Core --workers $Workers
if ($LASTEXITCODE -ne 0) {
    throw 'Public cache acquisition/gate failed. Preserve original-hash receipts and inspect unknown/partial artifacts before resuming.'
}
