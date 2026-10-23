/** Own read-only consumer of TB12 release evidence; no TB writer imports. */
import { spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync,readdirSync,lstatSync } from 'node:fs';
import { join } from 'node:path';
import { actualPin,demand,jsonPin,same,verifyPin,type Pin } from './paid-resource-proof-v2.ts';
import { verifyCashClosure } from './cny-cash-shadow-v2.ts';
import { inspectCampaignJournal } from './campaign-journal.ts';
import { loadNativePython } from './skb-jpg-native-python.ts';
import { durableJpgJson } from './jpg-paid-resource-admission-v1.ts';

export async function scanTb12ClosedPaidRuns(root:string,currentRun:string){
  const home=join(root,'docs/repair-2026-10-09/tb12-runs-v1'),inputPins:Pin[]=[],closedRunIds:string[]=[],nativeResults:any[]=[];let total=0;
  if(existsSync(home))for(const name of readdirSync(home).sort()){
    const dir=join(home,name),path=join(dir,'tb12-paid-resource-run.json');if(!existsSync(path))continue;
    demand(lstatSync(dir).isDirectory()&&!lstatSync(dir).isSymbolicLink(),'skb_tb12_directory');const p=actualPin(path),r=jsonPin(p);if(r.runId===currentRun)continue;
    demand(r.protocol==='tb12-paid-resource-run-v1'&&r.family==='terminal-bench-twelve-journal-v1'&&r.runId===name&&r.released===true&&r.closedPin&&r.releaseAckPin,'skb_tb12_previous_unclosed');
    const a=jsonPin(r.admissionPin),c=jsonPin(r.closedPin),ack=jsonPin(r.releaseAckPin);
    demand(c.protocol==='tb12-independent-close-certificate-v1'&&c.family===r.family&&c.runId===r.runId&&c.ownerNonce===a.owned.ownerNonce
      &&same(ack.owned,a.owned)&&same(ack.certificatePin,r.closedPin),'skb_tb12_certificate_identity');
    const cash=verifyCashClosure(c.cashClosePin),journal=inspectCampaignJournal(cash.config.journalDirectory);
    demand(cash.config.providerKind==='real-provider'&&cash.config.runId===r.runId&&cash.config.ownerNonce===a.owned.ownerNonce
      &&same(cash.config.admissionPin,r.admissionPin)&&cash.config.carryNanoCny==='8392180000'&&cash.config.envelopeNanoCny===a.selectedNewEnvelopeNanoCny
      &&cash.proof.snapshot.pendingCount===0&&cash.proof.snapshot.newUnknownCount===0&&BigInt(cash.proof.snapshot.newExposureNanoCny)<=BigInt(cash.config.envelopeNanoCny)
      &&c.newEstimatedNanoCny===cash.proof.snapshot.newKnownEstimatedNanoCny&&journal.valid&&journal.accountingClosed,'skb_tb12_raw_cash_journal');
    demand(['financial-only','score-and-financial'].includes(c.kind),'skb_tb12_certificate_kind');
    if(c.kind==='score-and-financial'){
      const audit=jsonPin(c.rawAuditPin);for(const q of audit.inputPins)verifyPin(q);
      demand(audit.integrityValid&&audit.providerKind==='real-provider'&&audit.result.taskRuns===24&&audit.result.distinctTaskCount===12,'skb_tb12_score_graph');
    }
    const n=loadNativePython(),script=join(import.meta.dir,'skb_artifact_tb12_scan_v2.py'),scriptPin=actualPin(script),argv=['-B','-X','utf8',script,'--run-directory',dir];
    const began=Date.now(),child=spawnSync(n.executable,argv,{windowsHide:true,timeout:180000,maxBuffer:2*1024**2,encoding:'utf8'});
    const caller=durableJpgJson(join(root,'docs/repair-2026-10-08/skillsbench-ten-takeover-v1/cross-family-preflights',randomBytes(16).toString('hex')+'.json'),
      {protocol:'skillsbench-cross-family-readonly-native-caller-v2',argv,scriptPin,nativeExecutablePin:actualPin(n.executable),childPid:child.pid,parentPid:process.pid,
        startedAtUnixMs:began,finishedAtUnixMs:Date.now(),directWaitReturned:true,exitCode:child.status,signal:child.signal,errorCode:child.error?.name??null,
        stdout:child.stdout,stderr:child.stderr,neighboringWrites:0,modelCalls:0});
    demand(child.status===0&&!child.error&&child.pid,'skb_tb12_actual_readonly_native_scan');const native=JSON.parse(child.stdout);
    demand(native.neighboringWrites===0&&native.modelCalls===0&&native.DockerOperations===0&&native.runId===r.runId&&same(native.registryPin,p)&&same(native.sourcePin,scriptPin),'skb_tb12_native_scan_binding');
    nativeResults.push({callerPin:caller,childPid:child.pid,directWaitReturned:true,exitCode:child.status,sourcePin:scriptPin,native});
    total+=journal.snapshot!.recordedUsageUpperBoundUsd;closedRunIds.push(r.runId);inputPins.push(p,r.admissionPin,r.closedPin,r.releaseAckPin,ack.freshOwnedObservationPin,c.cashClosePin,cash.proof.configPin,cash.proof.cashEventsPin,scriptPin);
    verifyPin(p); // Never adopt a registry that changed during the replay.
  }
  demand(new Set(closedRunIds).size===closedRunIds.length,'skb_tb12_duplicate_run');
  return {family:'terminal-bench-twelve-journal-v1',closedRecordedCostUpperBoundUsd:total,closedRunIds,inputPins,nativeResults,neighboringWrites:0,modelCalls:0};
}
