[CmdletBinding()]
param([ValidateSet('Gate','Restore')][string]$Stage='Gate')
$ErrorActionPreference='Stop'
$ProjectRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Review=Get-Content -LiteralPath (Join-Path $ProjectRoot 'docs/repair-2026-10-08/minif2f-plausible-restoration-review.json') -Raw | ConvertFrom-Json
foreach($Source in $Review.execution_files){
    $Actual=(Get-FileHash -LiteralPath $Source.path -Algorithm SHA256).Hash.ToLowerInvariant()
    if($Actual -ne $Source.sha256){throw 'Reviewed exact source restoration input changed.'}
}
$Python=Join-Path $ProjectRoot '.phase1-data/venv/Scripts/python.exe'
$Phase=if($Stage -eq 'Gate'){'gate'}else{'restore'}
& $Python -B -X utf8 (Join-Path $PSScriptRoot 'minif2f_plausible_restore.py') $Phase `
    --root 'E:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/minif2f-v415' `
    --public (Join-Path $ProjectRoot '.phase1-data/minif2f-restoration-public') `
    --helper (Join-Path $PSScriptRoot 'minif2f_public_cache.py') `
    --core (Join-Path $PSScriptRoot 'minif2f_restore.py')
if($LASTEXITCODE -ne 0){throw 'Exact plausible source restoration/gate failed; preserve all partial/evidence artifacts.'}
