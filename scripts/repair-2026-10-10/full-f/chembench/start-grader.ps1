$ErrorActionPreference='Stop'
$chemRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../../..')).Path
$chemOut=Join-Path $chemRoot 'docs/repair-2026-10-10/full-f-rerun/chembench'
$chemReceipt=Join-Path $chemOut 'grader-process.json'
if(Test-Path -LiteralPath $chemReceipt){
  $chemOld=Get-Content -LiteralPath $chemReceipt -Raw|ConvertFrom-Json
  if(Get-Process -Id $chemOld.pid -ErrorAction SilentlyContinue){throw 'Recorded grader is already running; inspect its health before restarting'}
}
$chemPython=Join-Path $PSScriptRoot 'runtime/Scripts/python.exe'
$chemProc=Start-Process -FilePath $chemPython -ArgumentList @('-B',(Join-Path $PSScriptRoot 'grader.py'),'--port','17906','--level','1') -WorkingDirectory $chemRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $chemOut 'grader.stdout.log') -RedirectStandardError (Join-Path $chemOut 'grader.stderr.log') -PassThru
@{pid=$chemProc.Id;startedAtUtc=[DateTime]::UtcNow.ToString('o');port=17906;python=$chemPython;entry=(Join-Path $PSScriptRoot 'grader.py');hidden=$true}|ConvertTo-Json|Set-Content -LiteralPath $chemReceipt
