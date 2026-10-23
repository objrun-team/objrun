/** Read-only broker/journal verification; writes only the coordinator audit receipt. */
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { gunzipSync } from 'node:zlib';
import { inspectCampaignJournal } from './shared/supplier-journal.ts';
import { verifyBenchmarkCashClosure } from './shared/supplier-usd-cash.ts';
import { actualPin } from '../../benchmark-repair/paid-resource-proof-v2.ts';
import { verifyReconciliation } from './shared/cash-reconciliation.ts';
import { auditProviderFlights } from './audit-events.ts';
import { verifyClosedBrokerHistory } from './audit-closed-broker.ts';
import { verifyDeadBrokerRecovery } from './shared/dead-broker-recovery.ts';
import { verifyChemBenchStreamEvidence } from './chembench/upstream-stream-transport.ts';
import {verifyApprovedSupplierStreamEvidence} from './chembench/supplier-stream-transport.ts';
import {verifyApprovedSupplierStreamEvidence as verifyContinuationStreamEvidence} from './chembench/supplier-stream-continuation.ts';
import {verifyChemiqStreamEvidence} from './chemiq/upstream-stream-length-staged.ts';
import { verifyControlledBrokerRecovery } from './shared/controlled-broker-recovery.ts';

const root = resolve(import.meta.dir, '../../..');
const output = join(root, 'docs/repair-2026-10-10/full-f-rerun');
const json = (path: string) => JSON.parse(readFileSync(path, 'utf8'));
const control = json(join(output, 'control.json'));
const health = json(control.broker.healthPath);
const lockPath = join(root, '.phase1-data/owned-paid-campaign.lock.json');
const ownerMatches = health.canonicalOwner
  ? existsSync(lockPath) && JSON.stringify(json(lockPath)) === JSON.stringify(health.canonicalOwner)
  : !existsSync(lockPath);
