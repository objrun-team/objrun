param(
    [Parameter(Mandatory=$true)][ValidateSet('gate','snapshot')][string]$Mode,
    [Parameter(Mandatory=$true)][string]$Review,
    [Parameter(Mandatory=$true)][string]$ReviewSha,
    [Parameter(Mandatory=$true)][string]$Receipt
)
$ErrorActionPreference='Stop'
$taskPython='D:/ProgramData/anaconda3/python.exe'
$taskPythonSha='6965927a96b81d1717c1d2186de7feb9b29ebf8775464020ebc2f25de6ef8ee0'
$taskSource=Join-Path $PSScriptRoot 'science-worker-db-snapshot-v1.py'
$taskReviewPath=[IO.Path]::GetFullPath($Review)
if((Get-FileHash -LiteralPath $taskPython -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskPythonSha){throw 'absolute_native_python_changed'}
if((Get-FileHash -LiteralPath $taskReviewPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ReviewSha){throw 'review_pin_changed'}
$taskReview=Get-Content -LiteralPath $taskReviewPath -Raw | ConvertFrom-Json
if($taskReview.protocol -ne 'science-worker-db-snapshot-review-v1' -or $taskReview.validated -ne $true){throw 'unreviewed_snapshot_protocol'}
if((Get-FileHash -LiteralPath $taskSource -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskReview.sourcePin.sha256){throw 'source_pin_changed'}
if((Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskReview.launcherPin.sha256){throw 'launcher_pin_changed'}
& $taskPython -B -X utf8 $taskSource --mode $Mode --review $taskReviewPath --review-sha $ReviewSha --receipt $Receipt
exit $LASTEXITCODE
