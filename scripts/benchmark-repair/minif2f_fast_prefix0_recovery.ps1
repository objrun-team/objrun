[CmdletBinding()]
param(
    [ValidateSet('Gate','Restore','CheckClosed')][string]$Stage='Gate',
    [Parameter(Mandatory)][string]$ReviewPath,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ReviewSha,
    [string]$GatePath='',
    [string]$GateSha=''
)
$ErrorActionPreference='Stop'
$taskPython='D:\ProgramData\anaconda3\python.exe'
$taskWorker=Join-Path $PSScriptRoot 'minif2f_fast_prefix0_recovery.py'
$taskStage=@{Gate='gate';Restore='restore';CheckClosed='check-closed'}[$Stage]
$taskArgs=@($taskWorker,$taskStage,'--review',$ReviewPath,'--review-sha',$ReviewSha)
if($Stage -eq 'Restore'){
    if(!$GatePath -or $GateSha -notmatch '^[0-9a-f]{64}$'){throw 'Restore needs exact new root-reviewed Gate path/SHA.'}
    $taskArgs+=@('--gate',$GatePath,'--gate-sha',$GateSha)
}
& $taskPython -B -X utf8 @taskArgs
if($LASTEXITCODE -ne 0){throw 'Prefix0 recovery is invalid. Preserve old/new/partial markers and all original objects; no automatic retry, cleanup or broad cache move.'}
