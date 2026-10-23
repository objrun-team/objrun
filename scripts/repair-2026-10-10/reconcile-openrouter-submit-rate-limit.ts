/** Reconcile only this task's closed smoke-test explicit upstream rate rejection. */
import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync, unlinkSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { gunzipSync } from 'node:zlib';
import { actualPin, demand, jsonPin, same, verifyPin } from '../repair-2026-10-08/paid-resource-proof-v2.ts';
import { verifyBenchmarkCashClosure } from '../repair-2026-10-08/benchmark-usd-cash.ts';
import { inspectCampaignJournal } from '../repair-2026-10-08/campaign-journal.ts';
import { benchmarkProviderKey } from '../repair-2026-10-08/benchmark-provider.ts';

const root=resolve(import.meta.dir,'../..'),file=actualPin(resolve(process.argv[2]??'')),result=jsonPin(file),directory=resolve(file.path,'..');
demand(result.protocol==='openrouter-current-system-submit-check-v1'&&result.live===true&&result.benchmarkStarted===false&&result.accountingClosed===true&&!result.ownerReleased,'only_closed_owned_smoke_rejection');
const ownerPath=join(root,'.phase1-data/owned-paid-campaign.lock.json'),ownerPin=actualPin(ownerPath),owner=jsonPin(ownerPin),admission=jsonPin(actualPin(join(directory,'openrouter-admission.json')));
demand(owner.family==='openrouter-submit-smoke-v1'&&same(owner,admission.owned)&&owner.runId===admission.runId&&owner.runId===jsonPin(result.ledgerPin).campaign&&Number.isSafeInteger(owner.pid)&&owner.pid>0,'owned_smoke_identity');
const script='$ErrorActionPreference="Stop"; $taskProcess=Get-Process -Id '+owner.pid+' -ErrorAction SilentlyContinue; if($null -ne $taskProcess){throw "Owned smoke PID remains alive"}; "absent"';
demand(execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],{windowsHide:true,encoding:'utf8'}).trim()==='absent','owned_smoke_not_absent');
const cash=verifyBenchmarkCashClosure(result.cashPin),journal=inspectCampaignJournal(join(directory,'journal'));
demand(journal.valid&&journal.accountingClosed&&cash.config.ownerNonce===owner.ownerNonce&&cash.proof.snapshot.pendingCount===0&&cash.proof.snapshot.newUnknownCount>0,'smoke_original_financial_binding');
// Save the exact currently verified sources before any subsequent adapter fixes.
const attempt=join(directory,'reconciliation-'+randomUUID());mkdirSync(attempt);
const snapshots:any[]=[];mkdirSync(join(attempt,'sources'));
for(const [index,pin]of [...result.sourcePins,cash.config.sourcePin].entries()){
  verifyPin(pin);const path=join(attempt,'sources',index+'.source');writeFileSync(path,readFileSync(pin.path),{flag:'wx'});snapshots.push({originalPin:pin,snapshotPin:actualPin(path)});
}
const rows=readFileSync(join(directory,'journal/api-events.jsonl'),'utf8').trim().split('\n').map(line=>JSON.parse(line)).filter(row=>row.kind==='finish');
let known=0,settled=0;const rejected:any[]=[],generations:any[]=[];
for(const event of rows){
  const receipt=event.record;
  if(receipt.costBasis!=='reservation'){known+=receipt.usdUpperBound;continue;}
  demand(receipt.httpStatus===429&&receipt.providerAttempted===true&&receipt.responseFile&&!receipt.requestId&&!receipt.usage,'smoke_unknown_not_explicit_429');
  const data=JSON.parse(gunzipSync(readFileSync(receipt.responseFile)).toString('utf8')),error=data.error;
  demand(error?.code===429&&error.metadata?.limit_source==='upstream_provider_shared_pool'&&error.metadata.provider_name==='Relace'
    &&typeof error.metadata.raw==='string'&&error.metadata.raw.includes('temporarily rate-limited upstream')&&!data.id&&!data.usage&&!data.choices,'explicit_pre_generation_shared_pool_rejection');
  rejected.push({requestSeq:event.requestSeq,requestPin:actualPin(receipt.requestFile),responsePin:actualPin(receipt.responseFile),originalReservationUsd:receipt.usdUpperBound,reconciledCostUsd:0,reason:'Explicit upstream rate rejection; no generation or token usage.'});settled+=receipt.usdUpperBound;
}
demand(rejected.length===cash.proof.snapshot.newUnknownCount&&Math.abs(settled-cash.proof.snapshot.unknownReservationUsd)<1e-9&&Math.abs(known-cash.proof.snapshot.billedUsd)<1e-9,'complete_smoke_unknown_reconciliation');
for(const event of rows.filter(row=>row.record.requestId)){
  const response=await fetch('https://openrouter.ai/api/v1/generation?id='+encodeURIComponent(event.record.requestId),{headers:{authorization:'Bearer '+benchmarkProviderKey(root)},signal:AbortSignal.timeout(30000)});
  const raw=await response.text(),path=join(attempt,'generation-'+event.requestSeq+'.json');writeFileSync(path,raw,{flag:'wx'});
  const data=JSON.parse(raw).data;demand(response.ok&&data?.id===event.record.requestId&&data.provider_name==='Relace'&&data.total_cost===event.record.billedCostUsd,'smoke_generation_usd_binding');generations.push(actualPin(path));
}
// OpenRouter's official zero-completion policy states that error responses are uncharged.
const policyURL='https://openrouter.ai/blog/insights/why-openrouter-for-deepseek/';
const policy=await fetch(policyURL,{signal:AbortSignal.timeout(30000)}),policyText=await policy.text();
demand(policy.ok&&policyText.includes('Zero Completion Insurance')&&policyText.includes('zero output tokens'),'official_zero_completion_policy');
const policyPath=join(attempt,'zero-completion-policy.html');writeFileSync(policyPath,policyText,{flag:'wx'});
const proof={protocol:'openrouter-owned-smoke-rejection-reconciliation-v1',runId:owner.runId,owned:owner,resultPin:file,originalCashPin:result.cashPin,
  originalUnknownReservationUsd:settled,reconciledUnknownUsd:0,billedUsd:known,rejected,generationPins:generations,
  policyURL,policyPin:actualPin(policyPath),sourceSnapshots:snapshots,ownedPidObservedAbsent:true,observedAtUtc:new Date().toISOString(),
  originalJournalAndCashUnmodified:true,invoice:false,originalDeepSeekCnyUnknownSettled:false,sourcePin:actualPin(import.meta.path)};
const path=join(directory,'financial-reconciliation.json');writeFileSync(path,JSON.stringify(proof,null,2)+'\n',{flag:'wx'});
verifyPin(ownerPin);demand(same(jsonPin(ownerPin),owner),'smoke_owner_changed');unlinkSync(ownerPath);
const closed=join(directory,'reconciled-owner-release.json');writeFileSync(closed,JSON.stringify({protocol:'openrouter-reconciled-smoke-owner-release-v1',proofPin:actualPin(path),owned:owner,canonicalOwnerReleased:true,invoice:false},null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({proofPath:path,canonicalOwnerReleased:true,billedUsd:known,reconciledUnknownUsd:0}));
