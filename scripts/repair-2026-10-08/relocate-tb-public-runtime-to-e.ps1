[CmdletBinding(DefaultParameterSetName='DryRun')]
param(
    [Parameter(ParameterSetName='DryRun')][switch]$DryRun,
    [Parameter(Mandatory,ParameterSetName='Apply')][switch]$Apply,
    [Parameter(Mandatory,ParameterSetName='Apply')][ValidatePattern('^[0-9a-f]{64}$')][string]$PreflightSha
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$taskProject='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$taskCBase='C:\Users\y1252\.codex\visualizations\2026\10\08\01a119ed-fdf7-7c32-b323-de9bab1290b6\public-runtime-cache\terminal-bench'
$taskFBase=Join-Path $taskProject 'examples\benchmark\terminal-bench'
$taskEBase='E:\objrun-experiment-cache\01a119ed-fdf7-7c32-b323-de9bab1290b6\inactive-benchmark-archives\public-tb-runtime'
$taskMini='E:\objrun-experiment-cache\01a119ed-fdf7-7c32-b323-de9bab1290b6\minif2f-v415'
$taskPreflight=Join-Path $taskProject 'docs\repair-2026-10-08\tb-public-runtime-c-to-e-preflight.json'
$taskApplyReceipt=Join-Path $taskProject 'docs\repair-2026-10-08\tb-public-runtime-c-to-e-apply.json'
$taskNames=@('.runtime','.verifier-deps')
$taskExpectedBytes=[long]204144539
$taskExpectedFiles=32
$taskReserve=[long](14GB+3GB)
$taskAuditReserve=[long]4MB
$taskLegacy=@(@{relative='docs\repair-2026-10-08\tb-public-runtime-relocation.json';sha256='87cde0489c603e6ad12d4c1112a8406fe8bd8a60f2a2fe3bbb6a90f869d200d4'})
$taskBoundaryPins=@(
 @{relative='docs\repair-2026-10-08\tb-pilot-independent-audit\tb-nginx-2026-10-08T10-47-06-544Z\audit.json';sha256='cc5bc3a9683648ee882e27e18e7acee05f95ed55631c349ce2cde296ce218e49'},
 @{relative='docs\repair-2026-10-08\skb-jpg-independent-audit\skb-jpg-2026-10-08T11-29-26-467Z\audit.json';sha256='a46552db5be379684a028ff9c99ec7db7cc91e936e28583bb720eaac61753c66'},
 @{relative='examples\benchmark\terminal-bench\stand.py';sha256='e39074db93de2505b10c7d355b8017378ba23af6224f826943b9da867e2c3363'},
 @{relative='examples\benchmark\terminal-bench\isolated_verifier.py';sha256='5fff8cb382376bc8bb4aac509f4b68d1b22fcc82c8a7153ffe9fd73adb976ef6'},
 @{relative='scripts\repair-2026-10-08\skb-jpg-stand.py';sha256='988d352a6ae62f000bcf88d1fd6e9f6440c8c6da69510498b717be0ef69fd9e2'},
 @{relative='scripts\repair-2026-10-08\software-jpg-build.py';sha256='615d78c49de32e0afb42fe6df9ad20a6b233dc531a4268e768c8d86a3d5487aa'},
 @{relative='docs\repair-2026-10-08\legacy-jpg-13-stand-cleanup.json';sha256='3bb8bb0e3edf60380ee7ae3bb6bf61b9493c63e58a9c47e7df8ef535ab17f064'}
)

function Canonical([string]$Path) {
    if (-not [IO.Path]::IsPathRooted($Path) -or $Path.StartsWith('\\')) { throw 'Only absolute local drive paths are accepted.' }
    return [IO.Path]::GetFullPath($Path).TrimEnd('\')
}
function Contained([string]$Path,[string]$Base) {
    $p = Canonical $Path
    $b = (Canonical $Base) + '\'
    if (-not $p.StartsWith($b,[StringComparison]::OrdinalIgnoreCase)) { throw 'Path escapes its exact explicitly named base.' }
    return $p
}
function Overlaps([string]$A,[string]$B) {
    $a = $A.Replace('\','/').TrimEnd('/').ToLowerInvariant()
    $b = $B.Replace('\','/').TrimEnd('/').ToLowerInvariant()
    return ($a -eq $b -or $a.StartsWith($b+'/') -or $b.StartsWith($a+'/'))
}
function Ordinary-Ancestors([string]$Path,[bool]$AllowMissing=$false) {
    $p = Canonical $Path
    while ($p.Length -gt 3) {
        if (Test-Path -LiteralPath $p) {
            $i = Get-Item -LiteralPath $p -Force
            if (-not $i.PSIsContainer -or ($i.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'An ancestor is not an ordinary directory.' }
        } elseif (-not $AllowMissing) { throw 'A required ordinary directory is missing.' }
        $p = Split-Path -Parent $p
    }
}
function Junction-Target([string]$Path,[string]$Expected) {
    $i = Get-Item -LiteralPath $Path -Force
    $targets = @($i.Target)
    if (-not $i.PSIsContainer -or $i.LinkType -ne 'Junction' -or $targets.Count -ne 1) { throw 'Expected the exact existing NTFS junction.' }
    $target = [string]$targets[0]
    if ($target.StartsWith('\??\')) { $target=$target.Substring(4) }
    if ($target.StartsWith('\\?\')) { $target=$target.Substring(4) }
    if ((Canonical $target) -cne (Canonical $Expected)) { throw 'Junction target differs from the fixed path.' }
    Ordinary-Ancestors (Split-Path -Parent $Path)
    return $target
}
function Sha([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Relative-Path([string]$Base,[string]$Path) {
    $p=Contained $Path $Base
    return $p.Substring((Canonical $Base).Length+1)
}
function Inventory([string]$Base) {
    Ordinary-Ancestors $Base
    $stack=[Collections.Generic.Stack[string]]::new()
    $stack.Push((Canonical $Base))
    $files=[Collections.Generic.List[object]]::new()
    $dirs=[Collections.Generic.List[string]]::new()
    while($stack.Count) {
        $directory=$stack.Pop()
        foreach($i in @(Get-ChildItem -LiteralPath $directory -Force)) {
            $path=Contained $i.FullName $Base
            if($i.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Unexpected reparse point inside fixed archive.' }
            if($i.PSIsContainer) { $dirs.Add((Relative-Path $Base $path)); $stack.Push($path) }
            else {
                if($i.Attributes -band ([IO.FileAttributes]::Compressed -bor [IO.FileAttributes]::SparseFile -bor [IO.FileAttributes]::Encrypted -bor [IO.FileAttributes]::Device)) {
                    throw 'Nonordinary/compressed/sparse/encrypted source requires separate allocation review.'
                }
                $files.Add([pscustomobject]@{relative=(Relative-Path $Base $path);bytes=[long]$i.Length;sha256=(Sha $path)})
            }
        }
    }
    return [pscustomobject]@{files=@($files|Sort-Object relative);directories=@($dirs|Sort-Object);bytes=[long](($files|Measure-Object bytes -Sum).Sum)}
}
function Match-Files($Expected,$Actual) {
    $expected=@($Expected);$actual=@($Actual)
    if($expected.Count -ne $actual.Count){throw 'Archive file count differs from original frozen manifest.'}
    $map=@{}
    foreach($e in $expected) {
        if([IO.Path]::IsPathRooted($e.relative) -or $e.relative -match '(^|[\\/])\.\.([\\/]|$)' -or $map.ContainsKey($e.relative)){throw 'Unsafe or duplicated frozen relative path.'}
        $map[$e.relative]=$e
    }
    foreach($a in $actual) {
        $e=$map[$a.relative]
        if($null -eq $e -or [long]$e.bytes -ne $a.bytes -or $e.sha256 -cne $a.sha256){throw 'Original archive bytes/SHA differ.'}
    }
}
function Alias-Hashes([string]$Alias,$Files) {
    foreach($file in $Files) {
        $path=Contained (Join-Path $Alias $file.relative) $Alias
        $item=Get-Item -LiteralPath $path -Force
        if($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or [long]$item.Length -ne [long]$file.bytes -or (Sha $path) -cne $file.sha256) {
            throw 'Original alias failed full byte/SHA readback.'
        }
    }
}
function Save-Json([string]$Path,$Object) {
    Contained $Path $taskProject|Out-Null
    $text=($Object|ConvertTo-Json -Depth 16)+[Environment]::NewLine
    $bytes=[Text.UTF8Encoding]::new($true).GetBytes($text)
    $out=[IO.File]::Open($Path,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try{$out.Write($bytes,0,$bytes.Length);$out.Flush($true)}finally{$out.Dispose()}
}
function Free-Space([long]$Remaining) {
    $c=[IO.DriveInfo]::new('C:\').AvailableFreeSpace
    $e=[IO.DriveInfo]::new('E:\').AvailableFreeSpace
    $f=[IO.DriveInfo]::new('F:\').AvailableFreeSpace
    if($e -lt $taskReserve+$Remaining+$taskAuditReserve){throw 'E requires additional14GiB+3GiB+all remaining copy/audit reservation.'}
    if($f -lt 1GB+$taskAuditReserve){throw 'F 1GiB reserve is not available.'}
    if($c -lt $taskAuditReserve){throw 'C junction metadata reservation is unavailable.'}
    return [ordered]@{C=$c;E=$e;F=$f;E_required_now=$taskReserve+$Remaining+$taskAuditReserve}
}
function Mount-Normalize([string]$Path) {
    $p=$Path.Replace('\','/').TrimEnd('/').ToLowerInvariant()
    foreach($prefix in @('/run/desktop/mnt/host/','/host_mnt/')) {
        if($p.StartsWith($prefix) -and $p.Length -gt $prefix.Length+1){$p=$p.Substring($prefix.Length,1)+':'+$p.Substring($prefix.Length+1)}
    }
    return $p
}
function Writer-Probe($Rows) {
    $all=@(Get-CimInstance Win32_Process)
    $excluded=[Collections.Generic.HashSet[int]]::new()
    $current=[int]$PID
    while($current){
        $excluded.Add($current)|Out-Null
        $ancestor=$all|Where-Object ProcessId -eq $current|Select-Object -First 1
        if($null -eq $ancestor){break}
        $current=[int]$ancestor.ParentProcessId
    }
    $hits=@()
    $knownConsumers=@(
      ((Join-Path $taskProject 'examples\benchmark\terminal-bench\stand.py').Replace('\','/').ToLowerInvariant()),
      ((Join-Path $taskProject 'examples\benchmark\terminal-bench\prepare_runtime.py').Replace('\','/').ToLowerInvariant()),
      ((Join-Path $taskProject 'examples\benchmark\terminal-bench\prepare_verifier_dependencies.py').Replace('\','/').ToLowerInvariant()),
      ((Join-Path $taskProject 'scripts\repair-2026-10-08\tb-nginx-stand.py').Replace('\','/').ToLowerInvariant()),
      ((Join-Path $taskProject 'scripts\repair-2026-10-08\skb-jpg-stand.py').Replace('\','/').ToLowerInvariant()),
      ((Join-Path $taskProject 'scripts\repair-2026-10-08\software-jpg-build.py').Replace('\','/').ToLowerInvariant())
    )
    foreach($process in $all){
        if($excluded.Contains([int]$process.ProcessId)){continue}
        $line=([string]$process.CommandLine).Replace('\','/').ToLowerInvariant()
        $reason=$null;$matched=$null
        foreach($known in $knownConsumers){
            if($line.Contains($known)){$reason='known_public_cache_consumer_or_preparer';$matched=Split-Path -Leaf $known;break}
        }
        if(-not $reason){
            foreach($row in $Rows){
                foreach($scope in @($row.sourceC,$row.aliasF,$row.targetE,$row.backupC,$row.stagedJunctionC)){
                    if($line.Contains((Mount-Normalize $scope))){$reason='exact_public_cache_path_in_command';$matched=$row.run;break}
                }
                if($reason){break}
            }
        }
        if($reason){$hits += [pscustomobject]@{pid=[int]$process.ProcessId;process=$process.Name;creationUtc=$process.CreationDate.ToUniversalTime().ToString('o');reason=$reason;matched=$matched}}
    }
    # Read only actual mount metadata. Never log raw commands, Config, environment or keys.
    $ids=@(& docker ps --no-trunc --format '{{.ID}}')
    if($LASTEXITCODE -ne 0){throw 'Actual running Docker inventory unavailable.'}
    $rw=@();$ro=@()
    if($ids.Count){
        $raw=& docker inspect @ids
        if($LASTEXITCODE -ne 0){throw 'Actual Docker mount inventory unavailable.'}
        foreach($container in ($raw|ConvertFrom-Json)){
            foreach($mount in $container.Mounts){
                $source=Mount-Normalize ([string]$mount.Source)
                foreach($row in $Rows){
                    foreach($scope in @($row.sourceC,$row.aliasF,$row.targetE,$row.backupC,$row.stagedJunctionC)){
                        if(Overlaps $source (Mount-Normalize $scope)){
                            $item=[pscustomobject]@{containerId=$container.Id;cache=$row.run;source=$source;destination=$mount.Destination;rw=[bool]$mount.RW}
                            if($mount.RW){$rw += $item}else{$ro += $item}
                            break
                        }
                    }
                }
            }
        }
    }
    if($hits.Count -or $rw.Count -or $ro.Count){throw 'A current consumer/preparer or actual writable/read-only mount overlaps an exact public cache; preserve both sides for root review.'}
    return [ordered]@{checkedAt=[DateTime]::UtcNow.ToString('o');hostConflicts=$hits;runningContainersChecked=$ids;writableMountConflicts=$rw;readOnlyMountConsumers=$ro;scope='old TB/JPG closure plus actual known consumers/exact paths and mount metadata; no claim of exhaustive open-handle isolation'}
}

$taskBoundaryFiles=@()
foreach($pin in $taskBoundaryPins){
    $path=Join-Path $taskProject $pin.relative
    if((Sha $path) -cne $pin.sha256){throw 'Pinned existing TB/JPG closure or public-cache source usage changed.'}
    $taskBoundaryFiles += [ordered]@{path=$path;bytes=(Get-Item -LiteralPath $path).Length;sha256=$pin.sha256}
}
$taskLaterClosure=Get-Content -LiteralPath (Join-Path $taskProject $taskBoundaryPins[6].relative) -Raw|ConvertFrom-Json
$taskExactClosed=@($taskLaterClosure.closedProcesses)
$taskExactPids=@(59880,92480,98188,93832,57304,95996,75920,3404,95312,35636,89232,94792,68384)
if($taskExactClosed.Count -ne 13 -or $taskLaterClosure.archivalFileBytesChanged -ne $false -or $taskLaterClosure.latest1129StoreTouched -ne $false){throw 'Later exact mock-consumer closure/no-archive-change evidence required.'}
foreach($closed in $taskExactClosed){
    if($closed.pid -notin $taskExactPids -or $closed.closed -ne $true -or $closed.mode -cne 'mock' -or $closed.handleIdentityChecked -ne $true -or $closed.parentAbsent -ne $true -or $closed.pidReusedAfterClose -ne $false){throw 'An exact formerly surviving public-cache consumer is unresolved.'}
}
if(@($taskExactClosed.pid|Sort-Object -Unique).Count -ne 13){throw 'Later closed exact consumer set differs.'}
foreach($index in @(0,1)){
    $audit=Get-Content -LiteralPath (Join-Path $taskProject $taskBoundaryPins[$index].relative) -Raw|ConvertFrom-Json
    if($audit.passedAllAvailableChecks -ne $true){throw 'Closed existing TB/JPG evidence is not valid.'}
    $required=if($index -eq 0){@('exact_owned_docker_objects_now_absent','recorded_host_workers_stand_and_ports_now_closed')}else{@('runner_cleanup_and_receipts_closed','recorded_processes_and_endpoint_ports_now_closed')}
    foreach($name in $required){
        $check=@($audit.checks|Where-Object name -eq $name)
        if($check.Count -ne 1 -or $check[0].passed -ne $true){throw 'An exact recorded closed-runtime boundary is missing.'}
    }
}
$taskRows=@()
foreach($pin in $taskLegacy){
    $path=Join-Path $taskProject $pin.relative
    if((Sha $path) -cne $pin.sha256){throw 'Original public-cache relocation source record changed.'}
    $legacy=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json
    if($legacy.applied -ne $true -or $legacy.validated -ne $true -or $legacy.scope -cne 'Owned public TB runtime and verifier dependency bytes only' -or [long]$legacy.totalBytes -ne $taskExpectedBytes){throw 'Original exact validated public-only relocation required.'}
    foreach($row in $legacy.directories){
        $name=[string]$row.name
        if($name -notin $taskNames -or $row.status -cne 'junction_and_all_file_hashes_verified'){throw 'Unexpected public cache directory or unresolved old relocation.'}
        $c=Contained (Join-Path $taskCBase $name) $taskCBase
        $f=Contained (Join-Path $taskFBase $name) $taskFBase
        $e=Contained (Join-Path $taskEBase $name) $taskEBase
        if((Canonical $row.target) -cne $c -or (Canonical $row.source) -cne $f -or (Overlaps $e $taskMini)){throw 'Fixed original public path differs or overlaps mini root.'}
        $backup=Contained (Join-Path $taskCBase ($name+'.ce-backup-01a119ed')) $taskCBase
        $stage=Contained (Join-Path $taskCBase ($name+'.ce-junction-01a119ed')) $taskCBase
        foreach($dest in @($e,$backup,$stage)){if(Test-Path -LiteralPath $dest){throw 'Prior target/backup/staged link exists; no overwrite/resume/cleanup.'}}
        Ordinary-Ancestors $c
        Ordinary-Ancestors $taskEBase $true
        Junction-Target $f $c|Out-Null
        $inventory=Inventory $c
        Match-Files $row.files $inventory.files
        if($inventory.bytes -ne [long]$row.bytes){throw 'Exact original public cache byte sum differs.'}
        Alias-Hashes $f $row.files
        $taskRows += [pscustomobject]@{run=$name;sourceC=$c;aliasF=$f;targetE=$e;backupC=$backup;stagedJunctionC=$stage;bytes=$inventory.bytes;files=$inventory.files;directories=$inventory.directories;eligibility=[ordered]@{publicCachedBytesOnly=$true;noCandidateOrPaidRecordMoved=$true;inputFiles=$taskBoundaryFiles;usageBoundary='TB runtime/dependency source and existing independently closed TB/JPG evidence; current consumer/mount gate must still pass'};status='sourceC_and_original_F_alias_verified'}
    }
}
if($taskRows.Count -ne 2 -or @($taskRows.run|Sort-Object -Unique).Count -ne 2 -or [long](($taskRows|Measure-Object bytes -Sum).Sum) -ne $taskExpectedBytes -or @($taskRows.files).Count -ne $taskExpectedFiles){throw 'Fixed two-root/32-file/204144539-byte contract differs.'}

$taskFree=Free-Space $taskExpectedBytes
$taskProbe=Writer-Probe $taskRows
$taskScriptSha=Sha $PSCommandPath
$taskResult=[ordered]@{protocol='closed-public-tb-runtime-c-to-e-v1';createdAt=[DateTime]::UtcNow.ToString('o');scriptSha256=$taskScriptSha;mode=if($Apply){'Apply'}else{'DryRun'};applied=$false;validated=$false;targets=2;files=32;bytes=$taskExpectedBytes;originalRecords=$taskLegacy;existingClosedBoundaryPins=$taskBoundaryPins;freeBefore=$taskFree;writerProbe=$taskProbe;miniOwnedRootModified=$false;providerCalled=$false;sourceRawModified=$false;runs=$taskRows;failurePolicy='retain all new target copies and C backups/staged links; no rollback or cleanup on failure'}
if(-not $Apply) {
    $taskResult.validated=$true
    $taskResult['C_logical_bytes_expected_recovered']=$taskExpectedBytes
    $taskResult['E_minimum_start_bytes']=[long]($taskReserve+$taskExpectedBytes+$taskAuditReserve)
    Save-Json $taskPreflight $taskResult
    [ordered]@{mode='DryRun';C_E_modified=$false;validated=$true;targets=2;files=32;bytes=$taskExpectedBytes;free=$taskFree;preflight=$taskPreflight;preflightSha256=(Sha $taskPreflight)}|ConvertTo-Json -Depth 4
    exit 0
}
if((Sha $taskPreflight) -cne $PreflightSha){throw 'Root-reviewed exact preflight SHA required before Apply.'}
$previous=Get-Content -LiteralPath $taskPreflight -Raw|ConvertFrom-Json
if($previous.scriptSha256 -cne $taskScriptSha -or $previous.protocol -cne 'closed-public-tb-runtime-c-to-e-v1' -or -not $previous.validated -or $previous.applied){throw 'Fresh same-script DryRun proof required.'}
foreach($row in $taskRows) {
    $old=@($previous.runs|Where-Object run -eq $row.run)
    if($old.Count -ne 1){throw 'Preflight fixed public-root set changed.'}
    Match-Files $old[0].files $row.files
    foreach($entry in $row.eligibility.inputFiles) {
        $oldEntry=@($old[0].eligibility.inputFiles|Where-Object path -eq $entry.path)
        if($oldEntry.Count -ne 1 -or $oldEntry[0].sha256 -cne $entry.sha256){throw 'Pinned TB/JPG closure/public source usage changed.'}
    }
}
if(Test-Path -LiteralPath $taskApplyReceipt){throw 'Existing Apply receipt requires review; no rerun or overwrite.'}
$taskMutex=[Threading.Mutex]::new($false,'Local\TgEnginClosedPublicRuntimeRelocation-01a119ed')
$taskHeld=$false
try {
    $taskHeld=$taskMutex.WaitOne(0)
    if(-not $taskHeld){throw 'Another relocation coordinator owns the exact cooperative mutex.'}
    Writer-Probe $taskRows|Out-Null
    Ordinary-Ancestors $taskEBase $true
    New-Item -ItemType Directory -Path $taskEBase -Force|Out-Null
    $remaining=[long]$taskExpectedBytes
    foreach($row in $taskRows) {
        Ordinary-Ancestors $row.sourceC
        New-Item -ItemType Directory -Path $row.targetE|Out-Null
        foreach($relative in $row.directories){New-Item -ItemType Directory -Path (Contained (Join-Path $row.targetE $relative) $row.targetE) -Force|Out-Null}
        foreach($file in $row.files) {
            $source=Contained (Join-Path $row.sourceC $file.relative) $row.sourceC
            $target=Contained (Join-Path $row.targetE $file.relative) $row.targetE
            Free-Space $remaining|Out-Null
            $incoming=[IO.File]::Open($source,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
            $outgoing=$null
            try {
                $outgoing=[IO.File]::Open($target,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
                $buffer=[byte[]]::new(1MB)
                $copied=[long]0
                while(($read=$incoming.Read($buffer,0,$buffer.Length)) -gt 0) {
                    if($copied+$read -gt [long]$file.bytes){throw 'Source grew beyond its exact frozen size; preserve partial copy and source.'}
                    $outgoing.Write($buffer,0,$read)
                    $copied+=$read
                    $remaining-=$read
                    Free-Space $remaining|Out-Null
                }
                if($copied -ne [long]$file.bytes){throw 'Source ended before its exact frozen size; preserve partial copy and source.'}
                $outgoing.Flush($true)
            } finally {if($outgoing){$outgoing.Dispose()};$incoming.Dispose()}
            if((Get-Item -LiteralPath $target -Force).Length -ne $file.bytes -or (Sha $target) -cne $file.sha256){throw 'Copied bytes/SHA failed; C source untouched.'}
        }
        $copy=Inventory $row.targetE
        Match-Files $row.files $copy.files
        if(($copy.directories -join '|') -cne ($row.directories -join '|')){throw 'Copied ordinary directory set differs.'}
        $row.status='all_target_bytes_verified_sourceC_untouched'
        Save-Json $taskApplyReceipt $taskResult
    }
    # No C rename/removal happens before BOTH E copies pass hashes.
    foreach($row in $taskRows) {
        Writer-Probe $taskRows|Out-Null
        Match-Files $row.files (Inventory $row.sourceC).files
        Junction-Target $row.aliasF $row.sourceC|Out-Null
        Ordinary-Ancestors $row.sourceC
        Ordinary-Ancestors $row.targetE
        Contained $row.backupC $taskCBase|Out-Null
        Contained $row.stagedJunctionC $taskCBase|Out-Null
        if((Test-Path -LiteralPath $row.backupC) -or (Test-Path -LiteralPath $row.stagedJunctionC)){throw 'Fresh C backup/staged link requirement changed; preserve both sides.'}
        New-Item -ItemType Junction -Path $row.stagedJunctionC -Target $row.targetE|Out-Null
        Junction-Target $row.stagedJunctionC $row.targetE|Out-Null
        Move-Item -LiteralPath $row.sourceC -Destination $row.backupC
        Move-Item -LiteralPath $row.stagedJunctionC -Destination $row.sourceC
        Junction-Target $row.sourceC $row.targetE|Out-Null
        Junction-Target $row.aliasF $row.sourceC|Out-Null
        Alias-Hashes $row.sourceC $row.files
        Alias-Hashes $row.aliasF $row.files
        $row.status='C_and_F_aliases_verified_C_backup_retained'
        Save-Json $taskApplyReceipt $taskResult
    }
    # BOTH C/F chains work before any old physical C duplicate is removed.
    foreach($row in $taskRows) {
        Writer-Probe $taskRows|Out-Null
        $exactBackup=Contained $row.backupC $taskCBase
        if($exactBackup -cne (Canonical (Join-Path $taskCBase ($row.run+'.ce-backup-01a119ed')))){throw 'Unexpected final recursive source-removal target.'}
        Ordinary-Ancestors $exactBackup
        Match-Files $row.files (Inventory $exactBackup).files
        Match-Files $row.files (Inventory $row.targetE).files
        Junction-Target $row.sourceC $row.targetE|Out-Null
        Alias-Hashes $row.aliasF $row.files
        Remove-Item -LiteralPath $exactBackup -Recurse -Force
        $row.status='exact_C_duplicate_removed_original_C_F_junction_chain_verified'
        Save-Json $taskApplyReceipt $taskResult
    }
    foreach($row in $taskRows){Match-Files $row.files (Inventory $row.targetE).files;Junction-Target $row.sourceC $row.targetE|Out-Null;Junction-Target $row.aliasF $row.sourceC|Out-Null;Alias-Hashes $row.aliasF $row.files}
    $taskResult.freeAfter=Free-Space 0
    if($taskResult.freeAfter.C -lt 1.5GB){throw 'Copies/links preserved, but actual C JPG reserve still below1.5GiB.'}
    $taskResult.applied=$true
    $taskResult.validated=$true
} catch {
    $taskResult['failureType']=$_.Exception.GetType().Name
    $taskResult['failureMessage']=$_.Exception.Message
    throw
} finally {
    $taskResult['finishedAt']=[DateTime]::UtcNow.ToString('o')
    try { Save-Json $taskApplyReceipt $taskResult }
    finally {
        if($taskHeld){$taskMutex.ReleaseMutex()}
        $taskMutex.Dispose()
    }
}
[ordered]@{mode='Apply';validated=$taskResult.validated;targets=2;files=32;bytes=$taskExpectedBytes;free=$taskResult.freeAfter;receipt=$taskApplyReceipt;receiptSha256=(Sha $taskApplyReceipt)}|ConvertTo-Json -Depth 4
