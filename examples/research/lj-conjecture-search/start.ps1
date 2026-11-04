param([string]$RunDirectory)
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
if(-not $RunDirectory){$RunDirectory=(Get-Content -LiteralPath (Join-Path $projectRoot 'data/lj-conjecture-search/latest-run.txt') -Raw).Trim()}
$RunDirectory=(Resolve-Path -LiteralPath $RunDirectory).Path
if(Test-Path -LiteralPath (Join-Path $RunDirectory 'primary-success.json')){throw 'Already solved/closed; no restart'}
if(Test-Path -LiteralPath (Join-Path $RunDirectory 'deadline.json')){
  $clock=Get-Content -LiteralPath (Join-Path $RunDirectory 'deadline.json') -Raw | ConvertFrom-Json
  if([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() -ge $clock.deadline_epoch){throw 'Original deadline passed'}
}
$bunCommand=(& bun -e 'console.log(process.execPath)').Trim()
$pythonCommand=(& python -c 'import sys;print(sys.executable)').Trim()
foreach($name in @('run.ts','monitor.py','supervisor.py','linux_owned.py','finalize.py')){Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $RunDirectory $name)}
$argsList=@(('"'+(Join-Path $RunDirectory 'supervisor.py')+'"'),('"'+$RunDirectory+'"'),('"'+$projectRoot+'"'),('"'+$bunCommand+'"'))
$process=Start-Process -FilePath $pythonCommand -ArgumentList $argsList -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $RunDirectory 'supervisor.stdout.log') -RedirectStandardError (Join-Path $RunDirectory 'supervisor.stderr.log') -PassThru
[pscustomobject]@{supervisor_pid=$process.Id;run=$RunDirectory;launched_utc=[DateTimeOffset]::UtcNow.ToString('o')} | ConvertTo-Json -Compress
