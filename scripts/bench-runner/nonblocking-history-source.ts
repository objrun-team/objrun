/** Build-time common policy branch; originals and old releases remain immutable. */
import {join} from 'node:path';
function once(s:string,a:string,b:string){if(s.split(a).length!==2)throw Error('nonblocking_policy_anchor_not_unique:'+a);return s.replace(a,b)}
export function nonblockingHistorySource(path:string,s:string,here:string){
 const name=path.replaceAll('\\','/').split('/').pop();
 const touched=['manifest.ts','runner.ts','queue.ts','index.ts','runtime.ts','terminal-driver.ts'].includes(name!);if(!touched)return s;
 const helper=JSON.stringify(join(here,'nonblocking-history-policy.ts').replaceAll('\\','/'));
 const header='import {historyAdmission,hasHistoryAdmission,manifestPinHistoryAdmission,policyHistory,policyRootEntry,policyOriginalRecovery} from '+helper+';\n';
 if(name==='manifest.ts')return s; // Numeric verified subtotals remain explicit; null historical totals live in facts.
 if(name==='runner.ts'){
  s=once(s,"demand(!task.quarantined&&m.history.stateKnown,'unknown_history_quarantined');","demand((!task.quarantined&&m.history.stateKnown)||hasHistoryAdmission(m),'unknown_history_quarantined');");
  s=once(s,"demand(!['inflight','quarantined'].includes(inventory.state),'inventory_not_admissible');","demand(!['inflight','quarantined'].includes(inventory.state)||hasHistoryAdmission(m),'inventory_not_admissible');");
  s=once(s,'let originalRecoveryProofPin:Pin|undefined;','let originalRecoveryProofPin:Pin|undefined=historyAdmission(m)?.authorizationPin;');
  s=once(s,"if(!task.valid&&(m.history.originalResultRecoveryRequired||inventory.state==='recoverable')){","if(!task.valid&&!hasHistoryAdmission(m)&&(m.history.originalResultRecoveryRequired||inventory.state==='recoverable')){");
 }
 if(name==='queue.ts'){
  s=once(s,"demand(t&&!t.quarantined,'enqueue_unknown_task');","demand(t&&(!t.quarantined||manifestPinHistoryAdmission(manifestPin)),'enqueue_unknown_task');");
  s=once(s,"demand(t&&!t.quarantined,'task_unknown_or_quarantined');","demand(t&&(!t.quarantined||manifestPinHistoryAdmission(manifestPin)),'task_unknown_or_quarantined');");
  s=once(s,"demand(t&&!t.quarantined&&(!t.valid||['cleanup','reconcile','archive'].includes(a.stage)),'planned_task_not_eligible');","demand(t&&(!t.quarantined||manifestPinHistoryAdmission(JSON.parse(a.manifest_pin)))&&(!t.valid||['cleanup','reconcile','archive'].includes(a.stage)),'planned_task_not_eligible');");
 }
 if(name==='index.ts'&&path.replaceAll('\\','/').endsWith('/adapters/index.ts')){
  s=once(s,'export async function recoverFor(bench: Bench, m: TaskManifest, c: AttemptContext): Promise<StageResult> {','export async function recoverFor(bench: Bench, m: TaskManifest, c: AttemptContext): Promise<StageResult> {\n if(c.attemptId===\'original-recovery\'&&hasHistoryAdmission(m))return policyOriginalRecovery(m) as StageResult;');
  s=once(s,"if(m.history.originalResultRecoveryRequired||c.inventoryTask.state==='recoverable') {","if(!hasHistoryAdmission(m)&&(m.history.originalResultRecoveryRequired||c.inventoryTask.state==='recoverable')) {");
 }
 if(name==='runtime.ts'){
  s=once(s,"if (!manifest.history.stateKnown) throw Error('unknown_history_quarantined');","if (!manifest.history.stateKnown&&!hasHistoryAdmission(manifest)) throw Error('unknown_history_quarantined');");
  s=once(s,"if(policy.historicalClosureProofPins.length===0||!c.originalRecoveryProofPin)throw Error('existing_canonical_requires_closed_original_recovery');","if(!hasHistoryAdmission(m)&&(policy.historicalClosureProofPins.length===0||!c.originalRecoveryProofPin))throw Error('existing_canonical_requires_closed_original_recovery');");
  s=once(s,"} else if(policy.legacyOriginalIdentityNull!==true||policy.historicalLockPins.length!==0)throw Error('new_canonical_requires_honest_legacy_null_identity');","} else if(!hasHistoryAdmission(m)&&(policy.legacyOriginalIdentityNull!==true||policy.historicalLockPins.length!==0))throw Error('new_canonical_requires_honest_legacy_null_identity');");
 }
 if(name==='terminal-driver.ts'){
  s=once(s,'export function inspectLegacyHistory(m:TaskManifest,d:TerminalDriverConfig) {','export function inspectLegacyHistory(m:TaskManifest,d:TerminalDriverConfig) {\n if(hasHistoryAdmission(m))return policyHistory(m);');
  const lines=s.split('\n'),matches=lines.map((x,i)=>x.includes("'root_reviewed_legacy_data_required'")?i:-1).filter(i=>i>=0);if(matches.length!==1)throw Error('nonblocking_root_review_anchor');const i=matches[0];lines[i]='  if(hasHistoryAdmission(m))policyRootEntry(m,entry);else '+lines[i].trim();s=lines.join('\n');
 }
 return header+s;
}
