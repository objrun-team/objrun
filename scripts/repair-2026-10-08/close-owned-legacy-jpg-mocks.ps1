$ErrorActionPreference='Stop'
$taskRepo='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$taskReport=Join-Path $taskRepo 'docs\repair-2026-10-08\legacy-mock-stand-cleanup.json'
if(Test-Path -LiteralPath $taskReport){throw 'Preserve existing cleanup evidence'}
$taskExpected=@(
    @{Pid=84036;Created='2026-10-08T09:46:52.0518790Z';Run='skb-jpg-2026-10-08T09-46-44-144Z';Port=64362},
    @{Pid=45880;Created='2026-10-08T09:48:15.2902840Z';Run='skb-jpg-2026-10-08T09-48-07-694Z';Port=64628},
    @{Pid=4084;Created='2026-10-08T09:54:59.5329530Z';Run='skb-jpg-2026-10-08T09-54-51-769Z';Port=50344}
)
$taskRows=@()
foreach($taskWanted in $taskExpected){
    $taskProc=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskWanted.Pid)"
    if(-not $taskProc){throw 'Exact old process disappeared before cleanup; inspect rather than guess'}
    $taskCommand=[string]$taskProc.CommandLine
    if($taskProc.CreationDate.ToUniversalTime().ToString('o') -ne $taskWanted.Created -or
       $taskProc.ExecutablePath -ne 'D:\ProgramData\anaconda3\python.exe' -or
       -not $taskCommand.Contains($taskRepo) -or
       -not $taskCommand.Contains('skb-jpg-stand.py') -or
       -not $taskCommand.Contains($taskWanted.Run) -or
       $taskCommand -notmatch 'mock') {throw 'PID identity changed; no process is stopped'}
    $taskHandle=Get-Process -Id $taskWanted.Pid
    $taskNativeHandle=$taskHandle.Handle
    if($taskHandle.Path -ne $taskProc.ExecutablePath -or
       $taskHandle.StartTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fff') -ne
       $taskProc.CreationDate.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fff')){throw 'Process handle identity differs'}
    $taskParent=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskProc.ParentProcessId)"
    if($taskParent){throw 'Original wrapper parent is currently present; separately review it'}
    $taskRows+=[ordered]@{pid=$taskWanted.Pid;run=$taskWanted.Run;createdUtc=$taskWanted.Created;port=$taskWanted.Port;projectStandMatch=$true;mockFlagPresent=$true;originalParentPid=$taskProc.ParentProcessId;parentAbsent=$true;handleIdentityChecked=$true;closed=$false}
    # The verified original process object only. No process-name/global cleanup.
    Stop-Process -InputObject $taskHandle -Force
    if(-not $taskHandle.WaitForExit(10000)){throw 'Exact owned process did not exit'}
    $taskAfter=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskWanted.Pid)"
    if($taskAfter -and $taskAfter.CreationDate.ToUniversalTime().ToString('o') -eq $taskWanted.Created){throw 'Old process still exists'}
    $taskRows[-1].closed=$true
    $taskRows[-1].closedAtUtc=[DateTime]::UtcNow.ToString('o')
    $taskRows[-1].pidReusedAfterClose=[bool]$taskAfter
    $taskHandle.Dispose()
}
$taskEvidence=[ordered]@{observedAtUtc=[DateTime]::UtcNow.ToString('o');scope='Three exact project-owned old zero-LLM JPG mock stand processes';scriptSha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant();closedProcesses=$taskRows;rawCommandOrTokenPrinted=$false;parentProcessStopped=$false;activePaidOrScientificServiceStopped=$false;archiveBytesChanged=$false;limitation='Earlier closure certificates did not include these actually surviving stands. This records their later exact closure without rewriting that history.'}
[IO.File]::WriteAllText($taskReport,(($taskEvidence|ConvertTo-Json -Depth 6)+[Environment]::NewLine),[Text.UTF8Encoding]::new($false))
[pscustomobject]@{exactProcessesClosed=$taskRows.Count;archiveBytesChanged=$false;modelCalls=0;report=$taskReport}|ConvertTo-Json -Compress
