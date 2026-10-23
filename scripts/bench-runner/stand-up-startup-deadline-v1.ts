/** Opt-in pre-begin /up transport bound to the actual signed parent deadline. */
import{readFileSync,existsSync}from'node:fs';import{join,resolve}from'node:path';import{createHash,verify}from'node:crypto';
const authoritySha='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98';
const initializedParents=new Set<string>();
function need(x:unknown,label:string):asserts x{if(!x)throw Error('stand_up_deadline:'+label)}
function checked(p:any){need(p&&Object.keys(p).sort().join(',')==='bytes,path,sha256'&&typeof p.path==='string'&&Number.isSafeInteger(p.bytes),'pin');const b=readFileSync(p.path);need(b.length===p.bytes&&createHash('sha256').update(b).digest('hex')===p.sha256,'pin_changed');return b}
export function deriveStartupDeadline(v:{parentCreatedUnix:number;outerSeconds:number;entryExpiryUnix:number;bindingExpiryUnix:number;explicitParentDeadlineUnix?:number},nowUnix:number){
 need(Number.isFinite(v.parentCreatedUnix)&&v.parentCreatedUnix>0&&v.parentCreatedUnix<=nowUnix,'actual_parent_birth');need(Number.isInteger(v.outerSeconds)&&v.outerSeconds>0&&v.outerSeconds<=86400,'original_parent_outer');
 const values=[v.parentCreatedUnix+v.outerSeconds,v.entryExpiryUnix,v.bindingExpiryUnix];if(v.explicitParentDeadlineUnix!==undefined)values.push(v.explicitParentDeadlineUnix);
 need(values.every(x=>Number.isFinite(x)&&x>0),'absolute_deadlines');const deadlineUnix=Math.min(...values);need(deadlineUnix>nowUnix,'expired');return{deadlineUnix,remainingMs:Math.max(1,Math.floor((deadlineUnix-nowUnix)*1000))};
}
export function startupFetchOptions(binding:any){
 need(binding?.protocol==='bench-original-stand-up-parent-deadline-v1'&&binding.path==='/up'&&binding.preBeginOnly===true&&binding.originalHttpDefaultMs===120000,'closed_binding');
 const run=process.env.BENCH_RUN_DIR,mp=process.env.BENCH_MANIFEST_PATH;need(run&&mp&&process.env.BENCH_STAGE==='solve','actual_parent_context');
 const envelope=JSON.parse(readFileSync(join(run,'root-entry.signed.json'),'utf8')),e=envelope.entry;need(envelope.protocol==='novaeve-root-signed-entry-v4'&&e.phase==='ready','signed_entry');
 const m=JSON.parse(readFileSync(mp,'utf8')),authority=m.adapterConfig.bindingSpec.authorityPin;need(authority.sha256===authoritySha&&authority.bytes===113,'authority');need(verify(null,Buffer.from(JSON.stringify(e)),checked(authority),Buffer.from(envelope.signature,'base64')),'signature');
 const rb=e.rootRuntimeBinding;need(rb?.stage==='solve'&&rb.attemptId===e.nonce&&resolve(rb.manifestPin.path)===resolve(mp),'signed_parent_binding');checked(rb.manifestPin);
 const neutral=binding.scope==='no-bench-affected-acceptance';if(neutral){need(e.neutralNoBench===true&&e.modelCalls===0&&e.benchGradeCalls===0,'neutral_scope')}else{
  need(binding.scope==='original-task-pre-begin'&&binding.acceptancePin,'actual_acceptance_required');const a=JSON.parse(checked(binding.acceptancePin).toString());need(a.protocol==='bench-owner-signed-stand-up-transport-acceptance-v1'&&verify(null,Buffer.from(JSON.stringify(a.proof)),checked(authority),Buffer.from(a.signature,'base64'))&&a.proof.accepted===true&&a.proof.actualDelaySeconds>120&&a.proof.actualOriginalParentAndPythonChild===true&&a.proof.originalParentDeadlinePreserved===true,'affected_acceptance');
 }
 const record=JSON.parse(readFileSync(join(run,'process.json'),'utf8'));need(record.pid===process.pid,'same_actual_parent_pid');let born:number;
 if(record.creation||record.incarnation){const ft=String(record.creation??record.incarnation);need(/^\d+$/.test(ft),'windows_filetime');born=Number(BigInt(ft)-116444736000000000n)/1e7}else{need(neutral&&Number.isFinite(record.createdEpoch),'native_parent_creation');born=record.createdEpoch}
 need(Math.abs((Date.now()/1000-process.uptime())-born)<5,'actual_parent_birth_matches_runtime');
 const original=m.stages.solve.outerTimeoutSeconds;let explicit:number|undefined;const deadlineFile=join(run,'absolute-deadline.json');if(existsSync(deadlineFile)){const x=JSON.parse(readFileSync(deadlineFile,'utf8'));explicit=x.deadlineUnix??x.absoluteDeadlineUnix;need(Number.isFinite(explicit),'existing_parent_deadline')}
 const result=deriveStartupDeadline({parentCreatedUnix:born,outerSeconds:original,entryExpiryUnix:Date.parse(rb.expiresAtUtc)/1000,bindingExpiryUnix:Date.parse(m.adapterConfig.bindingSpec.expiresAtUtc)/1000,explicitParentDeadlineUnix:explicit},Date.now()/1000);
 need(!initializedParents.has(e.nonce),'pre_begin_initialization_only_once');initializedParents.add(e.nonce);
 return{signal:AbortSignal.timeout(result.remainingMs),timeout:false};
}
export function startupLauncherSource(text:string,s:any){
 if(!s.startupDeadlineBinding)return text;const b=s.startupDeadlineBinding;need(b.protocol==='bench-original-stand-up-parent-deadline-v1'&&b.path==='/up'&&b.preBeginOnly===true&&b.originalHttpDefaultMs===120000,'binding');checked(b.helperPin);
 const anchor='signal:AbortSignal.timeout(timeoutMs)';need(text.split(anchor).length===2,'unique_original_signal');const importLine='import { startupFetchOptions as originalStandUpFetchOptions } from '+JSON.stringify(b.helperPin.path.replaceAll('\\','/'))+';\n';
 return importLine+text.replace(anchor,'...(path==="/up"?originalStandUpFetchOptions('+JSON.stringify(b)+'):{signal:AbortSignal.timeout(timeoutMs)})');
}
