$ErrorActionPreference='Stop'
$taskRepo='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$taskOwned='E:\objrun-experiment-cache\01a119ed-fdf7-7c32-b323-de9bab1290b6\minif2f-v415'
$taskArchive=Join-Path $taskRepo 'docs\repair-2026-10-08\minif2f-dependency-failures\public-cache-transport-first-attempt'
$taskPart=Join-Path $taskOwned 'downloads\mathlib-cache\f236dfdbe8e5ae7d.ltar.part'
$taskPartSha='076c08a8cba7692e1c8839b304b78b4f8f8a59522263d85fa37a2650c98efbf7'
function Contained([string]$Path,[string]$Root){
    $resolved=[IO.Path]::GetFullPath($Path)
    if(-not $resolved.StartsWith([IO.Path]::GetFullPath($Root).TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Path escapes the explicitly named root'}
    return $resolved
}
function Ordinary-Ancestors([string]$Path){
    $current=[IO.Path]::GetFullPath($Path)
    while($current){
        if(Test-Path -LiteralPath $current){if((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Unexpected reparse ancestor'}}
        $parent=Split-Path -Parent $current
        if(-not $parent -or $parent -eq $current){break};$current=$parent
    }
}
Contained $taskArchive $taskRepo|Out-Null
Contained $taskPart $taskOwned|Out-Null
Ordinary-Ancestors $taskArchive
Ordinary-Ancestors $taskPart
if(Test-Path -LiteralPath $taskArchive){throw 'Preserve prior failure archive; no overwrite'}
$taskLeasePath=Join-Path $taskOwned 'audit\public-cache-acquisition.lock'
$taskLease=Get-Content -LiteralPath $taskLeasePath -Raw|ConvertFrom-Json
if($taskLease.held -ne $false -or $taskLease.outcome -ne 'aborted' -or $taskLease.completed_objects -ne 68 -or $taskLease.pid -ne 87136){throw 'The exact failed acquisition is not released'}
$taskProc=Get-CimInstance Win32_Process -Filter 'ProcessId=87136'
if($taskProc -and [string]$taskProc.CommandLine -match 'minif2f_public_cache'){throw 'Failed worker still exists; no archive mutation'}
$taskParts=@(Get-ChildItem -LiteralPath (Join-Path $taskOwned 'downloads\mathlib-cache') -File -Filter '*.part')
if($taskParts.Count -ne 1 -or $taskParts[0].FullName -ne $taskPart -or $taskParts[0].Length -ne 32329 -or (Get-FileHash -LiteralPath $taskPart -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskPartSha){throw 'Partial differs from the reviewed exact bytes'}
if((Get-PSDrive E).Free -lt 3GB -or (Get-PSDrive F).Free -lt 1GB+2MB){throw 'Required host reserves unavailable'}
New-Item -ItemType Directory -Path $taskArchive|Out-Null
$taskPairs=@(
    @($taskLeasePath,'aborted-lease.json'),
    @((Join-Path $taskOwned 'audit\cache-downloads.jsonl'),'original-68-cache-downloads.jsonl'),
    @((Join-Path $taskRepo 'scripts\repair-2026-10-08\minif2f_public_cache.py'),'executed-public-cache.py'),
    @((Join-Path $taskRepo 'scripts\repair-2026-10-08\minif2f_public_cache.ps1'),'executed-public-cache.ps1'),
    @((Join-Path $taskRepo 'docs\repair-2026-10-08\minif2f-restoration-preflight.json'),'executed-profile.json')
)
$taskRows=@()
foreach($pair in $taskPairs){
    $target=Contained (Join-Path $taskArchive $pair[1]) $taskArchive
    Ordinary-Ancestors $pair[0]
    Copy-Item -LiteralPath $pair[0] -Destination $target
    $digest=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    if($digest -ne (Get-FileHash -LiteralPath $pair[0] -Algorithm SHA256).Hash.ToLowerInvariant()){throw 'Failure input copy differs'}
    $taskRows+=[pscustomobject]@{name=$pair[1];bytes=(Get-Item -LiteralPath $target).Length;sha256=$digest}
}
$taskDestination=Contained (Join-Path $taskArchive 'f236dfdbe8e5ae7d.ltar.part') $taskArchive
# Native PowerShell only, with the exact absolute source and destination checked.
Contained $taskPart $taskOwned|Out-Null
Ordinary-Ancestors $taskPart
Ordinary-Ancestors $taskDestination
Move-Item -LiteralPath $taskPart -Destination $taskDestination
if((Test-Path -LiteralPath $taskPart) -or (Get-Item -LiteralPath $taskDestination).Length -ne 32329 -or (Get-FileHash -LiteralPath $taskDestination -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskPartSha){throw 'Partial preservation failed; retain both locations for reviewed recovery'}
$taskReport=[ordered]@{observedAt=[DateTime]::UtcNow.ToString('o');session=17495;actualExitCode=1;fault='response-open URLError Win10060, no observer fault';completedObjects=68;completedOriginalBytesLeftInE=$true;partialOriginalPath=$taskPart;partialArchivePath=$taskDestination;partialBytes=32329;partialSha256=$taskPartSha;partialPromoted=$false;partialPreserved=$true;copiedInputs=$taskRows;failedSourceSha256='cc00c3aff60949865ebb3df3a1d89fc45170981c6057ad55c8f89294d06b91c0';oldCandidateOrModelRun=$false;limit='Completed objects must be verified against the original receipts before exact-key resume. Partial was not judged complete or promoted.'}
[IO.File]::WriteAllText((Join-Path $taskArchive 'failure-record.json'),(($taskReport|ConvertTo-Json -Depth 5)+[Environment]::NewLine),[Text.UTF8Encoding]::new($false))
[pscustomobject]@{archived=$true;partialBytes=32329;partialSha256=$taskPartSha;completedObjectsPreserved=68;modelRun=$false}|ConvertTo-Json -Compress
