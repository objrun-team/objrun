$ErrorActionPreference='Stop'
$chemRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../../..')).Path
$chemOut=Join-Path $chemRoot 'docs/repair-2026-10-10/full-f-rerun/chembench'
$chemAuthorization=Get-Content (Join-Path $chemOut 'relace-last-authorization.json') -Raw -Encoding UTF8|ConvertFrom-Json
$chemControl=Get-Content (Join-Path $chemRoot 'docs/repair-2026-10-10/full-f-rerun/control.json') -Raw -Encoding UTF8|ConvertFrom-Json
if(-not $chemAuthorization.armed -or $chemAuthorization.index -ne 277 -or $chemAuthorization.providerSlug -ne 'relace' -or $chemAuthorization.brokerRunId -ne $chemControl.broker.runId){throw 'Relace single attempt requires explicit armed authorization for current shared broker'}
if(-not $chemControl.paidReady){throw 'Shared broker is not ready'}
$chemHold=Get-Content (Join-Path $chemOut 'upstream-timeout-hold.json') -Raw -Encoding UTF8|ConvertFrom-Json
if($chemHold.requested){throw 'Hold must be explicitly released for material Relace attempt'}
foreach($chemKind in @('runner','supervisor')){
 $chemReceipt=Join-Path $chemOut "$chemKind-process.json"
 if(Test-Path $chemReceipt){$chemOld=Get-Content $chemReceipt -Raw -Encoding UTF8|ConvertFrom-Json;$chemLive=Get-CimInstance Win32_Process -Filter "ProcessId=$($chemOld.pid)";if($chemLive -and $chemLive.CommandLine.Contains($chemOld.entry)){throw "Recorded $chemKind remains alive"}}
}
$chemHealth=Invoke-RestMethod ($chemControl.broker.endpoint+'/health') -TimeoutSec 10
if(-not $chemHealth.healthy -or $chemHealth.pid -ne $chemControl.broker.pid -or $chemHealth.runId -ne $chemAuthorization.brokerRunId){throw 'Shared broker identity/health mismatch'}
Invoke-RestMethod 'http://127.0.0.1:17906/health' -TimeoutSec 10|Out-Null
$chemEntry=Join-Path $PSScriptRoot 'relace-last.ts'
$chemBun=(& bun -e 'console.log(process.execPath)').Trim()
$chemStamp=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$chemProc=Start-Process $chemBun -ArgumentList @($chemEntry) -WorkingDirectory $chemRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $chemOut "relace-last-$chemStamp.stdout.log") -RedirectStandardError (Join-Path $chemOut "relace-last-$chemStamp.stderr.log") -PassThru
@{pid=$chemProc.Id;startedAtUtc=[DateTime]::UtcNow.ToString('o');entry=$chemEntry;hidden=$true;providerSlug='relace';index=277;oneSegmentOnly=$true;stdout=(Join-Path $chemOut "relace-last-$chemStamp.stdout.log");stderr=(Join-Path $chemOut "relace-last-$chemStamp.stderr.log")}|ConvertTo-Json|Set-Content (Join-Path $chemOut 'runner-process.json') -Encoding UTF8
