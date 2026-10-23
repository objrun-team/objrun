param(
  [Parameter(Mandatory=$true)][ValidateSet('Gate','Restore','CheckClosed')][string]$Stage,
  [Parameter(Mandatory=$true)][string]$Review,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ReviewSha256,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ReviewedPythonSha256
)
$ErrorActionPreference='Stop'
$repo = 'F:/git/TgEngin-handoff-2026-10-07/TgEngin'
$source = Join-Path $repo 'scripts/repair-2026-10-08/minif2f_fast_nonzero_recovery.py'
$actualSha = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSha -cne $ReviewedPythonSha256) { throw 'Recovery execution source differs from reviewed bytes' }
& (Join-Path $repo '.phase1-data/venv/Scripts/python.exe') -B -X utf8 $source `
  --stage $Stage --review $Review --review-sha $ReviewSha256
if ($LASTEXITCODE -ne 0) { throw ('Recovery stage exited ' + $LASTEXITCODE) }