const commonSourcePinsUnchanged = control.broker.sourcePins.every((pin: any) => {
  const current = actualPin(pin.path);
  return current.bytes === pin.bytes && current.sha256 === pin.sha256;
});
const lanes = health.lanes as any[];
const historicalAudits=(control.brokerHistory??[]).filter((entry:any)=>entry.runId!==health.runId).map((entry:any)=>{
  if(entry.controlledRecoveryPin){try{return verifyControlledBrokerRecovery(entry.controlledRecoveryPin);}catch(error){return{runId:entry.runId,verified:false,error:String(error),retained:true};}}
  if(entry.recoveryPin){try{return verifyDeadBrokerRecovery(entry.recoveryPin);}catch(error){return{runId:entry.runId,verified:false,error:String(error),retained:true};}}
  if(!entry.reconciliationPin){try{return verifyClosedBrokerHistory(entry);}catch(error){return{runId:entry.runId,verified:false,error:String(error),retained:true};}}
  try{const checked=verifyReconciliation(entry.reconciliationPin);return{runId:entry.runId,verified:true,
    effectiveBilledUsd:checked.effectiveBilledUsd,originalUnknownCostCount:checked.originalUnknownCostCount,
    remainingUnknownCostCount:checked.remainingUnknownCostCount,originalCashUnmodified:true,releasePin:entry.releasePin};}
  catch(error){return{runId:entry.runId,verified:false,error:String(error),retained:true};}
});
const laneAudits: any[] = [];
let actualResponseCostsMatch = true;
const generationIds = new Set<string>();
let duplicateGeneration = false;
for (const lane of lanes) {
  const registeredCashPath=[join(lane.output,'currency/cash-config.json'),join(lane.output,'journal/currency/cash-config.json'),join(lane.output,'cash/cash-config.json')].find(existsSync);
  const journalPath = registeredCashPath?json(registeredCashPath).journal.directory:join(lane.output,'journal');
  let journal = inspectCampaignJournal(journalPath),inspectionRetries=0;
  // Independent processes can append between the event and checkpoint reads.
  // Retry only the live checkpoint race; persistent errors remain visible.
  while(!journal.valid&&!lane.closed&&journal.errors.every(error=>error==='checkpoint_prefix_or_accounting')&&inspectionRetries<2){
    journal=inspectCampaignJournal(journalPath);inspectionRetries++;
  }
  const closePath = [join(lane.output, 'currency/cash-close.json'), join(journalPath, 'currency/cash-close.json'),join(lane.output,'cash/cash-close.json')]
    .find(existsSync);
  let verifiedCashClosed = false;
  let verifiedAccountingClosed = false;
  let cashClosureError: string | null = null;
  if (closePath) {
    try { const closed=verifyBenchmarkCashClosure(actualPin(closePath));verifiedAccountingClosed=true;verifiedCashClosed=closed.proof.releasePermitted===true; }
    catch (error) { cashClosureError = String(error); }
  }
  let responseRecordsChecked = 0;
  let responseCostMismatches = 0;
  let streamEvidenceChecked=0,streamEvidenceMismatches=0;
  const eventPath = join(journalPath, 'api-events.jsonl');
  if (existsSync(eventPath)) {
    // A live writer can append after this read. Only complete durable lines are inspected.
    const raw = readFileSync(eventPath, 'utf8');
    for (const line of raw.slice(0, raw.lastIndexOf('\n') + 1).split('\n').filter(Boolean)) {
      const event = JSON.parse(line);
      if (event.kind !== 'finish') continue;
      const record = event.record;
      if (record.requestId) {
        if (generationIds.has(record.requestId)) duplicateGeneration = true;
        generationIds.add(record.requestId);
      }
      if (record.costBasis !== 'provider_reported_usd') continue;
      if(lane.slug==='chemiq'&&health.transportPolicy?.chemiq?.startsWith('pinned-task39')&&existsSync(join(dirname(journalPath),'stream-task-scope.json'))){
        try{const nonDO=lane.providerSlug&&lane.providerSlug!=='digitalocean';const proof=nonDO?verifyContinuationStreamEvidence(join(dirname(control.broker.healthPath),'stream-evidence',lane.runId+'-'+event.requestSeq)):verifyChemiqStreamEvidence(join(dirname(control.broker.healthPath),'chemiq-stream-evidence',lane.runId+'-'+event.requestSeq));streamEvidenceChecked++;
          if(proof.providerError||proof.httpStatus!==200||proof.generation!==record.requestId||proof.usage?.cost!==record.billedCostUsd||proof.sourceEvidence.aggregateSha256!==record.responseSha256)streamEvidenceMismatches++;
        }catch{streamEvidenceMismatches++;}
      }
      if(lane.slug==='chembench'&&health.transportPolicy?.chembench?.startsWith('upstream-sse')){
        try{const replay=health.transportPolicy.chembench.includes('length-v2')?verifyContinuationStreamEvidence:health.transportPolicy.chembench.includes('approved-supplier')?verifyApprovedSupplierStreamEvidence:verifyChemBenchStreamEvidence;const proof=replay(join(dirname(control.broker.healthPath),'stream-evidence',lane.runId+'-'+event.requestSeq));streamEvidenceChecked++;
          if(proof.providerError||proof.httpStatus!==200||proof.generation!==record.requestId||proof.usage?.cost!==record.billedCostUsd||proof.sourceEvidence.aggregateSha256!==record.responseSha256)streamEvidenceMismatches++;
        }catch{streamEvidenceMismatches++;}
      }
      const response = JSON.parse(gunzipSync(readFileSync(record.responseFile)).toString('utf8'));
      responseRecordsChecked++;
      const expectedProvider=json(join(journalPath,'journal-config.json')).providerName??'DeepSeek';
      if (response.id !== record.requestId || response.usage?.cost !== record.billedCostUsd
        || response.usage?.cost !== record.usdUpperBound || response.provider !== expectedProvider
        || record.requestedModel !== 'deepseek/deepseek-v4.1-flash') responseCostMismatches++;
    }
  }
  actualResponseCostsMatch &&= responseCostMismatches === 0&&streamEvidenceMismatches===0;
  laneAudits.push({ slug: lane.slug, runId: lane.runId, journalValid: journal.valid,
    errors: journal.errors, inspectionRetries,accepted: journal.snapshot?.acceptedRequestCount,
    finished: journal.snapshot?.finishedRequestCount,
    knownCostUpperUsd: journal.snapshot?.recordedUsageUpperBoundUsd,
    pendingReserveUsd: journal.snapshot?.reservedUpperBoundUsd,
    brokerClosed: lane.closed, verifiedCashClosed, verifiedAccountingClosed, cashClosureError,
    responseRecordsChecked, responseCostMismatches,streamEvidenceChecked,streamEvidenceMismatches, unknownCostCount: lane.unknownCount });
}
const eventsPath = join(dirname(control.broker.healthPath), 'events');
const flightAudit=auditProviderFlights((existsSync(eventsPath)?readdirSync(eventsPath):[]).filter(name=>/^\d+\.json$/.test(name)).sort().map(name=>json(join(eventsPath,name))));
const {peakRequests,peakPerBench,duplicateDispatch}=flightAudit;
const denominators: Record<string, number> = { chembench: 500, chemiq: 816, skillsbench: 87, 'terminal-bench': 89 };
const benchStatus = Object.entries(denominators).map(([slug, denominator]) => {
  const status = json(join(output, slug, 'status.json'));
  let terminalProtocolFailures: number | null = null;
  if (slug === 'chembench') {
    const results = join(output, slug, 'results');
    terminalProtocolFailures = readdirSync(results).filter(name => /^task-\d+\.json$/.test(name))
      .map(name => json(join(results, name))).filter(record => record.terminalProtocolFailure === true).length;
  }
  return { slug, denominator, declaredDenominator: status.planned ?? status.denominator,
    stage: status.stage ?? status.phase, completed: status.completed, terminalProtocolFailures,
    runnerPid: status.runnerPid ?? status.pid ?? status.processPid ?? status.backgroundPaidProcessPid ?? null };
});
const resources = health.resourceSlots?Object.fromEntries(health.resourceSlots.map((value:any)=>[value.kind+'/'+value.slug+'/'+value.pid,{slug:value.slug,pid:value.pid,slots:value.slots,memoryMb:value.memoryMb}])):
  Object.fromEntries(Object.entries(health.resources as Record<string, any>).map(([kind, value]) => [kind, { slug: value.slug, pid: value.pid }]));
