$ErrorActionPreference='Stop'
$taskRepo='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$taskRoot='E:\objrun-experiment-cache\01a119ed-fdf7-7c32-b323-de9bab1290b6\minif2f-v415'
$taskDir=Join-Path $taskRepo 'docs\repair-2026-10-08\minif2f-dependency-failures\public-cache-body-v3-first-attempt-verified-v2'
$taskLease=Join-Path $taskRoot 'audit\public-cache-acquisition.lock'
$taskReceipt=Join-Path $taskRoot 'audit\cache-downloads.jsonl'
$taskJournal=Join-Path $taskRoot 'audit\public-cache-body-attempts.jsonl'
function Hash([string]$path){ return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Inside([string]$parent,[string]$child){return [IO.Path]::GetFullPath($child).StartsWith(([IO.Path]::GetFullPath($parent).TrimEnd('\')+'\'),[StringComparison]::OrdinalIgnoreCase)}
function CopyDurable([string]$source,[string]$destination){
 $i=Get-Item -LiteralPath $source -Force
 if($i.PSIsContainer -or ($i.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Not an ordinary source file'}
 if(!(Inside $taskDir $destination)){throw 'Destination escapes exact new F archive'}
 $expected=Hash $source
 $inputFile=[IO.FileStream]::new($source,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
 $outputFile=$null
 try{
  $outputFile=[IO.FileStream]::new($destination,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  $inputFile.CopyTo($outputFile);$outputFile.Flush($true)
 }finally{if($outputFile){$outputFile.Dispose()};$inputFile.Dispose()}
 if((Hash $source) -cne $expected -or (Hash $destination) -cne $expected -or (Get-Item -LiteralPath $destination).Length -ne $i.Length){throw 'Exact durable copy identity changed'}
 return [ordered]@{source=$source;archive=$destination;bytes=$i.Length;sha256=$expected;flushToDiskReturned=$true;sourcePreserved=$true}
}
if((Hash $taskLease) -cne 'fa71a5bf32dc9f9e0fc721577baff3a4970c2b72d8376cdad940e542ae156e40' -or
   (Hash $taskReceipt) -cne '1914b27b4f76b164c85b7920b183a4bd8744114e2f4756e4430d014e1beb8796' -or
   (Hash $taskJournal) -cne '87d966cdc2ea16755a267a9872cce06f7b26e3e618fbd4eba9d6d4fb78e2466a'){throw 'Closed source evidence differs'}
if((Hash (Join-Path $taskRepo 'scripts\benchmark-repair\minif2f_public_cache_v3.py')) -cne '23e760d9236037e8c5d14ef686b00fcbe9659d34cf28d7c03624a7775573af83' -or
   (Hash (Join-Path $taskRepo 'docs\repair-2026-10-08\minif2f-public-cache-v3-review.json')) -cne '21ce70fcd2c9665f00981b9c2b2aa47a950a5130f02b866484e1f2ba41672815' -or
   (Hash (Join-Path $taskRepo 'scripts\benchmark-repair\minif2f_public_cache.py')) -cne 'a02c3519b0ccba8a74e577991fedcf75f0c05fb181cfeb617b7e51b060384c2b' -or
   (Hash (Join-Path $taskRepo 'docs\repair-2026-10-08\minif2f-restoration-preflight.json')) -cne 'f23ebc252a02cf9a407db4fb2045f6c8dba064e1706e97d28fc6ff96ac2a5fd3'){throw 'Executed source or profile changed'}
$taskRaw=Get-Content -LiteralPath $taskLease -Raw|ConvertFrom-Json -DateKind String
if($taskRaw.held -ne $false -or $taskRaw.outcome -cne 'aborted' -or $taskRaw.pid -ne 33428 -or
   $taskRaw.completed_objects -ne 3554 -or $taskRaw.transport_gets -ne 1505 -or $taskRaw.registered_body_recoveries -ne 4 -or
   $taskRaw.prefix_operations_closed -ne $true -or $taskRaw.body_journal.synced_bytes -ne 6751 -or
   $taskRaw.executing_worker_sha256 -cne '23e760d9236037e8c5d14ef686b00fcbe9659d34cf28d7c03624a7775573af83' -or
   $taskRaw.executing_review_sha256 -cne '21ce70fcd2c9665f00981b9c2b2aa47a950a5130f02b866484e1f2ba41672815' -or
   $taskRaw.retained_unclosed_owned_parts_error -ne $null){throw 'Exact released V3 owner differs'}
if(Get-CimInstance Win32_Process -Filter 'ProcessId=33428'){throw 'Former worker PID is present; no file removal'}
$taskSpecs=@(
 @{name='6bf7eeaf1784efec.ltar.part';bytes=81481;sha='f15eaf9e0f5dc8945659b36931f9c70e9d9a56b5027d4d87f875614e74de9e05'},
 @{name='a054c375d3391ae4.ltar.part';bytes=65097;sha='be71c86304f988330af90833ab7809ea98b1d8606b8ae75538c1ce8bf7ab3f66'}
)
$taskCanonical=Join-Path $taskRoot 'downloads\mathlib-cache'
$taskParts=@(Get-ChildItem -LiteralPath $taskCanonical -Filter '*.part' -File)
if($taskParts.Count -ne 2 -or @($taskRaw.retained_unclosed_owned_parts).Count -ne 2){throw 'Unknown canonical partial set'}
foreach($spec in $taskSpecs){
 $source=Join-Path $taskCanonical $spec.name
 $item=Get-Item -LiteralPath $source -Force
 if(!(Inside $taskCanonical $source) -or $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Length -ne $spec.bytes -or (Hash $source) -cne $spec.sha){throw 'Reviewed incomplete file differs'}
 $rows=@($taskRaw.retained_unclosed_owned_parts|Where-Object {$_.path -ceq $source})
 if($rows.Count -ne 1 -or $rows[0].promoted_to_complete -ne $false -or $rows[0].sha256 -cne $spec.sha -or $rows[0].bytes -ne $spec.bytes){throw 'Incomplete file is not exactly released owner evidence'}
}
if(Test-Path -LiteralPath $taskDir){throw 'No archive overwrite or repeated removal'}
New-Item -ItemType Directory -Path $taskDir -ErrorAction Stop|Out-Null
$taskCopies=@(
 @{source=$taskLease;name='aborted-lease.json'},
 @{source=$taskReceipt;name='original-3554-cache-downloads.jsonl'},
 @{source=$taskJournal;name='original-body-journal.jsonl'},
 @{source=(Join-Path $taskRepo 'scripts\benchmark-repair\minif2f_public_cache.py');name='executed-base-guard.py'},
 @{source=(Join-Path $taskRepo 'scripts\benchmark-repair\minif2f_public_cache_v3.py');name='executed-body-v3.py'},
 @{source=(Join-Path $taskRepo 'scripts\benchmark-repair\minif2f_public_cache_v3.ps1');name='executed-body-v3.ps1'},
 @{source=(Join-Path $taskRepo 'docs\repair-2026-10-08\minif2f-public-cache-v3-review.json');name='executed-source-review.json'},
 @{source=(Join-Path $taskRepo 'docs\repair-2026-10-08\minif2f-restoration-preflight.json');name='executed-profile.json'},
 @{source=(Join-Path $taskRepo 'docs\repair-2026-10-08\minif2f-v3-closed-eof-diagnosis.json');name='readonly-eof-diagnosis.json'}
)
$taskRecords=@()
foreach($copy in $taskCopies){$taskRecords+=CopyDurable $copy.source (Join-Path $taskDir $copy.name)}
$taskRegistered=@(Get-Content -LiteralPath $taskJournal|ForEach-Object {$_|ConvertFrom-Json -DateKind String}|Where-Object event -eq 'committed')
if($taskRegistered.Count -ne 4){throw 'Registered prefix count differs'}
foreach($prefix in $taskRegistered){
 $source=Join-Path $taskRoot $prefix.path
 if(!(Inside (Join-Path $taskRoot 'downloads\mathlib-cache-failed-prefix') $source) -or (Hash $source) -cne $prefix.sha256 -or (Get-Item -LiteralPath $source).Length -ne $prefix.bytes){throw 'Registered prefix differs'}
 $taskRecords+=CopyDurable $source (Join-Path $taskDir ([IO.Path]::GetFileName($source)))
}
$taskPartRecords=@()
foreach($spec in $taskSpecs){$taskPartRecords+=CopyDurable (Join-Path $taskCanonical $spec.name) (Join-Path $taskDir $spec.name)}
# All F copies are flushed, read back and hashed before any original file removal.
if((Hash $taskLease) -cne 'fa71a5bf32dc9f9e0fc721577baff3a4970c2b72d8376cdad940e542ae156e40' -or (Hash $taskReceipt) -cne '1914b27b4f76b164c85b7920b183a4bd8744114e2f4756e4430d014e1beb8796' -or (Hash $taskJournal) -cne '87d966cdc2ea16755a267a9872cce06f7b26e3e618fbd4eba9d6d4fb78e2466a'){throw 'Source lease or receipts changed during preservation'}
foreach($spec in $taskSpecs){
 $source=[IO.Path]::GetFullPath((Join-Path $taskCanonical $spec.name))
 $target=[IO.Path]::GetFullPath((Join-Path $taskDir $spec.name))
 if(!(Inside $taskCanonical $source) -or !(Inside $taskDir $target) -or (Hash $source) -cne $spec.sha -or (Hash $target) -cne $spec.sha){throw 'Exact removal containment or SHA differs'}
 Remove-Item -LiteralPath $source -ErrorAction Stop
 if(Test-Path -LiteralPath $source){throw 'Canonical incomplete file removal did not return'}
}
$taskRecord=[ordered]@{protocol='root-exact-closed-v3-failure-preservation-v1';observedAtUtc=[DateTime]::UtcNow.ToString('o');session=46202;actualExitCode=1;completedObjects=3554;newCompletedObjects=1488;transportGets=1505;registeredBodyRecoveries=4;completedBodyRecoveries=3;fault='Generation2 complete-fresh response reached EOF at81481B below87931; failed transfer never committed';originalLeaseHeld=$false;originalProcessPid=33428;originalProcessAbsent=$true;parts=$taskPartRecords;registeredPrefixes=$taskRegistered;copiedInputs=$taskRecords;partialPromoted=$false;completeObjectsOrReceiptsRewritten=$false;canonicalPartsArchivedOnly=$true;automaticRestartAuthorized=$false;modelOrCandidateExecuted=$false;archiveScriptSha256=(Hash $PSCommandPath)}
$taskRecordPath=Join-Path $taskDir 'failure-record.json'
$taskBytes=[Text.UTF8Encoding]::new($false).GetBytes(($taskRecord|ConvertTo-Json -Depth 14)+"`n")
$stream=[IO.FileStream]::new($taskRecordPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
try{$stream.Write($taskBytes,0,$taskBytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
if([Convert]::ToBase64String([IO.File]::ReadAllBytes($taskRecordPath)) -cne [Convert]::ToBase64String($taskBytes)){throw 'Final preservation receipt readback failed'}
[pscustomobject]@{preserved=$true;completedObjects=3554;partialFiles=2;partialBytes=146578;promoted=$false;report=$taskRecordPath;reportSha256=(Hash $taskRecordPath)}|ConvertTo-Json -Compress
