[CmdletBinding()]
param(
    [ValidateSet('Gate','Acquire')][string]$Stage='Gate',
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ReviewSha
)
$ErrorActionPreference='Stop'
$ProjectRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ReviewPath=Join-Path $ProjectRoot 'docs/repair-2026-10-08/minif2f-public-cache-root-carry-review.json'
$Review=Get-Content -LiteralPath $ReviewPath -Raw | ConvertFrom-Json
if ((Get-FileHash -LiteralPath $ReviewPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ReviewSha -or $Review.protocol -cne 'public-cache-root-carry-source-review-v1' -or $Review.validated -ne $true) { throw 'Carry review pin/contract differs.' }
foreach ($entry in @($Review.new_sources)+@($Review.protected_sources)) {
    if ((Get-Item -LiteralPath $entry.path).Length -ne $entry.bytes -or (Get-FileHash -LiteralPath $entry.path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry.sha256) { throw 'Reviewed carry/protected source changed.' }
}
$Python=Join-Path $ProjectRoot '.phase1-data/venv/Scripts/python.exe'
$Worker=Join-Path $PSScriptRoot 'minif2f_public_cache_root_carry.py'
# Root separately reviews and schedules the only E writer. This phase cannot
# acquire any remaining bulk key or publish a5826 cache completion certificate.
& $Python -B -X utf8 $Worker $Stage.ToLowerInvariant() --review-sha $ReviewSha
if ($LASTEXITCODE -ne 0) { throw 'Two-key carry aborted; preserve intent/partial/receipt evidence. Never automatically retry or reset its budget.' }
