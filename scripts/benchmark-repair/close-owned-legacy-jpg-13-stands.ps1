$ErrorActionPreference='Stop'
$taskRepo='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$taskDocs=Join-Path $taskRepo 'docs\repair-2026-10-08'
$taskDetails=Join-Path $taskDocs 'legacy-jpg-13-stand-process-details.json'
$taskInspection=Join-Path $taskDocs 'legacy-jpg-13-stand-process-inspection.json'
$taskReport=Join-Path $taskDocs 'legacy-jpg-13-stand-cleanup.json'
if(Test-Path -LiteralPath $taskReport){throw 'Keep the existing cleanup record'}
if((Get-FileHash -LiteralPath $taskDetails -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'eed9b68edb12e5ab8eba0e96eb195007384ac64f7c6d0d86028178a71c2b735a' -or
   (Get-FileHash -LiteralPath $taskInspection -Algorithm SHA256).Hash.ToLowerInvariant() -ne '28699477eba17eb77c5817e79069be82ca40bb66dd90412da7d2cb421e2f5dcd'){throw 'Reviewed root process identity evidence changed'}
$taskExpected=Get-Content -LiteralPath $taskDetails -Raw | ConvertFrom-Json -DateKind String
if(@($taskExpected).Count -ne 13){throw 'Exactly13 frozen identities required'}
$taskHandles=@()
$taskRows=@()
function Write-TaskEvidence {
    $taskEvidence=[ordered]@{observedAtUtc=[DateTime]::UtcNow.ToString('o');scope='Exactly13 project-owned abandoned JPG mock stands,12 Temp fixtures and one old10-29 zero-fee local mock';scriptSha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant();processDetailsSha256='eed9b68edb12e5ab8eba0e96eb195007384ac64f7c6d0d86028178a71c2b735a';closedProcesses=$taskRows;rawCommandOrCredentialPrinted=$false;parentProcessStopped=$false;latest1129StoreTouched=$false;activePaidOrScientificServiceStopped=$false;archivalFileBytesChanged=$false;fixtureAttribution='Exact mock mode and Temp tgengin-jpg-bridge launcher pattern;12 fixtures have no campaign ledgers, so no original campaign closure is fabricated';limitation='Earlier tests or run cleanup left these processes. This records later exact closure and does not rewrite earlier evidence.'}
    [IO.File]::WriteAllText($taskReport,(($taskEvidence|ConvertTo-Json -Depth 7)+[Environment]::NewLine),[Text.UTF8Encoding]::new($false))
}
# Verify every identity and hold its original process handle before stopping any.
try {
    foreach($taskWanted in $taskExpected){
        $taskProc=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskWanted.pid)"
        if(-not $taskProc){throw 'Expected process disappeared; inspect changed state'}
        $taskCommand=[string]$taskProc.CommandLine
        $taskCommandSha=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($taskCommand))).ToLowerInvariant()
        $taskHome=[regex]::Match($taskCommand,'--home\s+("[^"]+"|\S+)').Groups[1].Value.Trim('"')
        $taskMode=[regex]::Match($taskCommand,'--mode\s+(mock|live)').Groups[1].Value
        $taskPort=[regex]::Match($taskCommand,'--port\s+(\d+)').Groups[1].Value
        $taskFixture=$taskHome -cmatch '^C:\\Users\\y1252\\AppData\\Local\\Temp\\tgengin-jpg-bridge-[A-Za-z0-9]+$'
        $taskOldRun=$taskHome -ceq 'C:\Users\y1252\objrun-legacy-workspace\experiment-stores\skb-jpg-2026-10-08T10-29-51-522Z\stand'
        if($taskProc.CreationDate.ToUniversalTime().ToString('o') -cne $taskWanted.createdUtc -or
           $taskProc.ExecutablePath -cne 'D:\ProgramData\anaconda3\python.exe' -or
           $taskCommandSha -cne $taskWanted.commandSha256 -or
           -not $taskCommand.Contains((Join-Path $taskRepo 'scripts\benchmark-repair\skb-jpg-stand.py')) -or
           $taskMode -cne 'mock' -or $taskPort -cne $taskWanted.port -or
           $taskHome -cne $taskWanted.home -or (-not $taskFixture -and -not $taskOldRun)){throw 'Exact reviewed mock identity differs; nothing is stopped'}
        if(Get-CimInstance Win32_Process -Filter "ProcessId=$($taskProc.ParentProcessId)"){throw 'Old wrapper parent is now present; inspect it separately'}
        $taskHandle=Get-Process -Id $taskWanted.pid
        $taskNativeHandle=$taskHandle.Handle
        if($taskHandle.Path -cne $taskProc.ExecutablePath -or
           $taskHandle.StartTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fff') -cne $taskProc.CreationDate.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fff')){throw 'Original process handle differs'}
        $taskHandles+=$taskHandle
        $taskRows+=[ordered]@{pid=$taskWanted.pid;createdUtc=$taskWanted.createdUtc;mode=$taskMode;port=$taskPort;home=$taskHome;originalParentPid=$taskProc.ParentProcessId;parentAbsent=$true;handleIdentityChecked=$true;closed=$false}
    }
    Write-TaskEvidence
    for($taskIndex=0;$taskIndex -lt $taskHandles.Count;$taskIndex++){
        $taskHandle=$taskHandles[$taskIndex]
        Stop-Process -InputObject $taskHandle -Force
        if(-not $taskHandle.WaitForExit(10000)){throw 'The original exact process did not exit'}
        $taskAfter=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskRows[$taskIndex].pid)"
        if($taskAfter -and $taskAfter.CreationDate.ToUniversalTime().ToString('o') -ceq $taskRows[$taskIndex].createdUtc){throw 'Original process still present after close'}
        $taskRows[$taskIndex].closed=$true
        $taskRows[$taskIndex].closedAtUtc=[DateTime]::UtcNow.ToString('o')
        $taskRows[$taskIndex].pidReusedAfterClose=[bool]$taskAfter
        Write-TaskEvidence
    }
    [pscustomobject]@{exactProcessesClosed=$taskRows.Count;fixtureProcesses=12;localMockCampaignProcesses=1;modelCalls=0;report=$taskReport}|ConvertTo-Json -Compress
} finally {
    foreach($taskHandle in $taskHandles){$taskHandle.Dispose()}
}