const trackedPids = [...new Set([health.pid, ...benchStatus.map(value => value.runnerPid),
  ...Object.values(resources).map(value => value.pid)].filter(value => Number.isInteger(value) && value > 0))];
const filter = trackedPids.map(value => `ProcessId=${value}`).join(' or ');
const processResult = Bun.spawnSync(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
  `@(Get-CimInstance Win32_Process -Filter '${filter}' | ForEach-Object { @{pid=$_.ProcessId; parentPid=$_.ParentProcessId; createdAtUtc=$_.CreationDate.ToUniversalTime().ToString('o'); commandLine=$_.CommandLine} }) | ConvertTo-Json -Compress`]);
const processRows = processResult.exitCode === 0 ? JSON.parse(processResult.stdout.toString() || '[]') : null;
const processes=processRows===null?null:Array.isArray(processRows)?processRows:[processRows];
const allocatedCapUsd = lanes.filter(lane=>health.canonicalOwner&&json(join(lane.output,'shared-admission/openrouter-lane-admission.json')).ownerNonce===health.canonicalOwner.ownerNonce)
  .reduce((sum, lane) => {
    if(!health.allocation||!lane.closed)return sum+lane.capUsd;
    const path=[join(lane.output,'currency/cash-close.json'),join(lane.output,'journal/currency/cash-close.json'),join(lane.output,'cash/cash-close.json')].find(existsSync);
    if(!path)throw Error('Closed lane lacks original cash closure');
    return sum+verifyBenchmarkCashClosure(actualPin(path)).proof.snapshot.exposureUpperBoundUsd;
  }, 0);
// Journal/source replay can take longer than the heartbeat freshness window.
// Check the current file after replay, preserving the original sampled evidence.
const finalHealth=json(control.broker.healthPath);
const brokerFresh=finalHealth.runId===health.runId&&finalHealth.pid===health.pid&&Date.now()-Date.parse(finalHealth.atUtc)<20000;
const audit = { protocol: 'full-f-heartbeat-audit-v2', atUtc: new Date().toISOString(), automationId: 'bench-f',
  ownerMatches, commonSourcePinsUnchanged, brokerHealthy: finalHealth.healthy&&commonSourcePinsUnchanged&&Array.isArray(processes)&&processes.some((p:any)=>p.pid===health.pid&&['digitalocean-broker.ts','digitalocean-broker-600.ts','digitalocean-broker-cb-stream.ts','digitalocean-broker-cb-suppliers.ts','digitalocean-broker-cb-continuation.ts','digitalocean-broker-cb-score-completion.ts','digitalocean-broker-cq-stream.ts','digitalocean-broker-cq-suppliers.ts','digitalocean-broker-container-parallel.ts','digitalocean-broker-parallel-lanes.next.ts','digitalocean-broker-eight-tasks.next.ts','digitalocean-broker-dynamic-sixteen-actual-disk.next.ts','digitalocean-broker-sixteen-proxy10809.next.ts'].some(entry=>control.broker.sourcePins[0].path.replaceAll('\\','/').endsWith('/'+entry)&&(p.commandLine??'').includes(entry)))&&brokerFresh,
  brokerStatusFresh:brokerFresh,sampledHealthAtUtc:health.atUtc,finalHealthAtUtc:finalHealth.atUtc,stopReason: finalHealth.stopReason,costPolicy:control.costPolicy,historicalAudits,
  observedPeakRequests: peakRequests, observedPeakPerBench: peakPerBench, duplicateDispatch,
  incompleteFlightsEnded:flightAudit.incompleteFlightsEnded,ambiguousForwardResults:flightAudit.ambiguousForwardResults,
  duplicateGeneration, actualResponseCostsMatch, laneAudits, benchStatus, resources, processes,
  inactiveLanesClosed: laneAudits.filter(lane => lane.brokerClosed).every(lane => lane.verifiedAccountingClosed),
  financiallyResolved:historicalAudits.every((r:any)=>r.verified===true&&r.remainingUnknownCostCount===0&&r.financiallyResolved!==false)&&laneAudits.filter(lane=>lane.brokerClosed).every(lane=>lane.verifiedCashClosed),
  parentCapUsd: health.parentCapUsd, allocatedCapUsd,
  unallocatedCapUsd: health.parentCapUsd === null ? null : health.parentCapUsd - allocatedCapUsd,
  allocationMatches:health.allocation?Math.abs(allocatedCapUsd-health.allocation.allocatedUsd)<1e-7:null,
  allocationNote:health.allocation?'Closed lane actual known and unknown reserve remain allocated; unused cap is recycled through verified original closures.':'Legacy closed forkLane caps stay allocated until parent release.',
  modelCallsByAudit: 0 };
const path = join(output, `audit-${audit.atUtc.replace(/[:.]/g, '-')}.json`);
writeFileSync(path, JSON.stringify(audit, null, 2) + '\n');
console.log(JSON.stringify({ path, ...audit }, null, 2));
