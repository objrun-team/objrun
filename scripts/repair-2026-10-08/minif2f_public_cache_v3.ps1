[CmdletBinding()]
param(
    [ValidateSet('Gate','Acquire')][string]$Stage='Gate',
    [ValidateRange(1,4)][int]$Workers=4,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ReviewSha
)
$ErrorActionPreference='Stop'
$ProjectRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ReviewPath=Join-Path $ProjectRoot 'docs\repair-2026-10-08\minif2f-public-cache-v3-review.json'
$ProfilePath=Join-Path $ProjectRoot 'docs\repair-2026-10-08\minif2f-restoration-preflight.json'
if ((Get-FileHash -LiteralPath $ReviewPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ReviewSha) { throw 'Independent body-v3 review hash differs.' }
if ((Get-FileHash -LiteralPath $ProfilePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'f23ebc252a02cf9a407db4fb2045f6c8dba064e1706e97d28fc6ff96ac2a5fd3') { throw 'Original Profile bytes changed.' }
$Review=Get-Content -LiteralPath $ReviewPath -Raw | ConvertFrom-Json
if ($Review.protocol -ne 'public-cache-body-v3-source-review-v1' -or $Review.validated -ne $true) { throw 'Body-v3 review not validated.' }
foreach ($entry in @($Review.new_sources)+@($Review.protected_sources)) {
    if ((Get-Item -LiteralPath $entry.path).Length -ne $entry.bytes -or (Get-FileHash -LiteralPath $entry.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw 'Reviewed body-v3/protected source changed.' }
}
$Python=Join-Path $ProjectRoot '.phase1-data\venv\Scripts\python.exe'
$Worker=Join-Path $PSScriptRoot 'minif2f_public_cache_v3.py'
$Core=Join-Path $PSScriptRoot 'minif2f_restore.py'
$Public=Join-Path $ProjectRoot '.phase1-data\minif2f-restoration-public'
$CacheRoot='E:\objrun-experiment-cache\01a119ed-fdf7-7c32-b323-de9bab1290b6\minif2f-v415'
$phase=if ($Stage -eq 'Acquire') {'acquire'} else {'gate'}
# Only root may schedule this after the old acquisition has naturally closed
# and every unknown partial has been separately preserved/reviewed.
& $Python -B -X utf8 $Worker $phase --root $CacheRoot --public $Public --core $Core --workers $Workers --review $ReviewPath --review-sha $ReviewSha
if ($LASTEXITCODE -ne 0) { throw 'Body-v3 aborted. Keep original receipts, every failed-prefix artifact/journal and any unknown canonical part for exact review.' }
