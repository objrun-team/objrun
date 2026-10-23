[CmdletBinding()]
param(
    [ValidateSet('Gate','Acquire')][string]$Stage='Gate',
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ReviewSha
)
$ErrorActionPreference='Stop'
$ProjectRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ReviewPath=Join-Path $ProjectRoot 'docs/repair-2026-10-08/minif2f-public-cache-bulk-review.json'
$Review=Get-Content -LiteralPath $ReviewPath -Raw | ConvertFrom-Json
if ((Get-FileHash -LiteralPath $ReviewPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ReviewSha -or $Review.protocol -cne 'public-cache-explicit-bulk-source-review-v1' -or $Review.validated -ne $true) { throw 'Explicit bulk review pin/contract differs.' }
foreach ($entry in @($Review.new_sources)+@($Review.protected_sources)) {
    if ((Get-Item -LiteralPath $entry.path).Length -ne $entry.bytes -or (Get-FileHash -LiteralPath $entry.path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry.sha256) { throw 'Reviewed bulk/protected source changed.' }
}
$Python=Join-Path $ProjectRoot '.phase1-data/venv/Scripts/python.exe'
$Worker=Join-Path $PSScriptRoot 'minif2f_public_cache_bulk_stage.py'
# Root reviews and launches Gate and Acquire separately. Existing bulk intents
# never receive another allowance. No Range, candidate, Lean, or model calls.
& $Python -B -X utf8 $Worker $Stage.ToLowerInvariant() --review-sha $ReviewSha
if ($LASTEXITCODE -ne 0) { throw 'Explicit bulk aborted; preserve every intent/partial/receipt. No automatic retry, allowance reset, or deadline extension.' }
