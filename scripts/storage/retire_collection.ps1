[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Workspace,
    [Parameter(Mandatory=$true)][string]$Name,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath $Workspace).ProviderPath.TrimEnd('\')
if ($Name -notmatch '^[a-z0-9_-]+$') { throw 'Invalid collection name' }
$taskRun = Join-Path $taskRoot ('_objrun-archive\collections\' + $Name)
$taskRecordPath = Join-Path $taskRun 'record.json'
$taskRecord = Get-Content -LiteralPath $taskRecordPath -Raw | ConvertFrom-Json
if ($taskRecord.status -ne 'verified' -or -not $taskRecord.restore_verified -or -not $taskRecord.integrity_verified -or $taskRecord.source_removed) { throw 'Collection has not passed verification' }
$taskSource = [IO.Path]::GetFullPath($taskRecord.source).TrimEnd('\')
if (-not $taskSource.StartsWith($taskRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Source outside workspace' }
if ((Get-Item -LiteralPath $taskSource -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Source root is a reparse point' }
$taskRepo = Join-Path $taskRoot 'objrun'
if ($taskSource.StartsWith($taskRepo + '\', [StringComparison]::OrdinalIgnoreCase)) {
    $taskGitRelative = $taskSource.Substring($taskRepo.Length + 1).Replace('\','/')
    $taskTracked = @(& git -C $taskRepo ls-files -- $taskGitRelative)
    if ($LASTEXITCODE -ne 0 -or $taskTracked.Count -gt 0) { throw 'Source includes tracked Git files' }
}
$taskLive = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^(bun|node|python|docker|dockerd)\.exe$' -and $_.CommandLine -match 'TgEngin-handoff-2026-10-07|[\\/]objrun[\\/]' -and
    $_.CommandLine -notmatch '(archive_collection|verify_collection|stream_source_tar|preflight_retire|run_archive_plan)\.py'
})
if ($taskLive.Count -gt 0) { throw 'Project runtime is active' }
& python (Join-Path $PSScriptRoot 'preflight_retire.py') --workspace $taskRoot --name $Name
if ($LASTEXITCODE -ne 0) { throw 'Source changed or scope rejected; no files removed' }
if (-not $Apply) {
    [pscustomobject]@{mode='preview';source=$taskSource;files=$taskRecord.before.files;snapshot=$taskRecord.snapshot} | ConvertTo-Json
    return
}
$taskBeforeFree = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($taskRoot)).AvailableFreeSpace
. (Join-Path $PSScriptRoot 'retire_native.ps1')
$taskNativeJournal = Join-Path $taskRun 'retirement.jsonl'
[IO.File]::AppendAllText($taskNativeJournal,(@{event='begin';source=$taskSource;snapshot=$taskRecord.snapshot;manifest=$taskRecord.before.manifest_sha256} | ConvertTo-Json -Compress) + "`n")
$taskKeep = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($taskRel in @($taskRecord.excluded) + @($taskRecord.kept_files)) {
    if (-not $taskRel) { continue }
    $taskPreserved = [IO.Path]::GetFullPath((Join-Path $taskSource $taskRel))
    if (-not $taskPreserved.StartsWith($taskSource + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Preservation entry escaped source root' }
    while ($taskPreserved.Length -ge $taskSource.Length) {
        [void]$taskKeep.Add($taskPreserved)
        if ($taskPreserved -eq $taskSource) { break }
        $taskPreserved = [IO.Path]::GetDirectoryName($taskPreserved)
    }
}
$taskNativeDeleted = [ObjRunRetireNative]::Execute($taskSource,(Join-Path $taskRun 'retirement-input.tsv.gz'),$taskNativeJournal,[string[]]@($taskKeep))
$taskKeptCount = @($taskRecord.kept_files | Where-Object { $_ }).Count
if ($taskNativeDeleted -ne ($taskRecord.before.files - $taskKeptCount)) { throw 'Removal count differs from verified inventory' }
$taskNativeAfterFree = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($taskRoot)).AvailableFreeSpace
$taskRecord.status = 'archived'
$taskRecord.source_removed = ($taskKeep.Count -eq 0)
$taskRecord | Add-Member -NotePropertyName retirement -NotePropertyValue @{files=$taskNativeDeleted;before_free=$taskBeforeFree;after_free=$taskNativeAfterFree;free_delta=($taskNativeAfterFree-$taskBeforeFree);at=[DateTime]::UtcNow.ToString('o')} -Force
$taskRecord | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $taskRecordPath -Encoding utf8
[pscustomobject]@{collection=$Name;removed_files=$taskNativeDeleted;free_delta=($taskNativeAfterFree-$taskBeforeFree);snapshot=$taskRecord.snapshot} | ConvertTo-Json
