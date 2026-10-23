[CmdletBinding()]
param(
    [ValidateSet('Gate', 'Workspace', 'UnpackAndProbe', 'PrepareCandidates', 'RegradeCandidates', 'Finish')]
    [string]$Stage = 'Gate'
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$CacheRoot = 'E:\objrun-experiment-cache\01a119ed-fdf7-7c32-b323-de9bab1290b6\minif2f-v415'
$RunId = '01a119ed-fdf7-7c32-b323-de9bab1290b6'
$ImageId = 'sha256:adccbc2412fe240d3bba28a81e136d2e816a28b003263a2f1738098a67cbfbba'
$PublicRoot = Join-Path $ProjectRoot '.phase1-data\minif2f-restoration-public'
$ProfilePath = Join-Path $ProjectRoot 'docs\repair-2026-10-08\minif2f-restoration-preflight.json'
$Profile = Get-Content -LiteralPath $ProfilePath -Raw | ConvertFrom-Json
$Python = Join-Path $ProjectRoot '.phase1-data\venv\Scripts\python.exe'
$Core = Join-Path $PSScriptRoot 'minif2f_restore.py'
$Runtime = Join-Path $PSScriptRoot 'minif2f_runtime.py'
$Legacy = Join-Path $PSScriptRoot 'minif2f_legacy_regrade.py'
$Stand = Join-Path $ProjectRoot 'examples\benchmark\minif2f\stand.py'

function Frozen-Sha([string]$Path) {
    $entry = @($Profile.reviewed_plan_files) + @($Profile.adapter_files) | Where-Object path -eq $Path
    if (@($entry).Count -ne 1) { throw 'File is not uniquely present in the reviewed plan.' }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.sha256) { throw 'Reviewed source bytes changed.' }
    return $actual
}

function Reserves {
    if ((Get-PSDrive E).Free -lt 3GB -or (Get-PSDrive F).Free -lt 1GB) { throw 'Required E/F free-space reserve violated.' }
}

