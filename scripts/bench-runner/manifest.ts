import {openSync,readSync,closeSync,lstatSync,readFileSync,realpathSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {resolve,isAbsolute} from 'node:path';
import {STAGES,type Pin,type TaskManifest} from './types.ts';
export function demand(value:unknown,message:string):asserts value {if(!value)throw Error(message)}
export function pin(path:string):Pin {
 const p=resolve(path),s=lstatSync(p);demand(s.isFile()&&!s.isSymbolicLink(),'pin_regular_file_required');
 const h=createHash('sha256'),fd=openSync(p,'r'),b=Buffer.alloc(1024*1024);try{let n;while((n=readSync(fd,b,0,b.length,null))>0)h.update(b.subarray(0,n))}finally{closeSync(fd)}
 const after=lstatSync(p);demand(s.size===after.size&&s.mtimeMs===after.mtimeMs&&s.ino===after.ino,'pin_changed_during_read');return{path:p,bytes:s.size,sha256:h.digest('hex')};
}
export function verifyPin(p:Pin):Pin {demand(p&&typeof p.path==='string'&&isAbsolute(p.path)&&Number.isSafeInteger(p.bytes)&&p.bytes>=0&&/^[a-f0-9]{64}$/.test(p.sha256),'invalid_pin');const a=pin(p.path);demand(a.bytes===p.bytes&&a.sha256===p.sha256,'pin_changed:'+p.path);return a}
const nonnegative=(n:unknown)=>typeof n==='number'&&Number.isFinite(n)&&n>=0;
export function validateManifest(m:TaskManifest):TaskManifest {
 demand(m?.schemaVersion===1&&['terminal-bench','skillsbench'].includes(m.bench)&&typeof m.taskId==='string'&&/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,200}$/.test(m.taskId),'manifest_identity');
 demand(isAbsolute(m.root)&&isAbsolute(m.artifactRoot)&&realpathSync(m.root)===realpathSync(resolve(m.root)),'manifest_absolute_root');
 const o=m.original;demand(o&&['cpu','memoryMb','solveSeconds','gradeSeconds','toolSeconds','providerSeconds'].every(k=>nonnegative((o as any)[k])&&(o as any)[k]>0),'original_limits_required');
 demand(['model','provider','reasoning'].every(k=>typeof(o as any)[k]==='string'&&(o as any)[k].length>0)&&[o.taskCapUsd,o.priorKnownUsd,o.priorUnknownUsd].every(nonnegative)&&o.priorKnownUsd+o.priorUnknownUsd<=o.taskCapUsd,'original_budget_required');
 demand(m.provenance?.sourcePins?.length>0&&m.provenance.contractPins?.length>0&&m.provenance.inventoryPin,'manifest_provenance_required');
 for(const p of [...m.provenance.sourcePins,...m.provenance.contractPins,m.provenance.inventoryPin,...(m.provenance.authorizationPin?[m.provenance.authorizationPin]:[])])verifyPin(p);
 demand(typeof m.history?.stateKnown==='boolean'&&typeof m.history.originalResultRecoveryRequired==='boolean'&&Array.isArray(m.history.validResultPins)&&Array.isArray(m.history.priorRunPins),'manifest_history_required');
 for(const p of [...m.history.validResultPins,...m.history.priorRunPins,...Object.values(m.history.successfulStageProofs).flat()])verifyPin(p!);
 demand(m.stages&&Object.keys(m.stages).every(k=>(STAGES as readonly string[]).includes(k)),'unknown_stage');
 for(const [stage,s] of Object.entries(m.stages)){
  demand(s&&['reuse','command'].includes(s.kind)&&['read-only','native','model','grade','oracle'].includes(s.effect)&&Number.isInteger(s.timeoutSeconds)&&s.timeoutSeconds>0,'stage_contract');
  for(const p of s.evidencePins)verifyPin(p);
  if(s.kind==='reuse')demand(s.evidencePins.length>0&&!!s.originalSuccessKey&&!s.command,'reuse_requires_original_success_provenance');
  else demand(Array.isArray(s.command)&&s.command.length>0&&s.command.every(x=>typeof x==='string'&&x.length>0&&!x.includes('\0'))&&isAbsolute(s.command[0]),'command_array_absolute_executable_required');
  if(s.effect==='model')demand(stage==='solve'&&s.timeoutSeconds<=o.solveSeconds,'model_only_original_solve_limit');
  if(s.effect==='grade')demand(stage==='grade'&&s.timeoutSeconds<=o.gradeSeconds,'original_grade_limit');
  if(s.bundledStages){demand(s.kind==='command'&&s.bundledStages.length>0&&new Set(s.bundledStages).size===s.bundledStages.length&&s.bundledStages.every(k=>(STAGES as readonly string[]).includes(k)),'bundled_stage_names');demand(typeof s.outerTimeoutSeconds==='number'&&s.outerTimeoutSeconds>=s.timeoutSeconds&&s.outerTimeoutSeconds<=o.solveSeconds+o.gradeSeconds+o.toolSeconds*2,'original_outer_custody_envelope');}
  else demand(s.outerTimeoutSeconds===undefined||s.outerTimeoutSeconds===s.timeoutSeconds,'outer_limit_requires_declared_bundle');
  if(s.kind==='command'&&['native','model','grade','oracle'].includes(s.effect))demand(s.resourceMode==='driver-owned','qualified_driver_must_own_original_pool_lease');
  if(s.effect==='oracle'&&s.kind==='command'){demand(m.history.stateKnown&&!!s.originalSuccessKey,'first_oracle_requires_known_history_and_checkpoint_key');const checkpoints=m.adapterConfig.successfulCheckpoints as Record<string,unknown>|undefined;demand(!checkpoints?.[s.originalSuccessKey!],'successful_oracle_must_reuse_original_qualification');}
 }
 demand(m.adapterConfig&&typeof m.adapterConfig==='object','adapter_config_required');return m;
}
export function loadManifest(path:string):TaskManifest {const before=pin(path),m=JSON.parse(readFileSync(path,'utf8'));validateManifest(m);verifyPin(before);return m}
