param(
  [ValidateSet('Inspect','Apply')][string]$Mode='Inspect',
  [Parameter(Mandatory=$true)][ValidatePattern('^repair-[0-9TZ-]+$')][string]$RunId,
  [int]$OwnedPid=0,
  [string]$OwnerNonce=''
)
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$ownerRoot='D:\objrun-experiment-stores\01a119ed-fdf7-7c32-b323-de9bab1290b6'
$physical=[IO.Path]::GetFullPath((Join-Path $ownerRoot ('scientific-journal-v2-'+$RunId)))
$logical=[IO.Path]::GetFullPath((Join-Path $projectRoot ('.phase1-data\repair\'+$RunId)))
$inspectOutput=Join-Path $projectRoot ('docs\repair-2026-10-08\storage-preparations\'+$RunId+'\plan.json')
$paidLock=Join-Path $projectRoot '.phase1-data\owned-paid-campaign.lock.json'
$leasePath=Join-Path $projectRoot ('.phase1-data\owned-scientific-storage-'+$RunId+'.lock.json')
$layoutPath=Join-Path $projectRoot ('docs\repair-2026-10-08\campaigns\'+$RunId+'\storage-layout.json')
$GiB=[int64]1073741824
$residual=[int64]536870912
function Inside([string]$parent,[string]$target){
  $p=[IO.Path]::GetFullPath($parent).TrimEnd('\')+'\'
  $t=[IO.Path]::GetFullPath($target)
  return $t.StartsWith($p,[StringComparison]::OrdinalIgnoreCase)
}
function OrdinaryAncestors([string]$target){
  $at=[IO.Path]::GetFullPath($target)
  while($at){
    if(Test-Path -LiteralPath $at){
      $item=Get-Item -LiteralPath $at -Force
      if(!$item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'ancestor_not_ordinary'}
    }
    $parent=[IO.Path]::GetDirectoryName($at)
    if(!$parent -or $parent -eq $at){break}
    $at=$parent
  }
}
function WriteSynced([string]$path,$value,[bool]$exclusive=$true){
  $parent=[IO.Path]::GetDirectoryName($path)
  if(!(Test-Path -LiteralPath $parent)){New-Item -ItemType Directory -Path $parent -ErrorAction Stop | Out-Null}
  $bytes=[Text.UTF8Encoding]::new($false).GetBytes((ConvertTo-Json -Depth 30 -InputObject $value)+"`n")
  $mode=[IO.FileMode]::Create
  if($exclusive){$mode=[IO.FileMode]::CreateNew}
  $stream=[IO.FileStream]::new($path,$mode,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try{$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
  if([Convert]::ToBase64String([IO.File]::ReadAllBytes($path)) -cne [Convert]::ToBase64String($bytes)){throw 'storage_receipt_readback'}
  return @{path=$path;bytes=$bytes.Length;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower();flushToDiskReturned=$true}
}
function FreshPaidOwner{
  $owned=Get-Content -LiteralPath $paidLock -Raw | ConvertFrom-Json
  if($OwnedPid -le 0 -or !$OwnerNonce -or $owned.pid -ne $OwnedPid -or $owned.runId -cne $RunId -or $owned.ownerNonce -cne $OwnerNonce -or $owned.mode -cne 'carry-science-oom-2026-10-08-v2' -or !("$($owned.entry)" -like '*scientific-journal-campaign.ts')){throw 'canonical_paid_owner_required'}
  $null=Get-Process -Id $OwnedPid -ErrorAction Stop
  return $owned
}
if(![IO.Path]::IsPathRooted($physical) -or !(Inside $ownerRoot $physical) -or !(Inside (Join-Path $projectRoot '.phase1-data\repair') $logical) -or !(Inside $projectRoot $inspectOutput) -or !(Inside $projectRoot $layoutPath)){throw 'fixed_absolute_containment'}
OrdinaryAncestors $ownerRoot
OrdinaryAncestors ([IO.Path]::GetDirectoryName($logical))
if((Test-Path -LiteralPath $physical) -or (Test-Path -LiteralPath $logical)){throw 'new_store_must_not_exist'}
$d=[IO.DriveInfo]::new('D:\');$f=[IO.DriveInfo]::new('F:\')
$observed=@{DfreeBytes=$d.AvailableFreeSpace;FfreeBytes=$f.AvailableFreeSpace;DrequiredBytes=4*$GiB+$residual;FrequiredBytes=$residual;observedAtUtc=[DateTime]::UtcNow.ToString('o')}
$ready=$observed.DfreeBytes -ge $observed.DrequiredBytes -and $observed.FfreeBytes -ge $observed.FrequiredBytes
$scriptPin=@{path=$PSCommandPath;sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLower();bytes=(Get-Item -LiteralPath $PSCommandPath).Length}
$plan=@{protocol='scientific-journal-store-plan-v2';runId=$RunId;mode=$Mode;allowedOwnerRoot=$ownerRoot;physicalStore=$physical;logicalStore=$logical;resourceEvidence=$observed;resourceSatisfied=$ready;scriptPin=$scriptPin;newStoreOnly=$true;oldStoresMoved=$false;outsideProjectWrites=$false;modelCalls=0}
if($Mode -eq 'Inspect'){
  $receipt=WriteSynced $inspectOutput $plan
  ConvertTo-Json -Depth 30 -Compress -InputObject @{prepared=$true;paidReady=$false;resourceSatisfied=$ready;plan=$receipt;outsideProjectWrites=$false;modelCalls=0}
  exit 0
}
if(!$ready){throw 'insufficient_storage_before_any_creation'}
$owned=FreshPaidOwner
$leasePin=WriteSynced $leasePath @{protocol='scientific-journal-storage-lease-v2';pid=$OwnedPid;runId=$RunId;physicalStore=$physical;logicalStore=$logical;createdAtUtc=[DateTime]::UtcNow.ToString('o');paidLockSha256=(Get-FileHash -LiteralPath $paidLock -Algorithm SHA256).Hash.ToLower()}
# No delete/move/prune/reclaim path exists. A failure retains all partial owned paths and lease.
try{
  $null=FreshPaidOwner
  foreach($parent in @('D:\objrun-experiment-stores',$ownerRoot)){
    OrdinaryAncestors $parent
    if(!(Test-Path -LiteralPath $parent)){New-Item -ItemType Directory -Path $parent -ErrorAction Stop | Out-Null}
    OrdinaryAncestors $parent
  }
  $null=FreshPaidOwner
  New-Item -ItemType Directory -Path $physical -ErrorAction Stop | Out-Null
  OrdinaryAncestors $physical
  $layout=@{protocol='scientific-journal-store-v2';runId=$RunId;mode='owned-d-new-store';allowedOwnerRoot=$ownerRoot;physicalStore=$physical;logicalStore=$logical;ownerPid=$OwnedPid;paidLockSha256=(Get-FileHash -LiteralPath $paidLock -Algorithm SHA256).Hash.ToLower();storageLeasePin=$leasePin;scriptPin=$scriptPin;resourceEvidence=$observed;createdAtUtc=[DateTime]::UtcNow.ToString('o');reuse='never';oldStoresMoved=$false;credentialsIncluded=$false}
  $physicalReceipt=WriteSynced (Join-Path $physical 'storage-owner.json') $layout
  $null=FreshPaidOwner
  New-Item -ItemType Junction -Path $logical -Value $physical -ErrorAction Stop | Out-Null
  $link=Get-Item -LiteralPath $logical -Force
  if($link.LinkType -ne 'Junction' -or @($link.Target).Count -ne 1 -or [IO.Path]::GetFullPath([string]@($link.Target)[0]).TrimEnd('\') -ine $physical.TrimEnd('\')){throw 'new_junction_target_mismatch'}
  if((Get-FileHash -LiteralPath (Join-Path $logical 'storage-owner.json') -Algorithm SHA256).Hash.ToLower() -cne $physicalReceipt.sha256){throw 'logical_physical_bytes_differ'}
  $layout.junctionVerified=$true;$layout.physicalOwnerReceiptPin=$physicalReceipt
  $layoutReceipt=WriteSynced $layoutPath $layout
  $null=FreshPaidOwner
  ConvertTo-Json -Depth 30 -Compress -InputObject @{prepared=$true;mode='owned-d-new-store';layout=$layoutReceipt;physicalStore=$physical;logicalStore=$logical;modelCalls=0;note='Owned setup lease intentionally retained as evidence; no unknown data was reclaimed.'}
}catch{
  $failure=@{protocol='scientific-journal-storage-failure-v2';runId=$RunId;error=$_.Exception.GetType().Name;typedError=$_.Exception.Message;physicalStore=$physical;logicalStore=$logical;leasePath=$leasePath;partialRetained=$true;modelCalls=0;recovery='Inspect exact owned new paths and receipts; no automatic deletion or lock reclamation.'}
  try{$null=WriteSynced ($layoutPath+'.failure.json') $failure}catch{}
  throw
}
