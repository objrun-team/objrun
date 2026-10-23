import { randomBytes } from 'node:crypto';
import { closeSync, existsSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, readdirSync, realpathSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { type AdmissionLease, FAULT_SHA, PID_CERT_SHA, FAILED_RUN, assertPidsAbsent, observeOriginalPaidPids, scanOtherPaidRuns } from './paid-resource-admission-v2.ts';
import { verifyCashClosure } from './cny-cash-shadow-v2.ts';
import { actualPin, demand, gzipProof, hash, inside, jsonPin, nanoCny, REAL_CLOCK, requestValues, same, validatePrices, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { assertJpgClosureShape, assertJpgFoundationColdOnly, JPG_FAMILY, loadDStorage, validateJpgRecipe, type JpgRecipe } from './jpg-D-journal-contract.ts';
import { prospectiveJpgFinancialPreflight } from './jpg-financial-abort-scanner-v1.ts';
import { actualJpgPriorUsd as legacyJpgPriorUsd, scanJpgPaidRuns as scanLegacyJpgPaidRuns } from './jpg-paid-resource-admission-v1.ts';

const ROOT=resolve(import.meta.dir,'../..'), SELF=actualPin(import.meta.path), POSITIONS=[5470,5471,5473,5475], ORIGINAL_PIDS=[50652,38176,87440,96080,96848];
export const JPG_REGISTRY='jpg-D-paid-resource-run-v1';
export function durableJpgJson(path:string,value:unknown,replace=false):Pin {
  mkdirSync(dirname(path),{recursive:true}); const bytes=Buffer.from(JSON.stringify(value,null,2)+'\n');
  const target=replace?path+'.tmp-'+randomBytes(8).toString('hex'):path,fd=openSync(target,'wx',0o600);
  try{writeFileSync(fd,bytes);fsyncSync(fd);}finally{closeSync(fd);}
  demand(readFileSync(target).equals(bytes),'jpg_json_readback'); if(replace)renameSync(target,path);
  demand(readFileSync(path).equals(bytes),'jpg_json_commit_readback'); return actualPin(path);
}
/** Four original unknown transfers are carried as liability, never settled by a JPG run. */
export function jpgCarry(recipe:JpgRecipe,root=ROOT){
  demand(recipe.deferredFault.sha256===FAULT_SHA&&recipe.originalPidClosure.sha256===PID_CERT_SHA,'jpg_original_fault_policy');
  const fault=jsonPin(recipe.deferredFault),closed=jsonPin(recipe.originalPidClosure),critical:Pin[]=[recipe.deferredFault,recipe.originalPidClosure];
  demand(fault.protocol==='saved-scientific-campaign-deferred-fault-v1'&&fault.validated===true&&fault.campaign===FAILED_RUN&&fault.type==='infrastructure_abort_with_unknown_provider_receipts','jpg_original_fault');
  demand(fault.cost.ledgerCalls===5476&&fault.cost.finishedWithReportedUsage===5472&&fault.cost.unfinished===4&&same(fault.deferredCalls.map((row:any)=>row.ledgerPosition),POSITIONS),'jpg_original_pending_set');
  for(const name of ['manifest.json','source.json','summary.json','api-ledger.json','frozen-source.json','frozen-source.zip']){
    const rows=fault.identity.originalEvidenceFiles.filter((row:any)=>basename(row.path)===name); demand(rows.length===1&&rows[0].unchanged&&same(rows[0].before,rows[0].after),'jpg_original_evidence');
    const pin={path:resolve(root,rows[0].path),bytes:rows[0].before.bytes,sha256:rows[0].before.sha256};verifyPin(pin);critical.push(pin);
  }
  const ledger=jsonPin(critical.find(pin=>basename(pin.path)==='api-ledger.json')!);
  demand(ledger.campaign===FAILED_RUN&&ledger.calls.length===5476&&same(ledger.calls.flatMap((call:any,i:number)=>call.finishedAt?[]:[i]),POSITIONS)&&Math.abs(ledger.reservedUpperBoundUsd-1.258827)<1e-9,'jpg_original_ledger');
  const carry=fault.deferredCalls.map((row:any)=>{
    const pin={path:resolve(root,row.requestGzip.path),sha256:row.requestGzip.sha256,bytes:row.requestGzip.bytes},raw=gzipProof(pin,row.requestGzip.rawSha256,undefined,4*1024**2),v=requestValues(raw),call=ledger.calls[row.ledgerPosition];
    demand(raw.length===row.rawRequestBytes&&v.data.messages.length===row.messageCount&&v.inputUpper===row.inputUpperBoundFromFrozenFormula&&v.output===row.outputLimit,'jpg_original_raw_request');
    demand(call.providerAttempted===true&&call.requestSha256===row.requestGzip.rawSha256&&!call.finishedAt&&!call.usage&&!call.responseFile&&!existsSync(join(root,'.phase1-data/repair',FAILED_RUN,`provider-${row.ledgerPosition}-response.json.gz`)),'jpg_original_unknown_state');
    critical.push(pin);return{id:FAILED_RUN+'/'+row.ledgerPosition,ledgerPosition:row.ledgerPosition,requestSha256:row.requestGzip.rawSha256,peakNanoCny:v.peakNano.toString(),status:'unknown_original_provider_receipt' as const,settled:false as const};
  });
  demand(carry.reduce((sum:bigint,row:any)=>sum+BigInt(row.peakNanoCny),0n)===8392180000n&&same(closed.processes.map((row:any)=>row.pid),ORIGINAL_PIDS)&&closed.processes.every((row:any)=>row.present===false),'jpg_original_carry_or_actor');return{carry,critical};
}
export function verifyJpgCertificate(pin:Pin,expectedRun:string,kind:'real-provider'|'local-mock'){
  const cert=jsonPin(pin);assertJpgClosureShape(cert,expectedRun,kind);
  const summary=jsonPin(cert.summary),report=jsonPin(cert.auditor),source=jsonPin(cert.source),owned=jsonPin(cert.owned),grading=jsonPin(cert.grading),secrets=jsonPin(cert.secrets);
  demand(cert.storageVariant==='jpg-D-journal-v1','jpg_D_certificate_variant');
  demand(report.protocol==='jpg-D-journal-independent-audit-v1'&&report.family===JPG_FAMILY&&report.runId===expectedRun&&report.integrityValid===true&&report.scoreCertificateValid===true&&report.modelCalls===0&&report.errors.length===0,'jpg_actual_auditor_failed');
  demand(report.auditorSourcePin&&basename(report.auditorSourcePin.path)==='audit-jpg-D-journal-campaign.py'&&source.pins.some((p:Pin)=>same(p,report.auditorSourcePin)),'jpg_auditor_source_binding');
  verifyPin(report.auditorSourcePin);demand(Array.isArray(report.inputArtifacts)&&report.inputArtifacts.length>=9,'jpg_audit_inputs');
  for(const input of report.inputArtifacts)verifyPin(input);
  for(const bound of [cert.summary,cert.source,cert.owned,cert.grading,cert.secrets,cert.cash,cert.journal,cert.raw])demand(report.inputArtifacts.some((p:Pin)=>same(p,bound)),'jpg_audit_pin_graph');
  demand(summary.protocol==='jpg-journal-operational-summary-v1'&&summary.family===JPG_FAMILY&&summary.runId===expectedRun&&summary.providerKind===kind&&summary.operationalComplete===true&&summary.formalScoreCertified===false&&!summary.fatal&&summary.plannedTaskRuns===2&&summary.taskPins.length===2,'jpg_summary_not_closed');
  demand(source.protocol==='jpg-journal-source-close-v1'&&source.family===JPG_FAMILY&&source.runId===expectedRun&&source.pins.length>0,'jpg_source_close');for(const p of source.pins)verifyPin(p);
  demand(owned.protocol==='jpg-journal-owned-close-v1'&&owned.family===JPG_FAMILY&&owned.runId===expectedRun&&owned.closed===true&&owned.enginePids.length===2&&owned.bridgePid>0&&owned.processes.every((p:any)=>p.present===false)&&owned.ports.every((p:any)=>p.closed===true)&&owned.containers.every((p:any)=>p.present===false),'jpg_owned_close');
  demand(grading.protocol==='jpg-journal-grading-close-v1'&&grading.family===JPG_FAMILY&&grading.runId===expectedRun&&grading.finalGrades.length===2&&grading.generationClosedBeforeAllFinalGrading===true,'jpg_grading_close');
  demand(secrets.passed===true&&secrets.secretValuesChecked===6&&secrets.findings.length===0,'jpg_secret_close');
  const replay=verifyCashClosure(cert.cash); demand(replay.config.providerKind===kind&&replay.proof.runId===expectedRun&&same(cert.journal,replay.proof.journalConfigPin)&&!replay.proof.snapshot.poisoned,'jpg_cash_family_binding');
  if(kind==='real-provider')demand(BigInt(replay.proof.snapshot.newExposureNanoCny)<=BigInt(replay.config.envelopeNanoCny)&&replay.config.carryNanoCny==='8392180000'&&jsonPin(replay.config.admissionPin).family===JPG_FAMILY,'jpg_cash_envelope_or_carry');
  for(const p of summary.taskPins){const task=jsonPin(p);demand(task.family===JPG_FAMILY&&task.runId===expectedRun&&task.generationValid===true&&task.acceptance.valid===true,'jpg_task_invalid');}
  return{cert,source,summary,cash:replay};
}
export function validateDStoreInitialization(recipe:JpgRecipe){
  const d=loadDStorage(recipe),p=actualPin(join(recipe.output,'initial-store.json')),v=jsonPin(p);
  demand(v.protocol==='jpg-D-store-initialization-v1'&&v.family===JPG_FAMILY&&v.runId===recipe.runId&&v.ownerNonce===d.ownerNonce&&v.storePhysical===d.storePhysical&&v.storeLogical===d.storeLogical&&same(v.directories,d.directories)&&same(v.descriptorPin,recipe.DStorage.descriptorPin)&&same(v.sourcePins,recipe.sourcePins),'jpg_D_initialization_identity');
  demand(v.validated===true&&v.freshRootCreated===true&&v.actualDirectoryIdentityVerified===true&&v.setupNativeHandleClosed===true&&v.modelCalls===0&&v.providerForwarded===0&&v.DockerOperations===0&&v.canonicalPaidLockAcquired===false&&v.scoreCertificate===false&&v.paidReady===false,'jpg_D_initialization_zero_provider');
  demand(resolve(v.initializationSourcePin.path)===join(import.meta.dir,'jpg-D-store-init-v1.py')&&recipe.sourcePins.some(s=>same(s,v.initializationSourcePin)),'jpg_D_initializer_source');verifyPin(v.initializationSourcePin);verifyPin(v.intentPin);
  const closed=jsonPin(v.setupClosedLeasePin);demand(resolve(v.setupClosedLeasePin.path)===join(d.directories.leases!,'setup.lock')&&closed.protocol==='jpg-owned-D-evidence-storage-v1-native-lease'&&closed.held===false&&closed.fixtureOnly===false&&closed.nonce===d.ownerNonce&&closed.pid===v.creatorPid&&resolve(closed.root)===resolve(d.storePhysical),'jpg_D_setup_lease_bytes');
  const empty=['raw','sqlite','journal','cash','source','private-logs','stand','captures','audit'];
  for(const name of empty){const path=d.directories[name]!;demand(lstatSync(path).isDirectory()&&!lstatSync(path).isSymbolicLink()&&realpathSync(path).toLowerCase()===resolve(path).toLowerCase()&&readdirSync(path).length===0,'jpg_D_pre_run_phase_not_empty');}
  demand(same(readdirSync(recipe.output).sort(),['initial-store-intent.json','initial-store.json']),'jpg_D_pre_run_metadata_inventory');
  demand(same(readdirSync(d.directories.leases!).sort(),['setup.lock']),'jpg_D_pre_run_foreign_or_held_lease');
  return p;
}
export function saveJpgDDiscovery(recipe:JpgRecipe,registryPin:Pin){
  const d=loadDStorage(recipe);demand(resolve(registryPin.path)===join(recipe.output,'jpg-paid-resource-run.json'),'jpg_D_discovery_registry_path');verifyPin(registryPin);
  const path=join(d.FPointerDirectory,'discovery.json'),value={protocol:'jpg-D-evidence-discovery-v1',family:JPG_FAMILY,runId:recipe.runId,ownerNonce:d.ownerNonce,descriptorPin:recipe.DStorage.descriptorPin,registryPin,recipeSourceDigest:hash(JSON.stringify(recipe.sourcePins)),modelEvidenceDirectory:recipe.output,formalPaidReady:false};
  demand(Buffer.byteLength(JSON.stringify(value))<16384,'jpg_D_discovery_bound');
  if(existsSync(path)){const old=jsonPin(actualPin(path));demand(old.runId===recipe.runId&&old.ownerNonce===d.ownerNonce&&same(old.descriptorPin,value.descriptorPin),'jpg_D_discovery_owner_changed');}
  return durableJpgJson(path,value,existsSync(path));
}
/** Extra D family: every actual run must have a complete typed closure. */
export function scanJpgDRegistries(root:string,currentRun:string){
  demand(resolve(root)===ROOT,'jpg_D_scanner_root');const home=join(root,'docs/repair-2026-10-08/jpg-D-store-pointers');let total=0;const inputPins:Pin[]=[],closedRunIds:string[]=[];
  if(!existsSync(home))return{family:JPG_FAMILY,closedRecordedCostUpperBoundUsd:0,inputPins,closedRunIds};
  for(const name of readdirSync(home)){
    demand(/^[a-f0-9]{32}$/.test(name),'jpg_D_unknown_pointer_scope');const pointer=actualPin(join(home,name,'discovery.json')),p=jsonPin(pointer);
    demand(p.protocol==='jpg-D-evidence-discovery-v1'&&p.family===JPG_FAMILY&&p.ownerNonce===name,'jpg_D_pointer_family');if(p.runId===currentRun)continue;
    const d=jsonPin(p.descriptorPin);demand(d.ownerNonce===name&&resolve(p.registryPin.path)===join(d.directories.taskmeta,'jpg-paid-resource-run.json'),'jpg_D_pointer_registry_role');
    const r=jsonPin(p.registryPin);demand(r.protocol===JPG_REGISTRY&&r.family===JPG_FAMILY&&r.runId===p.runId&&r.released===true&&r.certificationPin,'jpg_D_other_scope_unclosed');
    const verified=verifyJpgCertificate(r.certificationPin,p.runId,r.providerKind);inputPins.push(pointer,p.descriptorPin,p.registryPin,r.certificationPin);closedRunIds.push(p.runId);
    if(r.providerKind==='real-provider'){
      demand(r.releasePin&&r.releaseCommittedPin,'jpg_D_release_ack_missing');const release=jsonPin(r.releasePin),ack=jsonPin(r.releaseCommittedPin),admission=jsonPin(r.admissionPin);
      demand(release.protocol==='jpg-financial-release-v1'&&release.runId===p.runId&&release.originalUnknownSettled===false&&same(release.proof.certification,r.certificationPin)&&ack.protocol==='jpg-lock-release-committed-v1'&&ack.runId===p.runId&&ack.ownerNonce===admission.owned.ownerNonce&&same(ack.authorizationPin,r.releasePin)&&ack.released===true,'jpg_D_release_nonce_graph');
      const ledgerPin=actualPin(join(d.directories.taskmeta,'api-ledger.json')),ledger=jsonPin(ledgerPin);demand(ledger.campaign===p.runId&&ledger.reservedUpperBoundUsd===0&&Number.isFinite(ledger.recordedUsageUpperBoundUsd)&&ledger.recordedUsageUpperBoundUsd>=0&&Math.abs(ledger.recordedUsageUpperBoundUsd-verified.summary.recordedUsageUpperBoundUsd)<1e-9,'jpg_D_prior_closed_ledger');
      total+=ledger.recordedUsageUpperBoundUsd;inputPins.push(r.releasePin,r.releaseCommittedPin,r.admissionPin,ledgerPin);
    }else demand(r.providerKind==='local-mock'&&r.productionLockAcquired===false,'jpg_D_mock_not_paid');
  }return{family:JPG_FAMILY,closedRecordedCostUpperBoundUsd:total,inputPins,closedRunIds};
}

/** Independent JPG owner with the frozen cash module's structural finance ABI. No scientific score wrapper. */
export async function acquireJpgPaidResource(recipe:JpgRecipe):Promise<AdmissionLease>{
  assertJpgFoundationColdOnly('real-provider');
  validateJpgRecipe(recipe);const d=loadDStorage(recipe);demand(recipe.mode==='real-provider'&&recipe.balance&&recipe.requestedNewEnvelopeCny&&resolve(recipe.output)===resolve(d.directories.taskmeta!),'jpg_explicit_production_recipe');
  const original=jpgCarry(recipe),balance=jsonPin(recipe.balance),price=validatePrices(recipe.prices),now=Date.now(),ttl=(at:string,span:number)=>{const t=Date.parse(at);demand(Number.isFinite(t)&&t<=now&&now-t<=span,'jpg_resource_expired');};
  demand(balance.protocol==='deepseek-resource-readonly-v1'&&balance.provider==='https://api.deepseek.com'&&balance.endpoint==='/user/balance'&&balance.method==='GET'&&balance.httpStatus===200&&balance.isAvailable===true&&balance.modelCalls===0&&balance.credentialPrinted===false,'jpg_balance_scope');ttl(balance.observedAtUtc,1800000);ttl(price.observedAtUtc,86400000);
  const rows=balance.balances.filter((x:any)=>x.currency==='CNY');demand(rows.length===1,'jpg_cny_balance');const available=nanoCny(rows[0].total_balance);demand(nanoCny(rows[0].granted_balance)+nanoCny(rows[0].topped_up_balance)===available,'jpg_balance_components');
  const carry=8392180000n,headroom=nanoCny(recipe.headroomCny),envelope=nanoCny(recipe.requestedNewEnvelopeCny);demand(headroom>=30000000000n&&envelope>0n&&carry+headroom+envelope<=available,'jpg_cash_envelope');
  assertPidsAbsent(ORIGINAL_PIDS,await observeOriginalPaidPids());const preflight=await prospectiveJpgFinancialPreflight(ROOT,recipe.runId,recipe.financialBoundary),own=scanJpgDRegistries(ROOT,recipe.runId);
  demand(Math.abs(preflight.priorCampaignCostUpperBoundUsd+own.closedRecordedCostUpperBoundUsd-recipe.priorCampaignCostUpperBoundUsd)<1e-9,'jpg_actual_prior_usd_changed');
  validateDStoreInitialization(recipe);
  const path=join(ROOT,'.phase1-data/owned-paid-campaign.lock.json'),owned=Object.freeze({pid:process.pid,startedAt:new Date().toISOString(),runId:recipe.runId,entry:recipe.sourcePins.find(p=>basename(p.path)==='skb-jpg-D-journal-campaign.ts')!.path,ownerNonce:randomBytes(24).toString('hex'),family:JPG_FAMILY,purpose:'independent-jpg-D-UF',policyFaultSha256:FAULT_SHA});
  // A write failure retains the actual lock and evidence. It never takes over another owner.
  durableJpgJson(path,owned);let released=false,cashPin:Pin|undefined;const registered:Pin[]=[];
  const assertOwned=()=>demand(!released&&same(JSON.parse(readFileSync(path,'utf8')),owned),'jpg_lock_owner_changed');
  const proofPin=durableJpgJson(join(recipe.output,'jpg-admission.json'),{protocol:'paid-resource-admission-v2',family:JPG_FAMILY,purpose:'jpg-finance-only',runId:recipe.runId,scope:'production',owned,createdAt:new Date().toISOString(),recipe,sourcePins:recipe.sourcePins,originalCriticalPins:original.critical,carry:original.carry,carryNanoCny:carry.toString(),balanceNanoCny:available.toString(),headroomNanoCny:headroom.toString(),selectedNewEnvelopeNanoCny:envelope.toString(),balancePin:recipe.balance,pricePin:recipe.prices});
  const registry=join(recipe.output,'jpg-paid-resource-run.json');durableJpgJson(registry,{protocol:JPG_REGISTRY,family:JPG_FAMILY,runId:recipe.runId,providerKind:'real-provider',admissionPin:proofPin,released:false,certificationPin:null});saveJpgDDiscovery(recipe,actualPin(registry));
  const validateForwardSource=()=>{assertOwned();for(const p of [...recipe.sourcePins,recipe.balance!,recipe.prices])verifyPin(p);const t=Date.parse(price.observedAtUtc);demand(Date.now()>=t&&Date.now()-t<=86400000,'jpg_price_expired');};
  return Object.freeze({protocol:'paid-resource-admission-v2' as const,root:ROOT,runId:recipe.runId,path,proofPin,owned,envelopeNanoCny:envelope,balanceNanoCny:available,headroomNanoCny:headroom,carryNanoCny:carry,carry:original.carry,clock:REAL_CLOCK,scope:'production' as const,sourcePins:recipe.sourcePins,assertOwned,validateForwardSource,
    registerCash(pin:Pin){assertOwned();const c=jsonPin(pin);demand(!cashPin&&c.protocol==='cny-shadow-config-v2'&&c.providerKind==='real-provider'&&c.runId===recipe.runId&&c.ownerNonce===owned.ownerNonce&&same(c.admissionPin,proofPin)&&c.envelopeNanoCny===envelope.toString()&&c.carryNanoCny===carry.toString(),'jpg_cash_register');cashPin=pin;},
    registerOwnedProcess(pin:Pin){assertOwned();const p=jsonPin(pin);demand(p.protocol==='paid-owned-process-v2'&&p.family===JPG_FAMILY&&p.runId===recipe.runId&&p.ownerNonce===owned.ownerNonce&&p.pid>0&&p.pid!==process.pid&&!registered.some(r=>jsonPin(r).pid===p.pid),'jpg_process_register');registered.push(pin);},
    async release(proof:any){assertOwned();validateForwardSource();for(const p of original.critical)verifyPin(p);demand(cashPin&&registered.length===3,'jpg_registered_resources_incomplete');const graph=verifyJpgCertificate(proof.certification,recipe.runId,'real-provider');
      demand(same(graph.cert.source,proof.sourceClosed)&&same(graph.cert.owned,proof.ownedClosed)&&same(graph.cert.cash,proof.cashClosed)&&same(graph.source.pins,recipe.sourcePins)&&same(graph.cash.config.admissionPin,proofPin)&&same(graph.cash.proof.configPin,cashPin),'jpg_release_graph');
      const raw=jsonPin(proof.rawClosed);demand(raw.protocol==='jpg-journal-raw-close-v1'&&raw.family===JPG_FAMILY&&raw.runId===recipe.runId&&same(raw.journalPrefix,graph.cash.proof.journalPrefix)&&graph.cert.raw&&same(graph.cert.raw,proof.rawClosed),'jpg_release_raw');
      const ownedClose=jsonPin(proof.ownedClosed);demand(same(ownedClose.registrationPins,registered),'jpg_registered_process_graph');for(const p of ownedClose.registrationPins)verifyPin(p);
      const {jpgNativeOperation}=await import('./skb-jpg-D-journal-campaign.ts');
      await jpgNativeOperation(['--verify-owned','--owned-scope',proof.ownedClosed.path,'--output',join(recipe.output,'release-fresh-owned.json')],15000);
      demand(Date.now()-Date.parse(graph.cert.createdAtUtc)<60000,'jpg_final_certificate_stale');
      validateForwardSource();const closure=durableJpgJson(join(recipe.output,'jpg-financial-release.json'),{protocol:'jpg-financial-release-v1',family:JPG_FAMILY,runId:recipe.runId,owned,proof,carriedOriginalUnknownNanoCny:carry.toString(),originalUnknownSettled:false,releaseAuthorized:true,authorizedAtUtc:new Date().toISOString()});
      const record={protocol:JPG_REGISTRY,family:JPG_FAMILY,runId:recipe.runId,providerKind:'real-provider',admissionPin:proofPin,released:true,certificationPin:proof.certification,releasePin:closure,releaseCommittedPin:null as Pin|null};
      durableJpgJson(registry,record,true);saveJpgDDiscovery(recipe,actualPin(registry));assertOwned();unlinkSync(path);released=true;
      const ack=durableJpgJson(join(recipe.output,'jpg-lock-release-committed.json'),{protocol:'jpg-lock-release-committed-v1',family:JPG_FAMILY,runId:recipe.runId,ownerNonce:owned.ownerNonce,authorizationPin:closure,released:true,committedAtUtc:new Date().toISOString()});durableJpgJson(registry,{...record,releaseCommittedPin:ack},true);saveJpgDDiscovery(recipe,actualPin(registry));
    }});
}
