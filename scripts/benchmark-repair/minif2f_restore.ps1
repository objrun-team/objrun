[CmdletBinding()]
param(
    [ValidateSet('Gate', 'Download', 'Bootstrap', 'CacheDownload', 'UnpackAndProbe', 'Archive', 'CleanOwned')]
    [string]$Stage = 'Gate'
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$CacheRoot = 'E:\objrun-experiment-cache\01a119ed-fdf7-7c32-b323-de9bab1290b6\minif2f-v415'
$RunId = '01a119ed-fdf7-7c32-b323-de9bab1290b6'
$ImageId = 'sha256:adccbc2412fe240d3bba28a81e136d2e816a28b003263a2f1738098a67cbfbba'
$PublicRoot = Join-Path $ProjectRoot '.phase1-data\minif2f-restoration-public'
$ProfilePath = Join-Path $ProjectRoot 'docs\repair-2026-10-08\minif2f-restoration-preflight.json'
$Worker = Join-Path $PSScriptRoot 'minif2f_restore.py'
$Python = Join-Path $ProjectRoot '.phase1-data\venv\Scripts\python.exe'
$Profile = Get-Content -LiteralPath $ProfilePath -Raw | ConvertFrom-Json

function Assert-ExactRoot {
    $resolved = [IO.Path]::GetFullPath($CacheRoot).TrimEnd('\')
    $expected = 'E:\objrun-experiment-cache\01a119ed-fdf7-7c32-b323-de9bab1290b6\minif2f-v415'
    if ($resolved -cne $expected) { throw 'Resolved cache path differs from the reviewed exact E root.' }
    # Reject an existing junction in any ancestor before creation, mounting, or deletion.
    $current = $resolved
    while ($current -and $current -ne 'E:\') {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'A cache ancestor is a reparse point.' }
        }
        $current = Split-Path -Parent $current
    }
}

function Assert-Reserves {
    $driveE = Get-PSDrive -Name E -PSProvider FileSystem
    $driveF = Get-PSDrive -Name F -PSProvider FileSystem
    if ($driveE.Free -lt 3GB) { throw 'E free space fell below 3 GiB.' }
    if ($driveF.Free -lt 1GB) { throw 'F free space fell below 1 GiB.' }
}

function Assert-Owned {
    Assert-ExactRoot
    $markerPath = Join-Path $CacheRoot 'owned-root.json'
    if (-not (Test-Path -LiteralPath $markerPath)) { throw 'No matching owned-root marker.' }
    $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
    if ($marker.run_id -ne $RunId -or $marker.host_root -ne $CacheRoot.Replace('\','/')) { throw 'Owned-root marker differs.' }
}

function Assert-FrozenPublic {
    if ($Profile.existing_container_image_id -ne $ImageId) { throw 'Profile image changed.' }
    if ($Profile.pins.mathlib4 -ne '9837ca9d65d9de6fad1ef4381750ca688774e608' -or $Profile.pins.repl -ne '21966799da3691a0912b5a15193585bd2dd7165d') { throw 'Formal dependency pins changed.' }
    $actual = (Get-FileHash -LiteralPath (Join-Path $PublicRoot 'public-lock.json') -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Profile.public_lock.sha256) { throw 'Public lock differs from the reviewed preflight.' }
    $actualBook = (Get-FileHash -LiteralPath (Join-Path $PublicRoot 'problems.jsonl') -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualBook -ne $Profile.public_all_problem_file.sha256) { throw 'Pinned 488-question metadata changed.' }
    foreach ($source in @($Profile.adapter_files) + @($Profile.reviewed_plan_files)) {
        $actualSource = (Get-FileHash -LiteralPath $source.path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualSource -ne $source.sha256) { throw 'A reviewed adapter or restoration script changed; refresh the review before execution.' }
    }
}

function Invoke-OfflineContainer([string]$ContainerStage) {
    Assert-Owned
    Assert-Reserves
    $actualImage = & docker image inspect $ImageId --format '{{.Id}}'
    if ($LASTEXITCODE -ne 0 -or $actualImage.Trim() -ne $ImageId) { throw 'The exact cached scientific image is unavailable.' }
    $auditRoot = Join-Path $CacheRoot 'audit'
    New-Item -ItemType Directory -Path $auditRoot -Force | Out-Null
    $name = 'minif2f-restore-' + $ContainerStage + '-' + $RunId.Substring(0,8)
    $arguments = @(
        'create', '--name', $name, '--pull', 'never', '--network', 'none', '--read-only',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--user', '0:0',
        '--cpus', '2', '--memory', '12g', '--memory-swap', '12g', '--pids-limit', '128',
        '--log-driver', 'none', '--shm-size', '16m',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=117440512,mode=1777',
        '--label', "tgengin.minif2f-owned=$RunId",
        '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', 'HOME=/cache/home',
        '--env', "PUBLIC_LOCK_SHA256=$($Profile.public_lock.sha256)",
        '--env', "PROBLEMS_SHA256=$($Profile.public_all_problem_file.sha256)",
        '--mount', "type=bind,source=$CacheRoot,target=/cache",
        '--mount', "type=bind,source=$PublicRoot,target=/public,readonly",
        '--mount', "type=bind,source=$Worker,target=/plan/minif2f_restore.py,readonly",
        '--mount', "type=bind,source=$(Join-Path $PSScriptRoot 'minif2f_restore.sh'),target=/plan/minif2f_restore.sh,readonly",
        '--mount', "type=bind,source=$(Join-Path $PSScriptRoot 'mathlib_cache_manifest.lean'),target=/plan/mathlib_cache_manifest.lean,readonly",
        '--mount', "type=bind,source=$(Join-Path $ProjectRoot 'examples\benchmark\minif2f\stand.py'),target=/plan/stand.py,readonly",
        '--entrypoint', '/bin/bash', $ImageId, '/plan/minif2f_restore.sh', $ContainerStage
    )
    $containerId = (& docker @arguments).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $containerId) { throw 'Could not create the dedicated offline container.' }
    try {
        $inspection = & docker inspect --size $containerId
        if ($LASTEXITCODE -ne 0) { throw 'Could not inspect container restrictions.' }
        $inspection | Set-Content -LiteralPath (Join-Path $auditRoot ($ContainerStage + '-container.json')) -Encoding utf8
        $object = ($inspection | ConvertFrom-Json)[0]
        if (-not $object.HostConfig.ReadonlyRootfs -or $object.HostConfig.NetworkMode -ne 'none' -or $object.SizeRw -gt 128MB) { throw 'Container isolation or writable-layer limit differs.' }
        $stdout = Join-Path $auditRoot ($ContainerStage + '-stdout.log')
        $stderr = Join-Path $auditRoot ($ContainerStage + '-stderr.log')
        $process = Start-Process -FilePath 'docker' -ArgumentList @('start', '--attach', $containerId) -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $began = [DateTime]::UtcNow
        while (-not $process.HasExited) {
            Start-Sleep -Seconds 2
            Assert-Reserves
            # Native host checks the actual E volume while workers bound each
            # extraction/download. Abort before crossing the full directory cap.
            $bytes = (Get-ChildItem -LiteralPath $CacheRoot -File -Recurse -Force | Measure-Object -Property Length -Sum).Sum
            if ($bytes -gt 14GB) { throw 'Owned cache logical bytes exceed the 14 GiB cap.' }
            if (([DateTime]::UtcNow-$began).TotalHours -gt 3) { throw 'Public restoration stage exceeded its three-hour wall limit.' }
            $process.Refresh()
        }
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw "Offline stage failed; preserve the owned receipts and inspect $stderr." }
        Assert-Reserves
        if (Test-Path -LiteralPath $stdout) { Get-Content -LiteralPath $stdout -Tail 4 }
    } finally {
        # Exactly the container ID created above is removed. No image, volume,
        # other container, Docker location, or global setting is changed.
        & docker rm --force $containerId | Out-Null
    }
}

Assert-ExactRoot
Assert-Reserves
Assert-FrozenPublic
if ($Stage -eq 'Gate') {
    $driveE = Get-PSDrive -Name E -PSProvider FileSystem
    $driveF = Get-PSDrive -Name F -PSProvider FileSystem
    if (-not (Test-Path -LiteralPath $CacheRoot) -and $driveE.Free -lt 17GB) { throw 'A fresh 14 GiB envelope cannot leave the required 3 GiB reserve.' }
    [ordered]@{ stage='Gate'; root=$CacheRoot; rootCreated=$false; directoryCapBytes=14GB; eFreeBytes=$driveE.Free; fFreeBytes=$driveF.Free; eReserveBytes=3GB; fReserveBytes=1GB; image=$ImageId; candidateRun=$false } | ConvertTo-Json
} elseif ($Stage -eq 'Download') {
    & $Python -X utf8 $Worker download --root $CacheRoot --public $PublicRoot --lock-sha $Profile.public_lock.sha256
    if ($LASTEXITCODE -ne 0) { throw 'Public Lean acquisition failed; no executable was run.' }
} elseif ($Stage -eq 'Bootstrap') {
    Invoke-OfflineContainer 'bootstrap'
} elseif ($Stage -eq 'CacheDownload') {
    Assert-Owned
    & $Python -X utf8 $Worker cache-download --root $CacheRoot
    if ($LASTEXITCODE -ne 0) { throw 'Public Mathlib cache acquisition failed; preserve owned receipts.' }
} elseif ($Stage -eq 'UnpackAndProbe') {
    Invoke-OfflineContainer 'unpack-probe'
} elseif ($Stage -eq 'Archive') {
    Assert-Owned
    $source = Join-Path $CacheRoot 'audit'
    $destination = Join-Path $ProjectRoot 'docs\repair-2026-10-08\minif2f-restoration-execution'
    $bytes = (Get-ChildItem -LiteralPath $source -File -Recurse -Force | Measure-Object -Property Length -Sum).Sum
    if ($bytes -gt 32MB -or (Get-PSDrive F).Free-$bytes -lt 1GB) { throw 'Review archive would exceed the 32 MiB limit or F reserve.' }
    if (Test-Path -LiteralPath $destination) { throw 'Refuse overwriting an earlier execution archive.' }
    Copy-Item -LiteralPath $source -Destination $destination -Recurse
    Get-ChildItem -LiteralPath $destination -File | Get-FileHash -Algorithm SHA256 | Select-Object Path,Hash | ConvertTo-Json
} elseif ($Stage -eq 'CleanOwned') {
    # Run only after Archive when the main task decides to clean this exact
    # owned E root. Refuse reparse directories rather than following any link.
    Assert-Owned
    $archive = Join-Path $ProjectRoot 'docs\repair-2026-10-08\minif2f-restoration-execution'
    if (-not (Test-Path -LiteralPath $archive)) { throw 'Archive owned receipts before cleanup.' }
    $reparseDirectories = Get-ChildItem -LiteralPath $CacheRoot -Directory -Recurse -Force | Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 }
    if ($reparseDirectories) { throw 'Owned cleanup contains reparse directories; stop for path inspection.' }
    $live = & docker ps --filter "label=tgengin.minif2f-owned=$RunId" --format '{{.ID}}'
    if ($LASTEXITCODE -ne 0 -or $live) { throw 'Do not remove an owned root while its container is running or state is unknown.' }
    Assert-ExactRoot
    Remove-Item -LiteralPath $CacheRoot -Recurse -Force
    [ordered]@{ cleanedExactOwnedRoot=$CacheRoot; receiptsArchived=$true } | ConvertTo-Json
}
