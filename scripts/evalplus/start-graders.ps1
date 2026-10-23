$ErrorActionPreference = 'Stop'
$epRoot = 'F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$epLinux = '/mnt/f/git/TgEngin-handoff-2026-10-07/TgEngin'
$epOut = Join-Path $epRoot 'docs/evalplus-20261012'
# Strict rule: no Docker, Docker Desktop, Compose or fallback to containers.
& wsl -d Ubuntu -u root --exec /usr/bin/python3 -m venv /tmp/objrun-evalplus-20261012/venv
if ($LASTEXITCODE -ne 0) { throw 'Existing Ubuntu Python venv unavailable; Docker fallback forbidden.' }
foreach ($epSpec in @(@('humaneval',17961),@('mbpp',17962))) {
  $epDataset=$epSpec[0];$epPort=$epSpec[1];$epDir=Join-Path $epOut $epDataset
  New-Item -ItemType Directory -Force -Path "$epDir/grader","$epDir/oracle-cache" | Out-Null
  $epReady=$false
  try { $epHealth=Invoke-RestMethod "http://127.0.0.1:$epPort/health" -TimeoutSec 2;$epReady=$epHealth.dataset -eq $epDataset -and $epHealth.executor -like '*venv*' } catch {}
  if (-not $epReady) {
    $epProc=Start-Process -FilePath 'C:\Windows\System32\wsl.exe' -ArgumentList @('-d','Ubuntu','-u','root','--exec','/tmp/objrun-evalplus-20261012/venv/bin/python',"$epLinux/scripts/evalplus/grader_service.py",'--dataset',$epDataset,'--port',$epPort,'--output',"$epLinux/docs/evalplus-20261012/$epDataset/grader") -WorkingDirectory $epRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$epDir/grader/stdout.log" -RedirectStandardError "$epDir/grader/stderr.log"
    @{ pid=$epProc.Id; createdUtc=[DateTime]::UtcNow.ToString('o'); dataset=$epDataset; port=$epPort; executor='WSL Ubuntu Python3.12 venv'; dockerForbidden=$true } | ConvertTo-Json | Set-Content -LiteralPath "$epDir/grader/process.json" -Encoding utf8
  }
}
@{ executor='WSL Ubuntu Python3.12 venv'; dockerForbidden=$true; dependencies='Existing Linux numpy 1.26.4, psutil 6.1.1; minimal pure Python helpers'; atUtc=[DateTime]::UtcNow.ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath "$epOut/environment.json" -Encoding utf8
