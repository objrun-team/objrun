param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$taskRepo = 'F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$taskSecondRoot = 'C:\Users\y1252\.codex\visualizations\2026\10\08\01a119ed-fdf7-7c32-b323-de9bab1290b6'
$taskSourceRoot = [IO.Path]::GetFullPath((Join-Path $taskRepo 'examples\benchmark\terminal-bench'))
$taskTargetRoot = [IO.Path]::GetFullPath((Join-Path $taskSecondRoot 'public-runtime-cache\terminal-bench'))
$taskReport = Join-Path $taskRepo 'docs\repair-2026-10-08\tb-public-runtime-relocation.json'
function Assert-Contained([string]$Path, [string]$Root) {
    $resolved = [IO.Path]::GetFullPath($Path)
    $prefix = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Resolved target escapes its named workspace: $resolved" }
    return $resolved
}
function Assert-NoReparseAncestors([string]$Path, [string]$Root) {
    $current = [IO.Path]::GetFullPath($Path)
    $stop = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    while ($current -and $current -ne $stop) {
        if (Test-Path -LiteralPath $current) {
            if ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Unexpected ancestor reparse point: $current" }
        }
        $current = Split-Path -Parent $current
    }
}
Assert-Contained $taskSourceRoot $taskRepo | Out-Null
Assert-Contained $taskTargetRoot $taskSecondRoot | Out-Null
Assert-NoReparseAncestors $taskSourceRoot $taskRepo
Assert-NoReparseAncestors $taskTargetRoot $taskSecondRoot
$taskRows = @()
foreach ($taskName in @('.runtime', '.verifier-deps')) {
    $source = Assert-Contained (Join-Path $taskSourceRoot $taskName) $taskSourceRoot
    $target = Assert-Contained (Join-Path $taskTargetRoot $taskName) $taskTargetRoot
    if (Test-Path -LiteralPath $target) { throw "Destination already exists; inspect prior receipt: $target" }
    $item = Get-Item -LiteralPath $source -Force
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Expected original ordinary public dependency directory' }
    $entries = @(Get-ChildItem -LiteralPath $source -Force -Recurse)
    if (@($entries | Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}).Count) { throw 'Unexpected reparse point in public dependency input' }
    $files = @($entries | Where-Object {-not $_.PSIsContainer} | Sort-Object FullName | ForEach-Object {
        [pscustomobject]@{relative=$_.FullName.Substring($source.Length+1); bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
    })
    $taskRows += [pscustomobject]@{name=$taskName; source=$source; target=$target; files=$files; bytes=($files | Measure-Object bytes -Sum).Sum; status='planned'}
}
$taskTotal = ($taskRows | Measure-Object bytes -Sum).Sum
$taskCBefore = ([IO.DriveInfo]::new('C')).AvailableFreeSpace
$taskFBefore = ([IO.DriveInfo]::new('F')).AvailableFreeSpace
if ($taskCBefore-$taskTotal -lt 1.5GB) { throw 'Migration would cross the C 1.5GiB reserve' }
$taskEvidence = [ordered]@{createdAt=[DateTime]::UtcNow.ToString('o'); scriptSha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant(); scope='Owned public TB runtime and verifier dependency bytes only'; closureEvidence='measurement_repairs confirmed no writer, no live TB candidate/bootstrap; new JPG code reads these paths only. Current paid ChemIQ does not use them.'; applied=[bool]$Apply; validated=$false; cFreeBeforeBytes=$taskCBefore; fFreeBeforeBytes=$taskFBefore; totalBytes=$taskTotal; directories=$taskRows; preserved='Every file byte, original F logical paths, frozen source/provenance/archives. No paid or historical record moved.'}
if (-not $Apply) {
    [pscustomobject]@{mode='review-only'; directories=$taskRows.Count; files=($taskRows.files | Measure-Object).Count; totalBytes=$taskTotal; cFreeBytes=$taskCBefore; fFreeBytes=$taskFBefore} | ConvertTo-Json -Compress
    exit 0
}
New-Item -ItemType Directory -Path $taskTargetRoot -Force | Out-Null
try {
    foreach ($row in $taskRows) {
        Assert-Contained $row.source $taskSourceRoot | Out-Null
        Assert-Contained $row.target $taskTargetRoot | Out-Null
        Move-Item -LiteralPath $row.source -Destination $row.target
        $row.status = 'moved'
        New-Item -ItemType Junction -Path $row.source -Target $row.target | Out-Null
        $link = Get-Item -LiteralPath $row.source -Force
        if ($link.LinkType -ne 'Junction' -or [IO.Path]::GetFullPath(@($link.Target)[0]) -ne $row.target) { throw 'Unexpected migrated junction target' }
        foreach ($file in $row.files) {
            $path = Join-Path $row.source $file.relative
            if ((Get-Item -LiteralPath $path -Force).Length -ne $file.bytes -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.sha256) { throw "Migrated public file bytes differ: $path" }
        }
        $row.status='junction_and_all_file_hashes_verified'
    }
    $taskEvidence.validated=$true
} catch {
    $taskEvidence['error']=$_.Exception.Message
    throw
} finally {
    $taskEvidence['finishedAt']=[DateTime]::UtcNow.ToString('o')
    $taskEvidence['cFreeAfterBytes']=([IO.DriveInfo]::new('C')).AvailableFreeSpace
    $taskEvidence['fFreeAfterBytes']=([IO.DriveInfo]::new('F')).AvailableFreeSpace
    [IO.File]::WriteAllText($taskReport,(($taskEvidence | ConvertTo-Json -Depth 8)+[Environment]::NewLine),[Text.UTF8Encoding]::new($false))
}
[pscustomobject]@{validated=$taskEvidence.validated; directories=$taskRows.Count; files=($taskRows.files | Measure-Object).Count; relocatedBytes=$taskTotal; cFreeBytes=$taskEvidence.cFreeAfterBytes; fFreeBytes=$taskEvidence.fFreeAfterBytes; report=$taskReport} | ConvertTo-Json -Compress
