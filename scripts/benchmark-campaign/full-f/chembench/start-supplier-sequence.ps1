$ErrorActionPreference='Stop'
$seqRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../../..')).Path
$seqOut=Join-Path $seqRoot 'docs/repair-2026-10-10/full-f-rerun/chembench'
$a=Get-Content (Join-Path $seqOut 'supplier-sequence-authorization.json') -Raw|ConvertFrom-Json
if(!$a.armed -or !$a.rootReady){throw 'Root must explicitly ready/arm supplier sequence'}
$receipt=Join-Path $seqOut 'supplier-sequence-process.json'
if(Test-Path $receipt){$r=Get-Content $receipt -Raw|ConvertFrom-Json;$p=Get-CimInstance Win32_Process -Filter "ProcessId=$($r.pid)";if($p -and $p.CommandLine.Contains($r.entry) -and [Math]::Abs(($p.CreationDate.ToUniversalTime()-[DateTime]::Parse($r.startedAtUtc).ToUniversalTime()).TotalSeconds) -lt 10){throw 'Sequence already alive'}}
$stamp=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$p=Start-Process powershell.exe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'supplier-sequence.ps1')) -WorkingDirectory $seqRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $seqOut "supplier-sequence-$stamp.stdout.log") -RedirectStandardError (Join-Path $seqOut "supplier-sequence-$stamp.stderr.log") -PassThru
@{pid=$p.Id;atUtc=[DateTime]::UtcNow.ToString('o');hidden=$true}|ConvertTo-Json|Set-Content (Join-Path $seqOut 'supplier-sequence-launch.json') -Encoding UTF8
