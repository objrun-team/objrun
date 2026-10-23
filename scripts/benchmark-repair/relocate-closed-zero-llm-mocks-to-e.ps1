[CmdletBinding(DefaultParameterSetName='DryRun')]
param(
    [Parameter(ParameterSetName='DryRun')][switch]$DryRun,
    [Parameter(Mandatory,ParameterSetName='Apply')][switch]$Apply,
    [Parameter(Mandatory,ParameterSetName='Apply')][ValidatePattern('^[0-9a-f]{64}$')][string]$PreflightSha
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$taskProject = 'F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$taskRunId = '01a119ed-fdf7-7c32-b323-de9bab1290b6'
$taskCBase = 'C:\Users\y1252\.codex\visualizations\2026\10\08\01a119ed-fdf7-7c32-b323-de9bab1290b6\evidence-archives'
$taskFBase = Join-Path $taskProject '.phase1-data\repair'
$taskEBase = 'E:\objrun-experiment-cache\01a119ed-fdf7-7c32-b323-de9bab1290b6\inactive-benchmark-archives\closed-zero-llm-mocks'
$taskMini = 'E:\objrun-experiment-cache\01a119ed-fdf7-7c32-b323-de9bab1290b6\minif2f-v415'
$taskPreflight = Join-Path $taskProject 'docs\repair-2026-10-08\closed-zero-mock-c-to-e-preflight.json'
$taskApplyReceipt = Join-Path $taskProject 'docs\repair-2026-10-08\closed-zero-mock-c-to-e-apply.json'
$taskNames = @(
    'skb-jpg-2026-10-08T09-46-34-645Z',
    'skb-jpg-2026-10-08T09-46-44-144Z',
    'skb-jpg-2026-10-08T09-48-07-694Z',
    'skb-jpg-2026-10-08T09-54-51-769Z',
    'tb-nginx-2026-10-08T07-48-23-195Z',
    'tb-nginx-2026-10-08T07-49-30-364Z',
    'tb-nginx-2026-10-08T08-35-56-432Z'
)
$taskExpectedBytes = [long]495020701
$taskExpectedFiles = 446
$taskReserve = [long](14GB + 3GB)
$taskAuditReserve = [long]4MB
$taskLegacy = @(
    @{relative='docs\repair-2026-10-08\closed-mock-relocation.json';sha256='0eb5de53fb44ff0f710538bfa84fea72d721578e69191ddc1d6f7f5f073f1bb2'},
    @{relative='docs\repair-2026-10-08\closed-tb-mock-relocation.json';sha256='33c86eb9467b1f8bd0d4074a0df2ce70bcf6261f018b52965cddf1dcf02972e9'}
)
$taskClosureCorrection = @{
    relative='docs\repair-2026-10-08\legacy-mock-stand-cleanup.json'
    sha256='6ac76aa4091d61117cd6449cb44045c0ef6dbc0432924afaa144bbbad9665799'
}

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
    while($current) {
        $excluded.Add($current)|Out-Null
        $p=$all|Where-Object ProcessId -eq $current|Select-Object -First 1
        if($null -eq $p){break}
        $current=[int]$p.ParentProcessId
    }
    $hits=@()
    foreach($p in $all) {
        if($excluded.Contains([int]$p.ProcessId)){continue}
        $line=[string]$p.CommandLine
        foreach($row in $Rows) {
            if($line.IndexOf($row.run,[StringComparison]::OrdinalIgnoreCase) -ge 0) {
                $hits += [pscustomobject]@{pid=[int]$p.ProcessId;process=$p.Name;matchedRun=$row.run};break
            }
        }
    }
    # Raw commands/config/env never enter the report. Inspect only actual bind metadata.
    $ids=@(& docker ps --no-trunc --format '{{.ID}}')
    if($LASTEXITCODE -ne 0){throw 'Actual running Docker inventory unavailable.'}
    $conflicts=@()
    if($ids.Count) {
        $raw=& docker inspect @ids
        if($LASTEXITCODE -ne 0){throw 'Actual Docker mount inventory unavailable.'}
        $objects=$raw|ConvertFrom-Json
        foreach($container in $objects) {
            foreach($mount in $container.Mounts) {
                if(-not $mount.RW){continue}
                $source=Mount-Normalize ([string]$mount.Source)
                foreach($row in $Rows) {
                    foreach($scope in @($row.sourceC,$row.aliasF,$row.targetE,$row.backupC,$row.stagedJunctionC)) {
                        if(Overlaps $source (Mount-Normalize $scope)) {
                            $conflicts += [pscustomobject]@{containerId=$container.Id;run=$row.run;source=$source;destination=$mount.Destination}
                        }
                    }
                }
            }
        }
    }
    if($hits.Count -or $conflicts.Count){throw 'A live process or actual writable mount overlaps a fixed closed archive.'}
    return [ordered]@{checkedAt=[DateTime]::UtcNow.ToString('o');hostConflicts=$hits;runningContainersChecked=$ids;writableMountConflicts=$conflicts;scope='root closure plus exact run metadata; no claim of exhaustive handle/process isolation'}
}
function Eligibility([string]$Run) {
    $group=if($Run.StartsWith('skb-')){'software-preparation'}else{'tb-preparation'}
    $base=Join-Path $taskProject ('docs\repair-2026-10-08\'+$group+'\'+$Run)
    $manifest=Join-Path $base 'manifest.json'
    $m=Get-Content -LiteralPath $manifest -Raw|ConvertFrom-Json
    if($m.provider -cne 'local-mock' -or $m.profile -notin @('zero-cost-preparation','zero-cost-validation') -or $m.priorCampaignCostUpperBoundUsd -ne 0){throw 'Exact original local-mock/zero-prior-cost mode required.'}
    if($Run.StartsWith('skb-') -and $m.mockOnly -ne $true){throw 'Original JPG mockOnly mode required.'}
    $inputs=@([ordered]@{path=$manifest;bytes=(Get-Item -LiteralPath $manifest).Length;sha256=(Sha $manifest)})
    $attempted=$null;$calls=0;$feeSource='trusted existing closure certificate; no execution/usage ledger for initial no-call store'
    $ledgerPath=Join-Path $base 'api-ledger.json'
    if(Test-Path -LiteralPath $ledgerPath) {
        $ledger=Get-Content -LiteralPath $ledgerPath -Raw|ConvertFrom-Json
        if($ledger.recordedUsageUpperBoundUsd -ne 0){throw 'Original local-mock ledger fee must be zero.'}
        $inputs+= [ordered]@{path=$ledgerPath;bytes=(Get-Item -LiteralPath $ledgerPath).Length;sha256=(Sha $ledgerPath)}
        $calls=@($ledger.calls).Count
        $attempted=@($ledger.calls|Where-Object providerAttempted -eq $true).Count
        $feeSource='original api-ledger.recordedUsageUpperBoundUsd=0'
    }
    $summaryPath=Join-Path $base 'summary.json'
    if(Test-Path -LiteralPath $summaryPath) {$inputs += [ordered]@{path=$summaryPath;bytes=(Get-Item -LiteralPath $summaryPath).Length;sha256=(Sha $summaryPath)}}
    return [ordered]@{manifestProvider=$m.provider;profile=$m.profile;mockOnly=if($Run.StartsWith('skb-')){$m.mockOnly}else{$null};realProviderAttemptedRawField=$null;localMockHTTPCalls=$calls;localMockProviderAttemptedTrueRows=$attempted;zeroFeeEvidence=$feeSource;actualRemotePaidFalseDerivedFrom='exact local-mock mode, zero fee ledger/closure and root confirmed closed zero-LLM scope; raw local flags preserved';inputFiles=$inputs}
}

$taskClosurePath=Join-Path $taskProject $taskClosureCorrection.relative
if((Sha $taskClosurePath) -cne $taskClosureCorrection.sha256){throw 'Actual later exact mock-stand closure evidence changed.'}
$taskClosure=Get-Content -LiteralPath $taskClosurePath -Raw|ConvertFrom-Json
$taskClosed=@($taskClosure.closedProcesses)
$taskFormerlyLive=@($taskNames[1],$taskNames[2],$taskNames[3])
if($taskClosed.Count -ne 3 -or $taskClosure.archiveBytesChanged -ne $false){throw 'Exact later closure/no-archive-change evidence required.'}
foreach($item in $taskClosed) {
    if($item.run -notin $taskFormerlyLive -or $item.closed -ne $true -or $item.handleIdentityChecked -ne $true -or $item.pidReusedAfterClose -ne $false){throw 'Later closure has an unresolved exact legacy process.'}
}
if(@($taskClosed.run|Sort-Object -Unique).Count -ne 3){throw 'Later closed process run set differs.'}
$taskRows=@()
foreach($pin in $taskLegacy) {
    $path=Join-Path $taskProject $pin.relative
    if((Sha $path) -cne $pin.sha256){throw 'Original validated relocation source record changed.'}
    $legacy=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json
    if($legacy.applied -ne $true -or $legacy.validated -ne $true -or $legacy.scope -notmatch 'zero-LLM' -or -not $legacy.authorizationEvidence){throw 'Actual existing closure/validated-apply proof required.'}
    foreach($row in $legacy.runs) {
        if($row.run -notin $taskNames -or $row.status -cne 'junction_and_all_file_hashes_verified'){throw 'Unexpected run or unresolved old relocation.'}
        $c=Contained (Join-Path $taskCBase $row.run) $taskCBase
        $f=Contained (Join-Path $taskFBase $row.run) $taskFBase
        $e=Contained (Join-Path $taskEBase $row.run) $taskEBase
        if((Canonical $row.target) -cne $c -or (Canonical $row.source) -cne $f -or (Overlaps $e $taskMini)){throw 'Fixed original/target relationship differs or overlaps mini owned root.'}
        $backup=Contained (Join-Path $taskCBase ($row.run+'.ce-backup-01a119ed')) $taskCBase
        $stage=Contained (Join-Path $taskCBase ($row.run+'.ce-junction-01a119ed')) $taskCBase
        foreach($dest in @($e,$backup,$stage)){if(Test-Path -LiteralPath $dest){throw 'Prior target/backup/staged junction exists; preserve it for root review, no automatic retry.'}}
        Ordinary-Ancestors $c
        Ordinary-Ancestors $taskEBase $true
        Junction-Target $f $c|Out-Null
        $inventory=Inventory $c
        Match-Files $row.files $inventory.files
        if($inventory.bytes -ne [long]$row.bytes){throw 'Original per-run byte sum differs.'}
        Alias-Hashes $f $row.files
        $taskRows += [pscustomobject]@{run=$row.run;sourceC=$c;aliasF=$f;targetE=$e;backupC=$backup;stagedJunctionC=$stage;bytes=$inventory.bytes;files=$inventory.files;directories=$inventory.directories;eligibility=(Eligibility $row.run);status='sourceC_and_original_F_alias_verified'}
    }
}
if($taskRows.Count -ne 7 -or @($taskRows.run|Sort-Object -Unique).Count -ne 7 -or [long](($taskRows|Measure-Object bytes -Sum).Sum) -ne $taskExpectedBytes -or @($taskRows.files).Count -ne $taskExpectedFiles){throw 'Fixed seven-target/446-file/495020701-byte contract differs.'}
$taskFree=Free-Space $taskExpectedBytes
$taskProbe=Writer-Probe $taskRows
$taskScriptSha=Sha $PSCommandPath
$taskResult=[ordered]@{protocol='closed-zero-mock-c-to-e-v1';createdAt=[DateTime]::UtcNow.ToString('o');scriptSha256=$taskScriptSha;mode=if($Apply){'Apply'}else{'DryRun'};applied=$false;validated=$false;targets=7;files=446;bytes=$taskExpectedBytes;originalRecords=$taskLegacy;closureCorrection=$taskClosureCorrection;earlierClosureOmittedSurvivingStands=$true;freeBefore=$taskFree;writerProbe=$taskProbe;miniOwnedRootModified=$false;providerCalled=$false;sourceRawModified=$false;runs=$taskRows;failurePolicy='retain all new target copies and C backups/staged links; no rollback or cleanup on failure'}
if(-not $Apply) {
    $taskResult.validated=$true
    $taskResult['C_logical_bytes_expected_recovered']=$taskExpectedBytes
    $taskResult['E_minimum_start_bytes']=[long]($taskReserve+$taskExpectedBytes+$taskAuditReserve)
    Save-Json $taskPreflight $taskResult
    [ordered]@{mode='DryRun';C_E_modified=$false;validated=$true;targets=7;files=446;bytes=$taskExpectedBytes;free=$taskFree;preflight=$taskPreflight;preflightSha256=(Sha $taskPreflight)}|ConvertTo-Json -Depth 4
    exit 0
}
if((Sha $taskPreflight) -cne $PreflightSha){throw 'Root-reviewed exact preflight SHA required before Apply.'}
$previous=Get-Content -LiteralPath $taskPreflight -Raw|ConvertFrom-Json
if($previous.scriptSha256 -cne $taskScriptSha -or $previous.protocol -cne 'closed-zero-mock-c-to-e-v1' -or -not $previous.validated -or $previous.applied){throw 'Fresh same-script DryRun proof required.'}
foreach($row in $taskRows) {
    $old=@($previous.runs|Where-Object run -eq $row.run)
    if($old.Count -ne 1){throw 'Preflight fixed run set changed.'}
    Match-Files $old[0].files $row.files
    foreach($entry in $row.eligibility.inputFiles) {
        $oldEntry=@($old[0].eligibility.inputFiles|Where-Object path -eq $entry.path)
        if($oldEntry.Count -ne 1 -or $oldEntry[0].sha256 -cne $entry.sha256){throw 'Original mock mode/fee raw evidence changed.'}
    }
}
if(Test-Path -LiteralPath $taskApplyReceipt){throw 'Existing Apply receipt requires review; no rerun or overwrite.'}
$taskMutex=[Threading.Mutex]::new($false,'Local\TgEnginClosedZeroMockRelocation-01a119ed')
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
    # No C rename/removal happens before ALL seven E copies pass hashes.
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
    # ALL C/F chains work before any old physical C duplicate is removed.
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
[ordered]@{mode='Apply';validated=$taskResult.validated;targets=7;files=446;bytes=$taskExpectedBytes;free=$taskResult.freeAfter;receipt=$taskApplyReceipt;receiptSha256=(Sha $taskApplyReceipt)}|ConvertTo-Json -Depth 4
