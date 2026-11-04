param([string]$RunDirectory)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
if (-not $RunDirectory) { $RunDirectory = (Get-Content -LiteralPath (Join-Path $projectRoot 'data/conway99-search/latest-run.txt') -Raw).Trim() }
$RunDirectory = (Resolve-Path -LiteralPath $RunDirectory).Path
if (Test-Path -LiteralPath (Join-Path $RunDirectory 'early-stop-request.json')) { throw 'User authorized early closeout. Search must not be restarted; final verification only.' }
$deadlinePath = Join-Path $RunDirectory 'deadline.json'
if (Test-Path -LiteralPath $deadlinePath) {
    $deadlineInfo = Get-Content -LiteralPath $deadlinePath -Raw | ConvertFrom-Json
    if ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() -ge $deadlineInfo.deadline_epoch) { throw 'Original campaign deadline has passed; refusing to restart.' }
}
$processPath=Join-Path $RunDirectory 'process.json'
if(Test-Path -LiteralPath $processPath){
    $priorProcess=Get-Content -LiteralPath $processPath -Raw | ConvertFrom-Json
    $running=Get-Process -Id $priorProcess.runner.pid -ErrorAction SilentlyContinue
    if($running){
        $created=([DateTimeOffset]$running.StartTime.ToUniversalTime()).ToUnixTimeMilliseconds()/1000
        if([Math]::Abs($created-$priorProcess.runner.created) -lt 1){throw 'This run already has a live controller.'}
    }
}
$bunCommand = (& bun -e 'console.log(process.execPath)').Trim()
if (-not (Test-Path -LiteralPath $bunCommand)) {throw 'Bun executable could not be resolved.'}
$stamp=[DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ')
foreach($name in @('run.ts','monitor.py')){Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $RunDirectory $name) -Force}
$runnerPath=Join-Path $PSScriptRoot './run.ts'
$envPath=Join-Path $projectRoot '.env'
$arguments=@(('"--env-file='+$envPath+'"'),('"'+$runnerPath+'"'),('"'+$RunDirectory+'"'))
$process=Start-Process -FilePath $bunCommand -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $RunDirectory "controller-$stamp.stdout.log") -RedirectStandardError (Join-Path $RunDirectory "controller-$stamp.stderr.log") -PassThru
[pscustomobject]@{pid=$process.Id;run=$RunDirectory;launched_utc=[DateTimeOffset]::UtcNow.ToString('o')} | ConvertTo-Json -Compress
