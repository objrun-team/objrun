param(
    [switch]$Apply,
    [string]$ApprovedPreflightSha256 = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$taskRepo = 'F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$taskSource = 'F:\git\TgEngin-handoff-2026-10-07\TgEngin\.phase1-data\scicode-verified'
$taskDestinationRoot = 'E:\objrun-experiment-cache\01a119ed-fdf7-7c32-b323-de9bab1290b6\inactive-benchmark-archives'
$taskTarget = Join-Path $taskDestinationRoot 'scicode-verified'
$taskEvidenceRoot = Join-Path $taskRepo 'docs\repair-2026-10-08\storage-actions\scicode-cold-cache'
$taskPreflightPath = Join-Path $taskEvidenceRoot 'preflight.json'
$taskExpectedFiles = 155
$taskExpectedBytes = 1113827547L
$taskFutureMiniReserve = 14GB
$taskActualFreeReserve = 3GB
$taskFReserve = 1GB
$taskAllocationAllowance = 32MB

function Assert-Contained([string]$Path, [string]$Root, [switch]$AllowRoot) {
    $resolved = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    if (($AllowRoot -and $resolved.Equals($rootPath, [StringComparison]::OrdinalIgnoreCase)) -or $resolved.StartsWith($rootPath + '\', [StringComparison]::OrdinalIgnoreCase)) { return $resolved }
    throw "Absolute path escapes its explicitly named root: $resolved"
}

function Assert-NoReparseAncestors([string]$Path) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Unexpected reparse ancestor: $current" }
        }
        $parent = Split-Path -Parent $current
        if (-not $parent -or $parent -eq $current) { break }
        $current = $parent
    }
}

function Get-Sha256([byte[]]$Bytes) {
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return [Convert]::ToHexString($hasher.ComputeHash($Bytes)).ToLowerInvariant() }
    finally { $hasher.Dispose() }
}

