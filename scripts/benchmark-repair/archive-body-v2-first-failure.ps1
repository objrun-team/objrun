$ErrorActionPreference='Stop'
$taskRepo='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$taskRoot='E:\objrun-experiment-cache\01a119ed-fdf7-7c32-b323-de9bab1290b6\minif2f-v415'
$taskDir=Join-Path $taskRepo 'docs\repair-2026-10-08\minif2f-dependency-failures\public-cache-body-v2-first-attempt'
$taskLease=Join-Path $taskRoot 'audit\public-cache-acquisition.lock'
$taskRaw=Get-Content -LiteralPath $taskLease -Raw|ConvertFrom-Json
if($taskRaw.held -ne $false -or $taskRaw.outcome -ne 'aborted' -or $taskRaw.pid -ne 108228 -or
   $taskRaw.completed_objects -ne 2066 -or $taskRaw.transport_gets -ne 135 -or
   $taskRaw.executing_worker_sha256 -cne 'a6aab8d59837109c6c3ff0eb9bca56559f2f2b373d0e58e7b44153aace5b0bec' -or
   $taskRaw.executing_review_sha256 -cne 'a7ca9e72f44a8d4419d5fe0d0d6b84fb42dd63f22083e0cb26319aa430f0d3c3' -or
   $taskRaw.prefix_operations_closed -ne $true -or $taskRaw.body_journal.synced_bytes -ne 0){throw 'Exact closed body-v2 failure changed'}
if(Get-CimInstance Win32_Process -Filter 'ProcessId=108228'){throw 'Old worker PID is present; inspect identity rather than move'}
$taskPart=Join-Path $taskRoot 'downloads\mathlib-cache\f00c6938dd5d3286.ltar.part'
$taskParts=@(Get-ChildItem -LiteralPath (Split-Path -Parent $taskPart) -Filter '*.part' -File)
if($taskParts.Count -ne 1 -or $taskParts[0].FullName -cne $taskPart){throw 'Unexpected partial set'}
$taskItem=Get-Item -LiteralPath $taskPart -Force
if(($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $taskItem.Length -ne 65097 -or
   (Get-FileHash -LiteralPath $taskPart -Algorithm SHA256).Hash.ToLowerInvariant() -cne 'b97e78e7c665be7e34f352d71d0565e470515865f288468e632bd560651c818f'){throw 'Actual partial identity/bytes changed'}
if(Test-Path -LiteralPath $taskDir){throw 'Preserve earlier archive; no overwrite or rerun'}
New-Item -ItemType Directory -Path $taskDir|Out-Null
$taskCopies=@(
 @{Source=$taskLease;Name='aborted-lease.json'},
 @{Source=(Join-Path $taskRoot 'audit\cache-downloads.jsonl');Name='original-2066-cache-downloads.jsonl'},
 @{Source=(Join-Path $taskRoot 'audit\public-cache-body-attempts.jsonl');Name='original-empty-body-journal.jsonl'},
 @{Source=(Join-Path $taskRepo 'scripts\benchmark-repair\minif2f_public_cache.py');Name='executed-base-guard.py'},
 @{Source=(Join-Path $taskRepo 'scripts\benchmark-repair\minif2f_public_cache_v2.py');Name='executed-body-v2.py'},
 @{Source=(Join-Path $taskRepo 'scripts\benchmark-repair\minif2f_public_cache_v2.ps1');Name='executed-body-v2.ps1'},
 @{Source=(Join-Path $taskRepo 'docs\repair-2026-10-08\minif2f-public-cache-v2-review.json');Name='executed-source-review.json'},
 @{Source=(Join-Path $taskRepo 'docs\repair-2026-10-08\minif2f-restoration-preflight.json');Name='executed-profile.json'}
)
$taskRecorded=@()
foreach($taskCopy in $taskCopies){
 $taskBefore=(Get-FileHash -LiteralPath $taskCopy.Source -Algorithm SHA256).Hash.ToLowerInvariant()
 $taskTarget=Join-Path $taskDir $taskCopy.Name
 Copy-Item -LiteralPath $taskCopy.Source -Destination $taskTarget
 if((Get-FileHash -LiteralPath $taskTarget -Algorithm SHA256).Hash.ToLowerInvariant() -cne $taskBefore -or
    (Get-FileHash -LiteralPath $taskCopy.Source -Algorithm SHA256).Hash.ToLowerInvariant() -cne $taskBefore){throw 'Immutable failure copy mismatch; retain both'}
 $taskRecorded+=[ordered]@{name=$taskCopy.Name;bytes=(Get-Item -LiteralPath $taskTarget).Length;sha256=$taskBefore}
}
$taskAbsoluteSource=[IO.Path]::GetFullPath($taskPart)
$taskAbsoluteTarget=[IO.Path]::GetFullPath((Join-Path $taskDir 'f00c6938dd5d3286.ltar.part'))
if(-not $taskAbsoluteSource.StartsWith(($taskRoot+'\downloads\mathlib-cache\'),[StringComparison]::OrdinalIgnoreCase) -or
   -not $taskAbsoluteTarget.StartsWith(($taskDir+'\'),[StringComparison]::OrdinalIgnoreCase)){throw 'Resolved exact file move escapes owned scopes'}
# Move only this reviewed incomplete file; never copy its bytes into a new download.
Move-Item -LiteralPath $taskAbsoluteSource -Destination $taskAbsoluteTarget
if((Get-FileHash -LiteralPath $taskAbsoluteTarget -Algorithm SHA256).Hash.ToLowerInvariant() -cne 'b97e78e7c665be7e34f352d71d0565e470515865f288468e632bd560651c818f' -or
   (Get-Item -LiteralPath $taskAbsoluteTarget).Length -ne 65097 -or (Test-Path -LiteralPath $taskAbsoluteSource)){throw 'Exact archived incomplete file failed verification'}
$taskRecord=[ordered]@{observedAtUtc=[DateTime]::UtcNow.ToString('o');session=19208;actualExitCode=1;completedObjects=2066;newCompletedObjects=129;transportGets=135;fault='Body timeout entered v2 recovery, which refused absent required length or strong ETag; actual failed response headers not persisted';originalLeaseHeld=$false;originalProcessAbsent=$true;executingWorkerSha256='a6aab8d59837109c6c3ff0eb9bca56559f2f2b373d0e58e7b44153aace5b0bec';executingReviewSha256='a7ca9e72f44a8d4419d5fe0d0d6b84fb42dd63f22083e0cb26319aa430f0d3c3';partialBytes=65097;partialSha256='b97e78e7c665be7e34f352d71d0565e470515865f288468e632bd560651c818f';partialPreserved=$true;partialPromoted=$false;completeOriginalObjectsRewritten=$false;bodyJournalSyncedBytes=0;copiedInputs=$taskRecorded;candidateOrLlmExecuted=$false;archiveScriptSha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()}
[IO.File]::WriteAllText((Join-Path $taskDir 'failure-record.json'),(($taskRecord|ConvertTo-Json -Depth 8)+[Environment]::NewLine),[Text.UTF8Encoding]::new($false))
[pscustomobject]@{preserved=$true;completedObjects=2066;partialBytes=65097;promoted=$false;report=(Join-Path $taskDir 'failure-record.json')}|ConvertTo-Json -Compress