function Owned {
    $expected = 'E:\objrun-experiment-cache\01a119ed-fdf7-7c32-b323-de9bab1290b6\minif2f-v415'
    if ([IO.Path]::GetFullPath($CacheRoot).TrimEnd('\') -cne $expected) { throw 'Unexpected owned root path.' }
    $current = $CacheRoot
    while ($current -and $current -ne 'E:\') {
        if (Test-Path -LiteralPath $current) {
            if (((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Owned root has a reparse ancestor.' }
        }
        $current = Split-Path -Parent $current
    }
    $marker = Get-Content -LiteralPath (Join-Path $CacheRoot 'owned-root.json') -Raw | ConvertFrom-Json
    if ($marker.run_id -ne $RunId -or $marker.host_root -ne $CacheRoot.Replace('\','/')) { throw 'Owned root marker differs.' }
}

function Run-Container([string]$RuntimeStage, [bool]$PrivateCandidates) {
    Owned
    Reserves
    $actualImage = & docker image inspect $ImageId --format '{{.Id}}'
    if ($LASTEXITCODE -ne 0 -or $actualImage.Trim() -ne $ImageId) { throw 'Fixed cached image unavailable.' }
    $name = 'minif2f-' + $RuntimeStage + '-' + $RunId.Substring(0,8)
    $audit = Join-Path $CacheRoot 'audit'
    $cacheMount = "type=bind,source=$CacheRoot,target=/cache"
    if ($PrivateCandidates) { $cacheMount += ',readonly' }
    $argsDocker = @('create', '--name', $name, '--pull', 'never', '--network', 'none', '--read-only',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--cpus', '2', '--memory', '12g',
        '--memory-swap', '12g', '--pids-limit', '128', '--log-driver', 'none', '--shm-size', '16m',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=117440512,mode=1777',
        '--label', "tgengin.minif2f-owned=$RunId", '--env', 'PYTHONDONTWRITEBYTECODE=1',
        '--mount', $cacheMount,
        '--mount', "type=bind,source=$Runtime,target=/plan/minif2f_runtime.py,readonly",
        '--mount', "type=bind,source=$Core,target=/plan/minif2f_restore.py,readonly",
        '--mount', "type=bind,source=$Stand,target=/plan/stand.py,readonly")
    if ($PrivateCandidates) {
        $bundleReceipt = Get-Content -LiteralPath (Join-Path $ProjectRoot 'docs\repair-2026-10-08\minif2f-private-bundle-receipt.json') -Raw | ConvertFrom-Json
        $bundle = $bundleReceipt.path
        if ((Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant() -ne $bundleReceipt.sha256) { throw 'Frozen private bundle changed.' }
        $output = Join-Path $audit 'legacy-regrade-output'
        New-Item -ItemType Directory -Path $output -Force | Out-Null
        if (Test-Path -LiteralPath (Join-Path $output 'legacy-regrade-minif2f.json')) { throw 'Refuse rerunning an existing frozen three-candidate diagnosis.' }
        $argsDocker += @('--user', '65534:65534',
            '--mount', "type=bind,source=$Legacy,target=/plan/minif2f_legacy_regrade.py,readonly",
            '--mount', "type=bind,source=$bundle,target=/private/legacy-final-3.json,readonly",
            '--mount', "type=bind,source=$output,target=/out",
            '--entrypoint', 'python', $ImageId, '/plan/minif2f_legacy_regrade.py', 'worker', '--root', '/cache',
            '--bundle-sha', $bundleReceipt.sha256, '--runtime-sha', $RuntimeSha, '--stand-sha', $StandSha)
    } else {
        $argsDocker += @('--user', '0:0', '--mount', "type=bind,source=$PublicRoot,target=/public,readonly",
            '--entrypoint', 'python', $ImageId, '/plan/minif2f_runtime.py', $RuntimeStage, '--root', '/cache',
            '--lock-sha', $Profile.public_lock.sha256, '--core-sha', $CoreSha, '--stand-sha', $StandSha)
    }
    $containerId = (& docker @argsDocker).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $containerId) { throw 'Could not create owned runtime container.' }
    try {
        $inspection = & docker inspect --size $containerId
        if ($LASTEXITCODE -ne 0) { throw 'Could not inspect owned container.' }
        $object = ($inspection | ConvertFrom-Json)[0]
        if (-not $object.HostConfig.ReadonlyRootfs -or $object.HostConfig.NetworkMode -ne 'none' -or $object.SizeRw -gt 128MB) { throw 'Container restrictions differ.' }
        $inspection | Set-Content -LiteralPath (Join-Path $audit ($RuntimeStage + '-container.json')) -Encoding utf8
        $stdout = Join-Path $audit ($RuntimeStage + '-stdout.log')
        $stderr = Join-Path $audit ($RuntimeStage + '-stderr.log')
        $process = Start-Process -FilePath 'docker' -ArgumentList @('start','--attach',$containerId) -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $began = [DateTime]::UtcNow
        while (-not $process.HasExited) {
            Start-Sleep -Seconds 2
            Reserves
            $bytes = (Get-ChildItem -LiteralPath $CacheRoot -File -Recurse -Force | Measure-Object -Property Length -Sum).Sum
            if ($bytes -gt 14GB) { throw 'Owned root directory exceeds 14 GiB.' }
            if (([DateTime]::UtcNow-$began).TotalHours -gt 3) { throw 'Owned runtime stage exceeds three hours.' }
            $process.Refresh()
        }
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw "Runtime stage failed; preserved audit: $stderr" }
        Reserves
        Get-Content -LiteralPath $stdout -Tail 4
    } finally {
        & docker rm --force $containerId | Out-Null
    }
}

$CoreSha = Frozen-Sha $Core
$RuntimeSha = Frozen-Sha $Runtime
$LegacySha = Frozen-Sha $Legacy
$StandSha = Frozen-Sha $Stand
Frozen-Sha $PSCommandPath | Out-Null
$publicHash = (Get-FileHash -LiteralPath (Join-Path $PublicRoot 'public-lock.json') -Algorithm SHA256).Hash.ToLowerInvariant()
if ($publicHash -ne $Profile.public_lock.sha256) { throw 'Public material lock changed.' }
Reserves
if ($Stage -eq 'Gate') {
    [ordered]@{ protocol='reconstructed-path-workspace-v1'; coreSha=$CoreSha; runtimeSha=$RuntimeSha; legacySha=$LegacySha; standSha=$StandSha; candidateRun=$false; eWrite=$false } | ConvertTo-Json
} elseif ($Stage -eq 'Workspace') {
    Run-Container 'workspace' $false
} elseif ($Stage -eq 'UnpackAndProbe') {
    Run-Container 'unpack-probe' $false
} elseif ($Stage -eq 'PrepareCandidates') {
    & $Python -X utf8 $Legacy prepare --project $ProjectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Local fixed-candidate preparation failed.' }
} elseif ($Stage -eq 'RegradeCandidates') {
    Run-Container 'legacy-regrade' $true
} elseif ($Stage -eq 'Finish') {
    Owned
    & $Python -X utf8 $Legacy finish --project $ProjectRoot --root $CacheRoot
    if ($LASTEXITCODE -ne 0) { throw 'Local miniF2F regrade archive failed.' }
}