function Save-Json([string]$Path, $Value) {
    $checked = Assert-Contained $Path $taskEvidenceRoot
    Assert-NoReparseAncestors (Split-Path -Parent $checked)
    if ((Test-Path -LiteralPath $checked) -and ((Get-Item -LiteralPath $checked -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Evidence file may not be a reparse point' }
    [IO.Directory]::CreateDirectory((Split-Path -Parent $checked)) | Out-Null
    $temporary = $checked + '.tmp-' + [Guid]::NewGuid().ToString('N')
    [IO.File]::WriteAllText($temporary, (($Value | ConvertTo-Json -Depth 12) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $checked -Force
}

function Get-Inventory([string]$Root, [switch]$ExpectedJunction) {
    $checkedRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $rootItem = Get-Item -LiteralPath $checkedRoot -Force
    if (-not $rootItem.PSIsContainer) { throw 'Cold benchmark cache must be a directory' }
    if (-not $ExpectedJunction -and ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Cold cache root is unexpectedly a reparse point' }
    $pending = [Collections.Generic.Queue[string]]::new()
    $pending.Enqueue($checkedRoot)
    $directories = [Collections.Generic.List[string]]::new()
    $directories.Add('')
    $files = [Collections.Generic.List[object]]::new()
    while ($pending.Count) {
        $directory = $pending.Dequeue()
        foreach ($item in @(Get-ChildItem -LiteralPath $directory -Force)) {
            $absolute = Assert-Contained $item.FullName $checkedRoot
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse entry in cold cache: $absolute" }
            $relative = $absolute.Substring($checkedRoot.Length + 1).Replace('\', '/')
            if ($item.PSIsContainer) {
                $directories.Add($relative)
                $pending.Enqueue($absolute)
                continue
            }
            # Exclusive read proves no incompatible open handle at this check;
            # it is not a claim that future readers cannot arrive.
            $stream = [IO.File]::Open($absolute, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
            $hasher = [Security.Cryptography.SHA256]::Create()
            try {
                $length = $stream.Length
                $digest = [Convert]::ToHexString($hasher.ComputeHash($stream)).ToLowerInvariant()
                if ($stream.Length -ne $length) { throw 'A cache file changed during its exclusive hash read' }
                $files.Add([pscustomobject][ordered]@{relative=$relative; bytes=$length; sha256=$digest})
            } finally { $hasher.Dispose(); $stream.Dispose() }
        }
    }
    $orderedFiles = @($files | Sort-Object relative -CaseSensitive)
    $orderedDirectories = @($directories | Sort-Object -CaseSensitive)
    $descriptor = [ordered]@{directories=$orderedDirectories; files=$orderedFiles}
    $descriptorBytes = [Text.Encoding]::UTF8.GetBytes(($descriptor | ConvertTo-Json -Depth 5 -Compress))
    return [pscustomobject][ordered]@{
        root=$checkedRoot; directories=$orderedDirectories; files=$orderedFiles
        fileCount=$orderedFiles.Count; directoryCount=$orderedDirectories.Count
        bytes=[long](($orderedFiles | Measure-Object bytes -Sum).Sum)
        inventorySha256=(Get-Sha256 $descriptorBytes)
        exclusiveFileReadsPassed=$orderedFiles.Count; reparseEntries=0
    }
}

function Get-Activity {
    $sourceSlash = $taskSource.Replace('\', '/')
    $targetSlash = $taskTarget.Replace('\', '/')
    $matching = @()
    foreach ($process in @(Get-CimInstance Win32_Process)) {
        if ($process.ProcessId -eq $PID -or -not $process.CommandLine) { continue }
        $line = [string]$process.CommandLine
        $mentions = $line.IndexOf($taskSource, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or $line.IndexOf($sourceSlash, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or $line.IndexOf($taskTarget, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or $line.IndexOf($targetSlash, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or $line.IndexOf('scicode', [StringComparison]::OrdinalIgnoreCase) -ge 0
        if ($mentions) { $matching += [pscustomobject]@{pid=$process.ProcessId; name=$process.Name; creationDate=$process.CreationDate; matchingCommandLinePresent=$true} }
    }
    $ids = @(& docker container ls -aq 2>&1)
    if ($LASTEXITCODE -ne 0) { throw 'Docker inventory unavailable; activity cannot be certified' }
    $containers = @()
    $mountMatches = @()
    $posixSource = '/f/' + $taskSource.Substring(3).Replace('\', '/')
    foreach ($id in $ids) {
        if (-not $id) { continue }
        $raw = @(& docker container inspect $id 2>&1)
        if ($LASTEXITCODE -ne 0) { throw 'A container inspect failed; do not assume the cache is unmounted' }
        $config = @(($raw -join [Environment]::NewLine) | ConvertFrom-Json)[0]
        $mounts = @()
        foreach ($mount in @($config.Mounts)) {
            $normalized = ([string]$mount.Source).Replace('\', '/').TrimEnd('/')
            $variants = @($sourceSlash, ('/mnt' + $posixSource), ('/host_mnt' + $posixSource), ('/run/desktop/mnt/host' + $posixSource))
            $intersects = $false
            foreach ($variant in $variants) {
                $intersects = $intersects -or $normalized.Equals($variant, [StringComparison]::OrdinalIgnoreCase) -or $normalized.StartsWith($variant + '/', [StringComparison]::OrdinalIgnoreCase) -or ($normalized -and $variant.StartsWith($normalized + '/', [StringComparison]::OrdinalIgnoreCase))
            }
            $mounts += [pscustomobject]@{type=$mount.Type; source=$mount.Source; destination=$mount.Destination; intersectsColdCache=$intersects}
            if ($intersects) { $mountMatches += [pscustomobject]@{containerId=$config.Id; source=$mount.Source; destination=$mount.Destination} }
        }
        $commandMentions = (($config.Name + ' ' + ($config.Config.Cmd -join ' ') + ' ' + ($config.Config.Entrypoint -join ' ')).IndexOf('scicode', [StringComparison]::OrdinalIgnoreCase) -ge 0)
        $containers += [pscustomobject]@{containerId=$config.Id; name=$config.Name; running=$config.State.Running; imageId=$config.Image; commandMentionsSciCode=$commandMentions; mounts=$mounts}
    }
    return [pscustomobject]@{
        observedAt=[DateTime]::UtcNow.ToString('o'); matchingProcesses=$matching
        inspectedContainerCount=$containers.Count; containers=$containers; matchingMounts=$mountMatches
        coldCacheContainers=@($containers | Where-Object commandMentionsSciCode)
        queryScope='Process command-line SciCode/path matching, complete daemon mount inventory, and exclusive per-file hash reads. No exhaustive kernel-handle or future-activity claim.'
        inactive=($matching.Count -eq 0 -and $mountMatches.Count -eq 0 -and @($containers | Where-Object commandMentionsSciCode).Count -eq 0)
    }
}

function Get-Space([long]$PlannedBytes) {
    $e = [IO.DriveInfo]::new('E')
    $f = [IO.DriveInfo]::new('F')
    if ($e.DriveFormat -ne 'NTFS' -or $f.DriveFormat -ne 'NTFS') { throw 'Both explicitly named volumes must be NTFS' }
    $projected = $e.AvailableFreeSpace - $PlannedBytes - $taskAllocationAllowance
    return [pscustomobject]@{
        eFreeBytes=$e.AvailableFreeSpace; fFreeBytes=$f.AvailableFreeSpace
        plannedBytes=$PlannedBytes; allocationAllowanceBytes=$taskAllocationAllowance
        futureMiniReserveBytes=$taskFutureMiniReserve; actualFreeAfterFutureMiniReserveBytes=$taskActualFreeReserve
        minimumEFreeAfterMigrationBytes=($taskFutureMiniReserve + $taskActualFreeReserve)
        eProjectedFreeAfterMigrationBytes=$projected; minimumFFreeBytes=$taskFReserve
        sufficient=($projected -ge ($taskFutureMiniReserve + $taskActualFreeReserve) -and $f.AvailableFreeSpace -ge $taskFReserve)
    }
}

function Get-RecoveryLocations($Inventory) {
    $locations = @()
    foreach ($file in $Inventory.files) {
        $locations += [pscustomobject]@{
            relative=$file.relative; expectedBytes=$file.bytes; expectedSha256=$file.sha256
            sourcePath=(Join-Path $taskSource $file.relative); targetPath=(Join-Path $taskTarget $file.relative)
            sourceExists=(Test-Path -LiteralPath (Join-Path $taskSource $file.relative))
            targetExists=(Test-Path -LiteralPath (Join-Path $taskTarget $file.relative))
        }
    }
    return [pscustomobject]@{automaticRecoveryExecuted=$false; files=$locations; instructions='Keep both locations and the operation journal. Recheck exact per-file SHA at each existing location. Do not remove duplicates, partial targets, or an unexpected junction. Root must review a new explicit recovery plan before any further mutation.'}
}

Assert-Contained $taskSource $taskRepo | Out-Null
Assert-Contained $taskTarget $taskDestinationRoot | Out-Null
Assert-Contained $taskEvidenceRoot $taskRepo | Out-Null
if ([IO.Path]::GetFullPath($taskSource) -ne $taskSource -or [IO.Path]::GetFullPath($taskTarget) -ne $taskTarget -or [IO.Path]::GetPathRoot($taskSource) -ne 'F:\' -or [IO.Path]::GetPathRoot($taskTarget) -ne 'E:\') { throw 'Unexpected resolved absolute source or target' }
Assert-NoReparseAncestors $taskSource
Assert-NoReparseAncestors $taskTarget
Assert-NoReparseAncestors $taskEvidenceRoot
if (Test-Path -LiteralPath $taskTarget) { throw 'Target already exists. Preserve it and review any prior operation; no merge or prune is permitted.' }
$taskScriptSha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
$taskInventory = Get-Inventory $taskSource
if ($taskInventory.fileCount -ne $taskExpectedFiles -or $taskInventory.bytes -ne $taskExpectedBytes) { throw 'Cold cache differs from the specified 155 files / 1113827547 bytes. Review the changed input before moving it.' }
$taskActivity = Get-Activity
$taskSpace = Get-Space $taskInventory.bytes
$taskReady = $taskActivity.inactive -and $taskSpace.sufficient

if (-not $Apply) {
    $taskPreflight = [ordered]@{
        schemaVersion=1; phase='prepared'; preparedAt=[DateTime]::UtcNow.ToString('o')
        scriptPath=$PSCommandPath; scriptSha256=$taskScriptSha256
        scope='Cold benchmark cache; no assertion that every file is public'
        source=$taskSource; target=$taskTarget; mode='prepare-only; no E writes or cache mutation'
        inventory=$taskInventory; activity=$taskActivity; space=$taskSpace; readyForReviewedApply=$taskReady
        exclusions='No active science store, .env, old run, minif2f-v415 root, Docker VHD or unrelated directory is touched.'
        applyProtocol='Require this preflight exact SHA and unchanged script/inventory, repeat activity/space guards, native Move-Item then target SHA/dirs verification, NTFS junction, original logical-path SHA/dirs verification. Failure preserves moved bytes and recovery locations.'
    }
    Save-Json $taskPreflightPath $taskPreflight
    [pscustomobject]@{mode='prepare-only'; ready=$taskReady; files=$taskInventory.fileCount; directories=$taskInventory.directoryCount; bytes=$taskInventory.bytes; inventorySha256=$taskInventory.inventorySha256; preflight=$taskPreflightPath; preflightSha256=(Get-FileHash -LiteralPath $taskPreflightPath -Algorithm SHA256).Hash.ToLowerInvariant(); scriptSha256=$taskScriptSha256} | ConvertTo-Json -Compress
    exit $(if ($taskReady) { 0 } else { 2 })
}

if ($ApprovedPreflightSha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'Apply requires the exact preflight SHA reviewed by root' }
Assert-NoReparseAncestors $taskPreflightPath
if ((Get-FileHash -LiteralPath $taskPreflightPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ApprovedPreflightSha256.ToLowerInvariant()) { throw 'Reviewed preflight SHA does not match' }
$taskApproved = Get-Content -LiteralPath $taskPreflightPath -Raw | ConvertFrom-Json
if ($taskApproved.phase -ne 'prepared' -or $taskApproved.scriptSha256 -ne $taskScriptSha256 -or $taskApproved.source -ne $taskSource -or $taskApproved.target -ne $taskTarget -or $taskApproved.inventory.inventorySha256 -ne $taskInventory.inventorySha256 -or -not $taskApproved.readyForReviewedApply -or -not $taskReady) { throw 'Apply preflight is changed, stale or currently blocked' }
$taskJournalPath = Join-Path $taskEvidenceRoot ('operation-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [Guid]::NewGuid().ToString('N') + '.json')
$taskJournal = [ordered]@{schemaVersion=1; phase='before_move'; startedAt=[DateTime]::UtcNow.ToString('o'); source=$taskSource; target=$taskTarget; scriptSha256=$taskScriptSha256; approvedPreflightSha256=$ApprovedPreflightSha256.ToLowerInvariant(); inventory=$taskInventory; activity=$taskActivity; spaceBefore=$taskSpace; validated=$false}
Save-Json $taskJournalPath $taskJournal
try {
    # Verify the exact absolute targets immediately before the recursive move.
    Assert-Contained $taskSource $taskRepo | Out-Null
    Assert-Contained $taskTarget $taskDestinationRoot | Out-Null
    Assert-NoReparseAncestors $taskSource
    Assert-NoReparseAncestors $taskTarget
    if (Test-Path -LiteralPath $taskTarget) { throw 'Destination appeared after preflight; preserve it' }
    [IO.Directory]::CreateDirectory($taskDestinationRoot) | Out-Null
    Assert-NoReparseAncestors $taskTarget
    Move-Item -LiteralPath $taskSource -Destination $taskTarget
    $taskJournal.phase='moved_before_junction'; Save-Json $taskJournalPath $taskJournal
    if (Test-Path -LiteralPath $taskSource) { throw 'Native move left a source path; preserve both locations for reviewed recovery' }
    $targetInventory = Get-Inventory $taskTarget
    if ($targetInventory.inventorySha256 -ne $taskInventory.inventorySha256) { throw 'Target bytes or directory list differ from the approved inventory' }
    Assert-NoReparseAncestors (Split-Path -Parent $taskSource)
    Assert-NoReparseAncestors $taskTarget
    New-Item -ItemType Junction -Path $taskSource -Target $taskTarget | Out-Null
    $link = Get-Item -LiteralPath $taskSource -Force
    if ($link.LinkType -ne 'Junction' -or [IO.Path]::GetFullPath(@($link.Target)[0]).TrimEnd('\') -ne $taskTarget) { throw 'Created junction has an unexpected target' }
    $logicalInventory = Get-Inventory $taskSource -ExpectedJunction
    if ($logicalInventory.inventorySha256 -ne $taskInventory.inventorySha256) { throw 'Original F logical-path bytes or directory list differ' }
    $taskJournal['spaceAfter'] = Get-Space 0
    if (-not $taskJournal.spaceAfter.sufficient) { throw 'Post-migration host reserve is below the required E or F floor' }
    $taskJournal['targetInventorySha256']=$targetInventory.inventorySha256
    $taskJournal['originalLogicalPathInventorySha256']=$logicalInventory.inventorySha256
    $taskJournal['junctionTarget']=$taskTarget
    $taskJournal.phase='junction_and_all_bytes_verified'; $taskJournal.validated=$true
} catch {
    $taskJournal.phase='failed_preserve_all_locations'
    $taskJournal['error']=$_.Exception.Message
    $taskJournal['recovery']=Get-RecoveryLocations $taskInventory
    throw
} finally {
    $taskJournal['finishedAt']=[DateTime]::UtcNow.ToString('o')
    Save-Json $taskJournalPath $taskJournal
}
[pscustomobject]@{validated=$taskJournal.validated; relocatedBytes=$taskInventory.bytes; files=$taskInventory.fileCount; directories=$taskInventory.directoryCount; sourceLogicalPath=$taskSource; junctionTarget=$taskTarget; operationReport=$taskJournalPath} | ConvertTo-Json -Compress
