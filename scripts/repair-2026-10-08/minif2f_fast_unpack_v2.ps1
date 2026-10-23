[CmdletBinding()]
param(
    [ValidateSet('Gate','Batch')][string]$Stage='Gate',
    [ValidateRange(1,64)][int]$Count=2,
    [string]$ReviewedPythonSha256=''
)
$ErrorActionPreference='Stop'
$taskProject='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$taskPython=Join-Path $taskProject '.phase1-data\venv\Scripts\python.exe'
$taskWorker=Join-Path $PSScriptRoot 'minif2f_fast_unpack_v2.py'
if([IO.Path]::GetFullPath($taskWorker) -ne (Join-Path $taskProject 'scripts\repair-2026-10-08\minif2f_fast_unpack_v2.py')){throw 'Independent v2 entry is outside the exact reviewed project path.'}
if($Stage -eq 'Batch'){
    if($ReviewedPythonSha256 -notmatch '^[0-9a-f]{64}$' -or (Get-FileHash -LiteralPath $taskWorker -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ReviewedPythonSha256){throw 'V2 Batch requires its exact new root-reviewed Python SHA.'}
    & $taskPython -B -X utf8 $taskWorker batch --count $Count --review-sha $ReviewedPythonSha256
}else{
    & $taskPython -B -X utf8 $taskWorker gate
}
if($LASTEXITCODE -ne 0){throw 'V2 fast phase is invalid. Preserve original objects, metadata, outputs and owner records; no automatic retry or repair.'}
