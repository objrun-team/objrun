[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$taskProject='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$taskManifest=Get-Content -LiteralPath (Join-Path $taskProject 'docs\repair-2026-10-08\closed-cache-relocation-file-manifest-v2.json') -Raw | ConvertFrom-Json
$taskRoots=@($taskManifest.roots | ForEach-Object {$_.sourceRoot})
$taskNames=@('paid-resource-admission-v2.test.ts','test_minif2f_fast_unpack.py','software-build-jpg-small.py')
$taskPids=@(37056,93820,97100,107176)
$taskPidStates=@(foreach($taskIdentity in $taskPids){[pscustomobject]@{pid=$taskIdentity;present=($null -ne (Get-Process -Id $taskIdentity -ErrorAction SilentlyContinue))}})
$taskHits=@()
foreach($taskProcess in @(Get-CimInstance Win32_Process -ErrorAction Stop)) {
    if($taskProcess.ProcessId -eq $PID){continue}
    $taskCommand=[string]$taskProcess.CommandLine
    if(-not $taskCommand){continue}
    $taskNormal=$taskCommand.Replace('\','/').ToLowerInvariant()
    $taskMatches=@()
    foreach($taskRoot in $taskRoots){if($taskNormal.Contains($taskRoot.Replace('\','/').ToLowerInvariant())){$taskMatches+=$taskRoot}}
    foreach($taskName in $taskNames){if($taskNormal.Contains($taskName.ToLowerInvariant())){$taskMatches+=$taskName}}
    if($taskMatches.Count){$taskHits += [pscustomobject]@{pid=$taskProcess.ProcessId;name=$taskProcess.Name;subjects=$taskMatches}}
}
[pscustomobject]@{
    protocol='closed-cache-process-path-observation-v1'
    observedAtUtc=[DateTime]::UtcNow.ToString('o')
    roots=$taskRoots
    recordedUnitPidStates=$taskPidStates
    consumerPathHits=$taskHits
    commandLinesOrEnvironmentPrinted=$false
    limitation='Bounded known roots and known test/build names; does not establish global handle or unknown process absence.'
} | ConvertTo-Json -Depth 8 -Compress
