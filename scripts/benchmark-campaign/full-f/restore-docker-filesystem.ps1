$ErrorActionPreference='Stop'
$cbRecoveryRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$cbEvidence=Join-Path $cbRecoveryRoot 'docs/repair-2026-10-10/full-f-rerun/docker-recovery-2026-10-10'
$cbManifestPath='F:/git/TgEngin-handoff-2026-10-07/tmp/docker-storage-backup-zstd-20261011/backup-manifest.json'
$cbBackup=Get-Content -LiteralPath $cbManifestPath -Raw | ConvertFrom-Json
if(-not $cbBackup.fullyDecompressedHashMatches -or -not $cbBackup.originalUnmodified -or $cbBackup.networkUpload -or $cbBackup.sourceBytes -ne 36593205248 -or $cbBackup.source -ne 'E:\Docker\wsl\disk\docker_data.vhdx'){throw 'Verified local backup precondition failed'}
foreach($cbPart in $cbBackup.parts){
 if((Get-Item -LiteralPath $cbPart.path).Length -ne $cbPart.bytes -or (Get-FileHash -LiteralPath $cbPart.path -Algorithm SHA256).Hash.ToLower() -ne $cbPart.sha256){throw 'Backup part mismatch'}
}
$cbOriginal=Get-Item -LiteralPath $cbBackup.source
if($cbOriginal.Length -ne $cbBackup.sourceBytes -or $cbOriginal.LastWriteTimeUtc.ToString('o') -ne '2026-10-10T19:52:02.7820592Z'){throw 'Original changed after verified backup'}
$cbControl=Get-Content (Join-Path $cbRecoveryRoot 'docs/repair-2026-10-10/full-f-rerun/control.json') -Raw | ConvertFrom-Json
$cbHealth=Get-Content -LiteralPath $cbControl.broker.healthPath -Raw | ConvertFrom-Json
if($cbHealth.resourceSlots.Count -or ($cbHealth.lanes | Where-Object {$_.slug -ne 'chembench' -and $_.active})){throw 'Other Bench container/request still active'}
$cbExpected=@{
 38328='2026-10-10T19:45:57.6064730Z';38920='2026-10-10T19:45:57.6747330Z';105684='2026-10-10T19:45:58.0810570Z';27388='2026-10-10T19:45:59.2029210Z';137328='2026-10-10T19:45:59.6583960Z';135456='2026-10-10T19:45:59.6741990Z';140232='2026-10-10T19:46:00.8540120Z'
}
$cbOwned=@()
$cbAllDocker=Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'Docker Desktop.exe' -or $_.Name -eq 'com.docker.backend.exe'}
if($cbAllDocker | Where-Object {-not $cbExpected.ContainsKey([int]$_.ProcessId)}){throw 'Unexpected Docker process needs independent identity review'}
foreach($cbPid in $cbExpected.Keys){
 $cbProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$cbPid"
 if(-not $cbProcess){continue}
 if($cbProcess.CreationDate.ToUniversalTime().ToString('o') -ne $cbExpected[$cbPid] -or $cbProcess.ExecutablePath -notin @('D:\Program\Docker Desktop.exe','D:\Program\frontend\Docker Desktop.exe','D:\Program\resources\com.docker.backend.exe')){throw 'Docker PID identity differs'}
 $cbOwned+=$cbProcess
}
$cbPreflight=@{atUtc=[DateTime]::UtcNow.ToString('o');backupFullyVerified=$true;source=$cbBackup.source;sourceSha256=$cbBackup.sourceSha256;backupManifest=$cbManifestPath;dockerPids=$cbOwned.ProcessId;chemBenchIndependentRequestsAllowed=$true;otherHeavyResources=0}
[IO.File]::WriteAllText((Join-Path $cbEvidence 'filesystem-repair-preflight.json'),($cbPreflight|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
foreach($cbProcess in $cbOwned){Stop-Process -Id $cbProcess.ProcessId -ErrorAction SilentlyContinue}
$cbLinuxCheck='test "$(blkid -s UUID -o value /dev/sdd)" = "bb44d891-fd65-4df2-80d8-578ee75c691c" && ! findmnt -rn -S /dev/sdd && /usr/sbin/e2fsck -p /dev/sdd'
$cbOutput=& wsl --system -u root -e sh -c $cbLinuxCheck 2>&1
$cbCode=$LASTEXITCODE
[IO.File]::WriteAllText((Join-Path $cbEvidence 'filesystem-repair.log'),($cbOutput -join "`n"),[Text.UTF8Encoding]::new($false))
if($cbCode -notin @(0,1)){throw "Automatic filesystem repair requires further review: $cbCode"}
$cbVerify=& wsl --system -u root -e sh -c '/usr/sbin/e2fsck -n /dev/sdd; test $? -eq 0' 2>&1
$cbVerifyCode=$LASTEXITCODE
[IO.File]::WriteAllText((Join-Path $cbEvidence 'filesystem-repair-verification.log'),($cbVerify -join "`n"),[Text.UTF8Encoding]::new($false))
if($cbVerifyCode -ne 0){throw 'Repaired filesystem still fails readonly verification'}
$cbResult=@{atUtc=[DateTime]::UtcNow.ToString('o');automaticRepairExitCode=$cbCode;readonlyVerificationExitCode=$cbVerifyCode;uuid='bb44d891-fd65-4df2-80d8-578ee75c691c';source=$cbBackup.source;backupPreserved=$true;imagesAndVolumesNotDeleted=$true;chemBenchNotInterrupted=$true}
[IO.File]::WriteAllText((Join-Path $cbEvidence 'filesystem-repair-result.json'),($cbResult|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
$cbResult|ConvertTo-Json -Depth 5
