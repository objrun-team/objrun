[CmdletBinding()]
param(
    [ValidateSet('Gate','Batch')]
    [string]$Stage = 'Gate',
    [ValidateRange(1,64)]
    [int]$Count = 64,
    [string]$ReviewedPythonSha256 = ''
)
$ErrorActionPreference = 'Stop'
$taskProject = 'F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$taskPython = Join-Path $taskProject '.phase1-data\venv\Scripts\python.exe'
$taskWorker = Join-Path $PSScriptRoot 'minif2f_fast_unpack.py'
if ([IO.Path]::GetFullPath($taskWorker) -ne (Join-Path $taskProject 'scripts\benchmark-repair\minif2f_fast_unpack.py')) { throw 'Independent entry is outside the exact reviewed project path.' }
if ($Stage -eq 'Batch') {
    if ($ReviewedPythonSha256 -notmatch '^[0-9a-f]{64}$' -or (Get-FileHash -LiteralPath $taskWorker -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ReviewedPythonSha256) { throw 'Batch requires the exact Python SHA reviewed by root.' }
    & $taskPython -B -X utf8 $taskWorker batch --count $Count --review-sha $ReviewedPythonSha256
} else {
    & $taskPython -B -X utf8 $taskWorker gate
}
if ($LASTEXITCODE -ne 0) { throw 'Fast unpack gate/batch is invalid. Preserve the typed stderr, exact originals, outputs, receipts, .new partials and owner intent; do not retry a failed phase or use the old unpack loop.' }
