$ErrorActionPreference='Stop'
$chemRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../../..')).Path
$chemOut=Join-Path $chemRoot 'docs/repair-2026-10-10/full-f-rerun/chembench'
$chemControl=Get-Content -LiteralPath (Join-Path $chemRoot 'docs/repair-2026-10-10/full-f-rerun/control.json') -Raw -Encoding UTF8|ConvertFrom-Json
if(-not $chemControl.paidReady){throw 'Shared paid broker is not ready'}
$chemReceipt=Join-Path $chemOut 'runner-process.json'
if(Test-Path -LiteralPath $chemReceipt){
  $chemOld=Get-Content -LiteralPath $chemReceipt -Raw -Encoding UTF8|ConvertFrom-Json
  $chemExisting=Get-CimInstance Win32_Process -Filter "ProcessId=$($chemOld.pid)"
  if($chemExisting -and $chemExisting.CommandLine -like '*chembench*run.ts*'){throw 'Recorded runner remains alive; do not launch duplicate work'}
}
Invoke-RestMethod 'http://127.0.0.1:17906/health' -TimeoutSec 10|Out-Null
$chemBun=(& bun -e 'console.log(process.execPath)').Trim()
$chemStamp=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$chemProc=Start-Process -FilePath $chemBun -ArgumentList @((Join-Path $PSScriptRoot 'run.ts')) -WorkingDirectory $chemRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $chemOut "runner-$chemStamp.stdout.log") -RedirectStandardError (Join-Path $chemOut "runner-$chemStamp.stderr.log") -PassThru
@{pid=$chemProc.Id;startedAtUtc=[DateTime]::UtcNow.ToString('o');entry=(Join-Path $PSScriptRoot 'run.ts');hidden=$true;stdout=(Join-Path $chemOut "runner-$chemStamp.stdout.log");stderr=(Join-Path $chemOut "runner-$chemStamp.stderr.log")}|ConvertTo-Json|Set-Content -LiteralPath $chemReceipt
