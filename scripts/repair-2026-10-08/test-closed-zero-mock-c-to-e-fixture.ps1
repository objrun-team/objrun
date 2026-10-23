[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$taskProject='F:\git\TgEngin-handoff-2026-10-07\TgEngin'
$taskSource=Join-Path $taskProject 'scripts\repair-2026-10-08\relocate-closed-zero-llm-mocks-to-e.ps1'
$taskFixture=Join-Path $taskProject '.phase1-data\cold-relocation-fixture-01a119ed'
$taskReport=Join-Path $taskProject 'docs\repair-2026-10-08\closed-zero-mock-c-to-e-fixtures.json'
$taskTokens=$null;$taskErrors=$null
$taskAst=[Management.Automation.Language.Parser]::ParseFile($taskSource,[ref]$taskTokens,[ref]$taskErrors)
if(@($taskErrors).Count){throw 'Production PowerShell syntax failed.'}
# Load only reviewed pure file/path helpers. Do not execute its top-level DryRun/Apply.
$taskHelpers=@('Canonical','Contained','Ordinary-Ancestors','Junction-Target','Sha','Relative-Path','Inventory','Match-Files','Alias-Hashes','Save-Json')
foreach($function in $taskAst.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){
    if($function.Name -in $taskHelpers){Invoke-Expression $function.Extent.Text}
}
if(Test-Path -LiteralPath $taskFixture){throw 'Existing fixture must be reviewed, never overwritten.'}
Contained $taskFixture $taskProject|Out-Null
Ordinary-Ancestors (Split-Path -Parent $taskFixture)
$taskChecks=[Collections.Generic.List[object]]::new()
function Check([string]$Name,[bool]$Condition) {
    if(-not $Condition){throw ('Fixture failed: '+$Name)}
    $taskChecks.Add([ordered]@{case=$Name;passed=$true})
}
function Reject([string]$Name,[scriptblock]$Action) {
    $rejected=$false
    try {& $Action|Out-Null} catch {$rejected=$true}
    Check $Name $rejected
}
$taskPhysical=Join-Path $taskFixture 'physical'
$taskAlias=Join-Path $taskFixture 'original-alias'
$taskTarget=Join-Path $taskFixture 'target'
$taskBackup=Join-Path $taskFixture 'exact-backup'
$taskStage=Join-Path $taskFixture 'staged-junction'
$taskOther=Join-Path $taskFixture 'other'
$taskJunctions=@()
$taskSucceeded=$false
$taskPayloadBytes=[long]0
try {
    New-Item -ItemType Directory -Path $taskFixture|Out-Null
    foreach($path in @($taskPhysical,$taskTarget,$taskOther,(Join-Path $taskPhysical 'empty'),(Join-Path $taskPhysical 'sub'))){
        New-Item -ItemType Directory -Path $path|Out-Null
    }
    [IO.File]::WriteAllBytes((Join-Path $taskPhysical 'a.bin'),[byte[]](0..255))
    [IO.File]::WriteAllText((Join-Path $taskPhysical 'sub\b.txt'),'closed native fixture',[Text.UTF8Encoding]::new($false))
    $before=Inventory $taskPhysical
    $taskPayloadBytes=$before.bytes
    foreach($relative in $before.directories){New-Item -ItemType Directory -Path (Contained (Join-Path $taskTarget $relative) $taskTarget)|Out-Null}
    foreach($file in $before.files){
        $input=[IO.File]::Open((Join-Path $taskPhysical $file.relative),[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
        $output=$null
        try {
            $output=[IO.File]::Open((Join-Path $taskTarget $file.relative),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
            $input.CopyTo($output);$output.Flush($true)
        } finally {if($output){$output.Dispose()};$input.Dispose()}
    }
    Match-Files $before.files (Inventory $taskTarget).files
    Check 'native-copy-full-sha-readback-and-flush-returned' $true
    New-Item -ItemType Junction -Path $taskAlias -Target $taskPhysical|Out-Null
    $taskJunctions += $taskAlias
    Junction-Target $taskAlias $taskPhysical|Out-Null
    Alias-Hashes $taskAlias $before.files
    Check 'original-junction-full-sha-readback' $true
    Reject 'sibling-prefix-containment-rejected' {Contained ($taskFixture+'-outside\file') $taskFixture}
    Reject 'dotdot-escape-containment-rejected' {Contained (Join-Path $taskFixture '..\escape') $taskFixture}
    Reject 'wrong-junction-target-rejected' {Junction-Target $taskAlias $taskTarget}
    Reject 'junction-ancestor-rejected' {Ordinary-Ancestors (Join-Path $taskAlias 'sub')}
    $bad=@($before.files|ForEach-Object {[pscustomobject]@{relative=$_.relative;bytes=$_.bytes;sha256=$_.sha256}})
    $bad[0].sha256='0'*64
    Reject 'wrong-frozen-file-sha-rejected' {Match-Files $bad (Inventory $taskTarget).files}
    Match-Files $before.files (Inventory $taskPhysical).files
    Match-Files $before.files (Inventory $taskTarget).files
    Check 'source-and-copy-retained-after-verification-failure' $true
    $taskInnerLink=Join-Path $taskTarget 'unexpected-link'
    New-Item -ItemType Junction -Path $taskInnerLink -Target $taskOther|Out-Null
    $taskJunctions += $taskInnerLink
    Reject 'unmanifested-interior-reparse-point-rejected' {Inventory $taskTarget}
    [IO.Directory]::Delete((Contained $taskInnerLink $taskFixture))
    New-Item -ItemType Junction -Path $taskStage -Target $taskTarget|Out-Null
    $taskJunctions += $taskStage
    Junction-Target $taskStage $taskTarget|Out-Null
    Move-Item -LiteralPath $taskPhysical -Destination $taskBackup
    Move-Item -LiteralPath $taskStage -Destination $taskPhysical
    $taskJunctions += $taskPhysical
    Junction-Target $taskPhysical $taskTarget|Out-Null
    Junction-Target $taskAlias $taskPhysical|Out-Null
    Alias-Hashes $taskAlias $before.files
    Match-Files $before.files (Inventory $taskBackup).files
    Check 'native-directory-rename-junction-rename-original-two-hop-chain' $true
    $exact=Contained $taskBackup $taskFixture
    if($exact -cne (Canonical (Join-Path $taskFixture 'exact-backup'))){throw 'Fixture recursive removal escaped exact named backup.'}
    Ordinary-Ancestors $exact
    Match-Files $before.files (Inventory $exact).files
    Remove-Item -LiteralPath $exact -Recurse -Force
    Match-Files $before.files (Inventory $taskTarget).files
    Alias-Hashes $taskAlias $before.files
    Check 'exact-ordinary-backup-removal-retains-target-and-two-hop-alias' $true
    $taskSucceeded=$true
} finally {
    # Remove only known F-only junction entries nonrecursively, then the ordinary fixture.
    foreach($link in $taskJunctions|Select-Object -Unique) {
        $exact=Contained $link $taskFixture
        $item=Get-Item -LiteralPath $exact -Force -ErrorAction SilentlyContinue
        if($null -ne $item) {
            if($item.LinkType -ne 'Junction'){throw 'Fixture link cleanup encountered unknown object.'}
            [IO.Directory]::Delete($exact)
        }
    }
    if(Test-Path -LiteralPath $taskFixture) {
        $exact=Contained $taskFixture $taskProject
        if($exact -cne (Canonical (Join-Path $taskProject '.phase1-data\cold-relocation-fixture-01a119ed'))){throw 'Fixture root removal escaped exact owned target.'}
        Ordinary-Ancestors $exact
        Inventory $exact|Out-Null
        Remove-Item -LiteralPath $exact -Recurse -Force
    }
    Save-Json $taskReport ([ordered]@{protocol='closed-zero-mock-c-to-e-native-fixtures-v1';createdAt=[DateTime]::UtcNow.ToString('o');validated=$taskSucceeded;productionSourceSha256=(Sha $taskSource);C_E_modified=$false;actualArchiveBytesUsed=$false;copiedPayloadBytes=$taskPayloadBytes;checks=$taskChecks.ToArray();fixtureRemoved=(-not (Test-Path -LiteralPath $taskFixture));purpose='actual native NTFS rename/junction behavior and production path/SHA guard rejection; no actual Apply'})
}
[ordered]@{validated=$taskSucceeded;cases=$taskChecks.Count;C_E_modified=$false;reportSha256=(Sha $taskReport)}|ConvertTo-Json
