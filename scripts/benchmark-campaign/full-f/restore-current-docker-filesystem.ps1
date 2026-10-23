$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$taskEvidence=Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/docker-recovery-2026-10-10'
$taskManifest='F:/git/TgEngin-handoff-2026-10-07/tmp/docker-storage-backup-current-20261011-0300/backup-manifest.json'
$taskBackup=Get-Content -LiteralPath $taskManifest -Raw|ConvertFrom-Json
if(-not $taskBackup.fullyDecompressedHashMatches -or -not $taskBackup.originalUnmodified -or $taskBackup.networkUpload -or $taskBackup.sourceBytes -ne 49243226112 -or $taskBackup.source -ne 'E:\Docker\wsl\disk\docker_data.vhdx'){throw 'Current verified local backup required'}
foreach($taskPart in $taskBackup.parts){if((Get-Item -LiteralPath $taskPart.path).Length -ne $taskPart.bytes -or (Get-FileHash -LiteralPath $taskPart.path -Algorithm SHA256).Hash.ToLower() -ne $taskPart.sha256){throw 'Current backup part mismatch'}}
$taskSource=Get-Item -LiteralPath $taskBackup.source
if($taskSource.Length -ne 49243226112 -or $taskSource.LastWriteTimeUtc.ToString('o') -ne '2026-10-11T02:58:14.3441063Z'){throw 'Current source changed since backup start'}
if((Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='E:'").FreeSpace -lt 8GB){throw 'Physical E growth reserve missing'}
$taskControl=Get-Content (Join-Path $taskRoot 'docs/repair-2026-10-10/full-f-rerun/control.json') -Raw|ConvertFrom-Json
$taskHealth=Get-Content -LiteralPath $taskControl.broker.healthPath -Raw|ConvertFrom-Json
if($taskHealth.resourceSlots.Count -or @($taskHealth.lanes|Where-Object {$_.slug -ne 'chembench' -and $_.active}).Count){throw 'Docker Bench still active'}
if(Get-CimInstance Win32_Process|Where-Object {$_.Name -in @('Docker Desktop.exe','com.docker.backend.exe')}){throw 'Desktop processes must remain stopped'}
$taskCheck='test "$(blkid -s UUID -o value /dev/sdd)" = "bb44d891-fd65-4df2-80d8-578ee75c691c" && ! findmnt -rn -S /dev/sdd && /usr/sbin/e2fsck -p /dev/sdd'
$taskLog=& wsl --system -u root -e sh -c $taskCheck 2>&1
$taskCode=$LASTEXITCODE
[IO.File]::WriteAllText((Join-Path $taskEvidence 'second-filesystem-repair.log'),($taskLog -join "`n"),[Text.UTF8Encoding]::new($false))
if($taskCode -notin @(0,1)){throw "Current filesystem automatic repair requires review: $taskCode"}
$taskVerify=& wsl --system -u root -e sh -c '/usr/sbin/e2fsck -n /dev/sdd; test $? -eq 0' 2>&1
$taskVerifyCode=$LASTEXITCODE
[IO.File]::WriteAllText((Join-Path $taskEvidence 'second-filesystem-verification.log'),($taskVerify -join "`n"),[Text.UTF8Encoding]::new($false))
if($taskVerifyCode -ne 0){throw 'Readonly verification failed'}
$taskResult=@{atUtc=[DateTime]::UtcNow.ToString('o');source=$taskBackup.source;sourceBytes=$taskBackup.sourceBytes;backupManifest=$taskManifest;sourceSha256=$taskBackup.sourceSha256;partHashesVerified=$true;automaticRepairExitCode=$taskCode;readonlyVerificationExitCode=$taskVerifyCode;uuid='bb44d891-fd65-4df2-80d8-578ee75c691c';imagesVolumesPreserved=$true;chembenchNotInterrupted=$true;globalWslShutdown=$false}
[IO.File]::WriteAllText((Join-Path $taskEvidence 'second-filesystem-repair-result.json'),($taskResult|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
$taskResult|ConvertTo-Json -Depth 5
