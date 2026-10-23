/** Root data publication only. No signing key, child process, lease, lane or Bench side effect. */
import { verify } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import { join,resolve } from 'node:path';
import type { TaskManifest,AttemptContext,Pin } from './types.ts';
import { checkPin,filePin,readPinned,wxJson,expand } from './runtime.ts';

export interface BindingSpec {
  protocol:'bench-root-data-binding-v1'; authorityPin:Pin; entryTemplatePin:Pin;
  inputs:Record<string,{pin:Pin;select:'path'|'sha256'}>;
  output:{root:string;prefix:string}; expiresAtUtc:string;
}
function requireValue(value:unknown,message:string):asserts value {if(!value)throw Error(message);}
function specFor(m:TaskManifest):BindingSpec {
  const s=m.adapterConfig.bindingSpec as unknown as BindingSpec;
  requireValue(s?.protocol==='bench-root-data-binding-v1','binding_spec_protocol');
  checkPin(s.authorityPin);checkPin(s.entryTemplatePin);
  requireValue(Date.parse(s.expiresAtUtc)>Date.now(),'binding_spec_expired');
  requireValue(s.output && /^[a-zA-Z0-9._-]+$/.test(s.output.prefix),'safe_output_prefix');
  for(const [name,input] of Object.entries(s.inputs)) {
    requireValue(/^[A-Z][A-Z0-9_]*$/.test(name)&&!['NONCE','OUTPUT','RECOVERY_ENTRY','ENTRY_ENVELOPE','MANIFEST_PATH','CONTEXT_PATH','MANIFEST','CONTEXT'].includes(name),'binding_input_name');
    requireValue(input.select==='path'||input.select==='sha256','binding_input_selection');checkPin(input.pin);
    requireValue([...m.provenance.sourcePins,...m.provenance.contractPins].some(p=>p.path===input.pin.path&&p.sha256===input.pin.sha256),'binding_input_not_reviewed');
  }
  return s;
}
function valuesFor(s:BindingSpec,c:AttemptContext):Record<string,string> {
  requireValue(/^[a-zA-Z0-9_-]+$/.test(c.attemptId),'safe_fresh_attempt_id');
  const values:Record<string,string>={NONCE:c.attemptId,OUTPUT:resolve(s.output.root,s.output.prefix+c.attemptId),
    RECOVERY_ENTRY:join(c.runDir,'recovery.entry.json'),ENTRY_ENVELOPE:join(c.runDir,'root-entry.signed.json'),MANIFEST_PATH:c.manifestPath,CONTEXT_PATH:join(c.runDir,'intent-context.json'),MANIFEST:c.manifestPath,CONTEXT:join(c.runDir,'intent-context.json')};
  for(const [key,input]of Object.entries(s.inputs))values[key]=input.select==='path'?resolve(input.pin.path):input.pin.sha256;
  return values;
}
function substitute(value:any,values:Record<string,string>):any {
  if(typeof value==='string')return value.replace(/\{\{bindings\.([A-Z][A-Z0-9_]*)\}\}/g,(_,key)=>{
    requireValue(Object.hasOwn(values,key),'unknown_binding:'+key);return values[key];
  });
  if(Array.isArray(value))return value.map(x=>substitute(x,values));
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,substitute(v,values)]));
  return value;
}
export function prepareContextDraft(m:TaskManifest,c:AttemptContext):{draftPin:Pin;requestPin:Pin;bindings:Record<string,string>} {
  checkPin(c.manifestPin);const s=specFor(m),values=valuesFor(s,c);
  const original=readPinned(s.entryTemplatePin),entry=substitute(original,values);
  requireValue(entry.taskId===m.taskId&&entry.bench===m.bench&&entry.nonce===c.attemptId,'fresh_template_entry_identity');
  requireValue(Array.isArray(entry.argv),'reviewed_driver_argv_required');
  const command=m.stages[c.stage]?.command;
  requireValue(Array.isArray(command)&&JSON.stringify(entry.argv)===JSON.stringify(command.map(x=>expand(x,{...c,bindings:values}))),'signed_argv_must_equal_manifest_expanded_command');
  // Original budget/history/policy fields remain in the root-reviewed template, never regenerated or reset here.
  entry.rootRuntimeBinding={protocol:'bench-root-runtime-binding-v1',attemptId:c.attemptId,taskId:c.taskId,bench:c.bench,
    stage:c.stage,manifestPin:c.manifestPin,templatePin:s.entryTemplatePin,inputPins:Object.values(s.inputs).map(x=>x.pin),
    expiresAtUtc:s.expiresAtUtc,bindings:values};
  const draftPath=join(c.runDir,'root-entry.draft.json');wxJson(draftPath,entry);
  const requestPath=join(c.runDir,'binding-request.json');wxJson(requestPath,{protocol:'bench-root-signing-request-v1',draftPin:filePin(draftPath),
    authorityPin:s.authorityPin,signedEnvelopeDestination:values.ENTRY_ENVELOPE,signatureProtocol:'novaeve-root-signed-entry-v4',
    originalAuthorityMaySet:{coordinatorReviewed:true,phase:'ready'},newModelNativeLaneCalls:0});
  return {draftPin:filePin(draftPath),requestPin:filePin(requestPath),bindings:values};
}
export function loadPreparedContext(m:TaskManifest,c:AttemptContext,readOnly=false):AttemptContext {
  checkPin(c.manifestPin);const s=specFor(m),values=valuesFor(s,c),envelope=JSON.parse(readFileSync(values.ENTRY_ENVELOPE,'utf8').replace(/^\uFEFF/,''));
  requireValue(envelope.protocol==='novaeve-root-signed-entry-v4'&&envelope.entry&&typeof envelope.signature==='string','root_envelope_required');
  requireValue(verify(null,Buffer.from(JSON.stringify(envelope.entry)),readFileSync(s.authorityPin.path),Buffer.from(envelope.signature,'base64')),'root_signature_invalid');
  const e=envelope.entry,b=e.rootRuntimeBinding;
  const command=m.stages[c.stage]?.command;
  requireValue(Array.isArray(command)&&JSON.stringify(e.argv)===JSON.stringify(command.map(x=>expand(x,{...c,bindings:values}))),'signed_argv_must_equal_manifest_expanded_command');
  requireValue(e.coordinatorReviewed===true&&e.nonce===c.attemptId&&e.taskId===m.taskId&&e.bench===m.bench,'root_entry_identity');
  requireValue(b?.protocol==='bench-root-runtime-binding-v1'&&b.attemptId===c.attemptId&&b.taskId===c.taskId&&b.bench===c.bench&&b.stage===c.stage,'root_runtime_identity');
  requireValue(JSON.stringify(b.manifestPin)===JSON.stringify(c.manifestPin)&&JSON.stringify(b.templatePin)===JSON.stringify(s.entryTemplatePin),'root_manifest_template_binding');
  requireValue(JSON.stringify(b.bindings)===JSON.stringify(values)&&b.expiresAtUtc===s.expiresAtUtc&&Date.parse(b.expiresAtUtc)>Date.now(),'root_binding_expired_or_changed');
  for(const p of b.inputPins)checkPin(p);
  requireValue(JSON.stringify(b.inputPins)===JSON.stringify(Object.values(s.inputs).map(x=>x.pin)),'root_input_pin_set');
  // Compare all old contract/cash/unknown/lock fields, allowing only the original authority's documented metadata update.
  const expected=substitute(readPinned(s.entryTemplatePin),values);
  for(const [key,value]of Object.entries(expected))if(!['coordinatorReviewed','phase','rootRuntimeBinding'].includes(key))requireValue(JSON.stringify(e[key])===JSON.stringify(value),'root_template_field_changed:'+key);
  if(!existsSync(values.RECOVERY_ENTRY)){requireValue(!readOnly,'original_plain_entry_missing_custody');wxJson(values.RECOVERY_ENTRY,e);}
  else requireValue(JSON.stringify(JSON.parse(readFileSync(values.RECOVERY_ENTRY,'utf8')))===JSON.stringify(e),'existing_plain_entry_changed');
  return {...c,bindings:values} as AttemptContext;
}
