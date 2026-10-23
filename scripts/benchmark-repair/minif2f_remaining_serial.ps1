[CmdletBinding()]
param(
    [ValidateSet('Gate','Run')][string]$Stage='Gate',
    [Parameter(Mandatory=$true)][string]$Review,
    [Parameter(Mandatory=$true)][string]$ReviewSha256,
    [Parameter(Mandatory=$true)][string]$ReviewedPythonSha256,
    [string]$Gate='', [string]$GateSha256='',
    [string]$RootReview='', [string]$RootReviewSha256=''
)
$ErrorActionPreference='Stop'
$taskProject='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$taskPython=Join-Path $taskProject '.phase1-data\venv\Scripts\python.exe'
$taskWorker=Join-Path $PSScriptRoot 'minif2f_remaining_serial.py'
if([IO.Path]::GetFullPath($taskWorker) -ne (Join-Path $taskProject 'scripts\benchmark-repair\minif2f_remaining_serial.py')){throw 'The new serial entry is outside its exact reviewed project.'}
if($ReviewedPythonSha256 -notmatch '^[0-9a-f]{64}$' -or (Get-FileHash -LiteralPath $taskWorker -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ReviewedPythonSha256){throw 'The new phase requires its exact separately reviewed Python source SHA.'}
$taskArguments=@('-B','-X','utf8',$taskWorker,'--stage',$Stage,'--review',$Review,'--review-sha',$ReviewSha256)
if($Stage -eq 'Run'){
    if([string]::IsNullOrEmpty($Gate) -or [string]::IsNullOrEmpty($RootReview)){throw 'Run requires its actual Gate and separate Root review.'}
    $taskArguments+=@('--gate',$Gate,'--gate-sha',$GateSha256,'--root-review',$RootReview,'--root-review-sha',$RootReviewSha256)
}
& $taskPython @taskArguments
if($LASTEXITCODE -ne 0){throw 'Remaining serial phase is invalid. Preserve original and new evidence; no automatic retry/cleanup/resume.'}
