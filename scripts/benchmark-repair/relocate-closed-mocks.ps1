param([switch]$Apply, [ValidateSet('JPG','TB')][string]$Batch='JPG')
$ErrorActionPreference = 'Stop'
$taskRepo = 'F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$taskSecondRoot = 'C:\Users\y1252\.codex\visualizations\2026\10\08\01a119ed-fdf7-7c32-b323-de9bab1290b6'
$taskSourceRoot = [IO.Path]::GetFullPath((Join-Path $taskRepo '.phase1-data\repair'))
$taskTargetRoot = [IO.Path]::GetFullPath((Join-Path $taskSecondRoot 'evidence-archives'))
$taskReport = Join-Path $taskRepo 'docs\repair-2026-10-08\closed-mock-relocation.json'
$taskNames = @('skb-jpg-2026-10-08T09-46-34-645Z', 'skb-jpg-2026-10-08T09-46-44-144Z', 'skb-jpg-2026-10-08T09-48-07-694Z', 'skb-jpg-2026-10-08T09-54-51-769Z')
$taskClosure = 'measurement_repairs closure report: old mock PIDs60132/83620 and all bridge/engine/gateway/proxy stages closed; no ZIP altered'
if ($Batch -eq 'TB') {
    $taskReport = Join-Path $taskRepo 'docs\repair-2026-10-08\closed-tb-mock-relocation.json'
    $taskNames = @('tb-nginx-2026-10-08T07-48-23-195Z', 'tb-nginx-2026-10-08T07-49-30-364Z', 'tb-nginx-2026-10-08T08-35-56-432Z')
    $taskClosure = 'measurement_repairs exact-PID/CMD/container read-only audit: stand49384/83280/62176 and engine87212/84576/97804/90504 absent; no matching run PID or container; owner stopped writing'
}
function Assert-Contained([string]$Path, [string]$Root) {
    $resolved = [IO.Path]::GetFullPath($Path)
    $rootPrefix = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Target escapes the explicitly named workspace: $resolved" }
    return $resolved
}
Assert-Contained $taskSourceRoot $taskRepo | Out-Null
Assert-Contained $taskTargetRoot $taskSecondRoot | Out-Null
$taskRows = @()
foreach ($taskName in $taskNames) {
    $source = Assert-Contained (Join-Path $taskSourceRoot $taskName) $taskSourceRoot
    $target = Assert-Contained (Join-Path $taskTargetRoot $taskName) $taskTargetRoot
    if (Test-Path -LiteralPath $target) { throw "Destination already exists; inspect the prior relocation before retrying: $target" }
    $item = Get-Item -LiteralPath $source -Force
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Source must be the original ordinary owned directory: $source" }
    $entries = @(Get-ChildItem -LiteralPath $source -Force -Recurse)
    if (@($entries | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw "Unexpected reparse point inside the owned source: $source" }
    $files = @($entries | Where-Object { -not $_.PSIsContainer } | Sort-Object FullName | ForEach-Object {
        [pscustomobject]@{ relative=$_.FullName.Substring($source.Length+1); bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
    $taskRows += [pscustomobject]@{ run=$taskName; source=$source; target=$target; bytes=($files | Measure-Object bytes -Sum).Sum; files=$files; status='planned' }
}
$taskTotal = ($taskRows | Measure-Object bytes -Sum).Sum
$taskCBefore = ([IO.DriveInfo]::new('C')).AvailableFreeSpace
$taskFBefore = ([IO.DriveInfo]::new('F')).AvailableFreeSpace
if ($taskCBefore - $taskTotal -lt 1.5GB) { throw 'The destination would violate the C 1.5GiB reserve' }
$taskEvidence = [ordered]@{ createdAt=[DateTime]::UtcNow.ToString('o'); scope="Explicitly confirmed closed, owned, zero-LLM $Batch diagnostic stores only"; authorizationEvidence=$taskClosure; scriptSha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant(); applied=[bool]$Apply; validated=$false; cFreeBeforeBytes=$taskCBefore; fFreeBeforeBytes=$taskFBefore; totalBytes=$taskTotal; runs=$taskRows; limits='Preserve every file byte and original F path via NTFS junction. No paid campaign, historical run or original source manifest is changed.' }
if (-not $Apply) {
    [pscustomobject]@{ mode='review-only'; totalBytes=$taskTotal; runs=$taskNames; cFreeBytes=$taskCBefore; fFreeBytes=$taskFBefore } | ConvertTo-Json -Compress
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
        if ($link.LinkType -ne 'Junction' -or [IO.Path]::GetFullPath(@($link.Target)[0]) -ne $row.target) { throw "Unexpected junction target: $($row.source)" }
        foreach ($file in $row.files) {
            $originalPath = Join-Path $row.source $file.relative
            if ((Get-Item -LiteralPath $originalPath -Force).Length -ne $file.bytes -or (Get-FileHash -LiteralPath $originalPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $file.sha256) { throw "Relocated evidence failed byte verification: $originalPath" }
        }
        $row.status = 'junction_and_all_file_hashes_verified'
    }
    $taskEvidence.validated = $true
} catch {
    $taskEvidence['error'] = $_.Exception.Message
    throw
} finally {
    $taskEvidence['finishedAt'] = [DateTime]::UtcNow.ToString('o')
    $taskEvidence['cFreeAfterBytes'] = ([IO.DriveInfo]::new('C')).AvailableFreeSpace
    $taskEvidence['fFreeAfterBytes'] = ([IO.DriveInfo]::new('F')).AvailableFreeSpace
    [IO.File]::WriteAllText($taskReport, (($taskEvidence | ConvertTo-Json -Depth 8) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
}
[pscustomobject]@{ validated=$taskEvidence.validated; runs=$taskRows.Count; files=($taskRows.files | Measure-Object).Count; relocatedBytes=$taskTotal; cFreeBytes=$taskEvidence.cFreeAfterBytes; fFreeBytes=$taskEvidence.fFreeAfterBytes; report=$taskReport } | ConvertTo-Json -Compress
