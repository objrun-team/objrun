[CmdletBinding()]
param(
    [ValidateSet('Gate', 'Workspace', 'Controls', 'Candidates')]
    [string]$Stage = 'Gate',
    [string]$ReviewSha
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ReviewPath = Join-Path $ProjectRoot 'docs\repair-2026-10-08\minif2f-native-v3-review.json'
$HostScript = Join-Path $PSScriptRoot 'minif2f_native_v3_stage.py'
$Python = Join-Path $ProjectRoot '.phase1-data\venv\Scripts\python.exe'
$Review = Get-Content -LiteralPath $ReviewPath -Raw | ConvertFrom-Json
foreach ($Entry in $Review.files) {
    if ((Get-Item -LiteralPath $Entry.path).Length -ne $Entry.bytes -or
        (Get-FileHash -LiteralPath $Entry.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Entry.sha256) {
        throw ('Independent v3 reviewed file changed: ' + $Entry.path)
    }
}
if ($Review.protocol -ne 'reconstructed-lean-dsl-workspace-v3-fast-v2') { throw 'Unexpected independent v3 protocol.' }
if ($Stage -ne 'Gate' -and ($ReviewSha -notmatch '^[0-9a-f]{64}$' -or
    (Get-FileHash -LiteralPath $ReviewPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ReviewSha)) {
    throw 'An exact root-reviewed independent v3 review SHA is required for an E stage.'
}
$HostArgs = @('-X','utf8',$HostScript,'--stage',$Stage,'--review',$ReviewPath)
if ($ReviewSha) { $HostArgs += @('--review-sha',$ReviewSha) }
& $Python @HostArgs
if ($LASTEXITCODE -ne 0) { throw 'Native v3 stage refused/failed; preserve its original receipt and logs before any retry.' }
