param([switch]$GraderOnly)
$ErrorActionPreference='Stop'
$hbRoot='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$hbHome=Join-Path $hbRoot 'docs/evalplus-20261012/humaneval/binary-v1'
$hbOut=Join-Path $hbHome 'full'
$hbBun='C:\Users\y1252\AppData\Roaming\npm\node_modules\bun\bin\bun.exe'
New-Item -ItemType Directory -Force -Path $hbOut,(Join-Path $hbHome 'grader') | Out-Null
$hbPins=Get-Content -LiteralPath (Join-Path $hbHome 'source-pins.json') -Raw | ConvertFrom-Json
foreach($hbRow in $hbPins.files){if((Get-FileHash -LiteralPath $hbRow.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hbRow.sha256){throw "Binary source changed: $($hbRow.path)"}}
$hbLive=Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'bun.exe' -and $_.CommandLine -match 'run-humaneval-binary\.ts["\s]+full'}
if($hbLive){$hbLive | Select-Object ProcessId,CreationDate,CommandLine | ConvertTo-Json; return}
$hbReady=$false
try{$hbHealth=Invoke-RestMethod http://127.0.0.1:17963/health -TimeoutSec 2;$hbReady=$hbHealth.dataset -eq 'humaneval' -and $hbHealth.executor -like '*venv*'}catch{}
if(-not $hbReady){
 $hbListener=Get-NetTCPConnection -LocalPort 17963 -State Listen -ErrorAction SilentlyContinue
 if($hbListener){throw 'Port 17963 occupied by an unexpected service'}
 $hbProc=Start-Process -FilePath 'C:\Windows\System32\wsl.exe' -ArgumentList @('-d','Ubuntu','-u','root','--exec','/bin/sh','/mnt/f/git/TgEngin-handoff-2026-10-07/TgEngin/scripts/evalplus-20261012/start-humaneval-binary-grader.sh') -WorkingDirectory $hbRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$hbHome/grader/stdout.log" -RedirectStandardError "$hbHome/grader/stderr.log"
 @{pid=$hbProc.Id;createdUtc=[DateTime]::UtcNow.ToString('o');port=17963;dataset='humaneval';dockerForbidden=$true}|ConvertTo-Json|Set-Content -LiteralPath "$hbHome/grader/launch.json" -Encoding utf8
 for($hbI=0;$hbI -lt 30;$hbI++){try{$hbHealth=Invoke-RestMethod http://127.0.0.1:17963/health -TimeoutSec 2;$hbReady=$hbHealth.ok -and $hbHealth.dataset -eq 'humaneval';if($hbReady){break}}catch{};Start-Sleep -Seconds 1}
 if(-not $hbReady){throw "Dedicated HumanEval grader failed; inspect $hbHome/grader/stderr.log"}
}
if($GraderOnly){$hbHealth|ConvertTo-Json;return}
& $hbBun run scripts/evalplus-20261012/run-humaneval-binary.ts preflight
if($LASTEXITCODE -ne 0){throw 'Binary preflight failed'}
$hbLock=Join-Path $hbOut 'runner-lock.json'
if(Test-Path -LiteralPath $hbLock){
 $hbOld=Get-Content -LiteralPath $hbLock -Raw|ConvertFrom-Json
 $hbOwner=Get-CimInstance Win32_Process -Filter "ProcessId=$($hbOld.pid)"
 if($hbOwner -and $hbOwner.Name -eq 'bun.exe' -and $hbOwner.CommandLine -like '*run-humaneval-binary.ts*'){throw 'Binary runner is already live'}
 Move-Item -LiteralPath $hbLock -Destination ($hbLock+'.closed-'+(Get-Date -Format yyyyMMddTHHmmssfff))
}
$hbStamp=Get-Date -Format yyyyMMddTHHmmssfff
$hbProc=Start-Process -FilePath $hbBun -ArgumentList @('run','scripts/evalplus-20261012/run-humaneval-binary.ts','full') -WorkingDirectory $hbRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$hbOut/stdout-$hbStamp.log" -RedirectStandardError "$hbOut/stderr-$hbStamp.log"
@{pid=$hbProc.Id;createdUtc=[DateTime]::UtcNow.ToString('o');command='run-humaneval-binary.ts full';stdout="$hbOut/stdout-$hbStamp.log";stderr="$hbOut/stderr-$hbStamp.log";dockerForbidden=$true}|ConvertTo-Json|Set-Content -LiteralPath "$hbOut/launch.json" -Encoding utf8
Get-Content -LiteralPath "$hbOut/launch.json" -Raw
