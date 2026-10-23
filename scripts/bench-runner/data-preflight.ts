/** Read-only metadata checks before Runner.plan/reserve. Never signs, repairs or executes a stage. */
import {readFileSync,realpathSync} from 'node:fs';
import {resolve,isAbsolute} from 'node:path';
import {pathToFileURL} from 'node:url';
import {verify} from 'node:crypto';
import {pin,verifyPin,demand,validateManifest} from './manifest.ts';
import type {Pin,TaskManifest} from './types.ts';
import {BENCH_CODES} from '../repair-2026-10-10/full-f/shared/shared-admission.ts';

const json=(p:Pin)=>{verifyPin(p);return JSON.parse(readFileSync(p.path,'utf8').replace(/^\uFEFF/,''))};
const identity=(p:Pin)=>{const path=resolve(p.path).replaceAll('\\','/');return process.platform==='win32'?path.toLowerCase():path;};
/** For NEW unsigned data only. Does not mutate any caller or existing signed pin. */
export function canonicalFilePin(path:string):Pin {return pin(realpathSync(path));}
export const sameFilePin=(a:Pin,b:Pin)=>!!a&&!!b&&identity(a)===identity(b)&&a.bytes===b.bytes&&a.sha256===b.sha256;
export function validateSupplierRunId(runId:string,activation:any,bench:string){
 demand(Object.hasOwn(BENCH_CODES,bench)&&typeof runId==='string'&&runId.startsWith(activation.runId+'-'+BENCH_CODES[bench]+'-')&&/^repair-[0-9TZ-]+$/.test(runId),'invalid_bench_run_id');
}
const member=(pins:Pin[],p:Pin)=>pins.some(q=>sameFilePin(p,q));
function uniquePins(pins:Pin[],label:string){
 const seen=new Map<string,Pin>();for(const p of pins){verifyPin(p);const key=identity(p),old=seen.get(key);demand(!old||sameFilePin(old,p),label+':conflicting_pin');seen.set(key,p);}
}
function validateSourceConfig(p:Pin){
 const e=json(p),c=e.config;demand(e.protocol==='bench-signed-financial-source-config-v1'&&c,'signed_source_config_protocol');
 verifyPin(c.authorityPublicPin);demand(c.authorityPublicPin.sha256==='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98'&&verify(null,Buffer.from(JSON.stringify(c)),readFileSync(c.authorityPublicPin.path),Buffer.from(e.signature,'base64')),'signed_source_config_signature');return c;
}
/** This is the pre-execute contract guard in adapters/index.ts, not just validateFor(). */
export function validateDriverContractBinding(m:TaskManifest){
 const c=m.adapterConfig.driverContract as any;
 demand(c?.ownedLease===true&&c.beforeJournal===true&&c.beforeForward===true&&c.originalBudget===true,'qualified_deep_driver_contract_required');
 demand(c.pin&&m.provenance.contractPins.some(p=>p.sha256===c.pin.sha256&&resolve(p.path)===resolve(c.pin.path)),'driver_contract_pin_required');verifyPin(c.pin);
}
/** Mirrors python_child_entry.py before import/guard/lease, including sequential replacement anchors. */
export function validatePythonMappingData(c:any,selectedEntry?:Pin){
 demand(c?.protocol==='bench-qualified-python-source-mapping-v1','python_mapping_protocol');
 const approved=[c.originalStandPin,...(c.allowedEntryPins??[])];const paths=new Set<string>();
 for(const p of approved){verifyPin(p);demand(!paths.has(identity(p)),'child_entry_not_approved:duplicate_entry');paths.add(identity(p));}
 if(selectedEntry){verifyPin(selectedEntry);demand(approved.filter(p=>identity(p)===identity(selectedEntry)).length===1,'child_entry_not_approved');}
 verifyPin(c.guardPin);const names=new Set<string>(),entryMappings=new Set<string>();
 for(const m of c.entryMappings??[]){verifyPin(m.pin);demand(!entryMappings.has(identity(m.pin)),'duplicate_python_entry_mapping');entryMappings.add(identity(m.pin));}
 for(const m of [...(c.modules??[]),...(c.entryMappings??[])]){
  verifyPin(m.pin);if(m.name){demand(!names.has(m.name),'duplicate_python_module_name');names.add(m.name);}
  let code=readFileSync(m.pin.path,'utf8');for(const change of m.exactReplacements??[]){demand(typeof change.from==='string'&&change.from.length>=9&&code.split(change.from).length===2,'child_mapping_anchor_not_unique');code=code.replace(change.from,change.to);}
  for(const kind of Object.values(m.guardAliases??{}))demand(['actual-adopted-control','actual-owned-lease'].includes(kind as string),'unknown_guard_alias_kind');
  if(c.requireHistoryPolicy)demand(!code.includes('paid_preserve_no_retry'),'obsolete_unpaid_predicate_forbidden');
 }
 if(c.requireHistoryPolicy){demand(c.historyPolicy,'python_history_policy_required');for(const p of [c.historyPolicy.manifestPin,c.historyPolicy.verifierPin,c.historyPolicy.bunPin])verifyPin(p);}
 return {approvedEntries:approved.length,modules:(c.modules??[]).length,historyRequired:c.requireHistoryPolicy===true};
}
/** configured-observed-spawn.ts checks these exact executables/data against source scope. */
export function validateLauncherScope(m:TaskManifest,stand:any,activationPin?:Pin){
 const required=[stand.pythonPin,stand.standEntryPin,stand.pythonBootstrap?.bootstrapPin,stand.pythonBootstrap?.configPin,...(activationPin?[activationPin]:[])];
 for(const p of required){demand(p,'explicit_launcher_pin_required');verifyPin(p);demand(member(m.provenance.sourcePins,p),'explicit_launcher_pin_not_in_scope:'+p.path);}
}
export function validateCarrierFinancialJoin(carrier:any,expected:Pin){
 const actual=carrier.adapterConfig?.financialSourceConfigPin;demand(actual&&sameFilePin(actual,expected),'carrier_financial_source_config_join');
 const c=validateSourceConfig(actual);demand(c?.providerProbeHumanAuthorityPin&&c.providerProbeOnly===true,'carrier_explicit_child_loader_config_required');
 demand(member([...(carrier.provenance?.sourcePins??[]),...(carrier.provenance?.contractPins??[])],actual),'carrier_financial_config_not_in_scope');
}
export interface DataPreflightRequest {
 protocol:'bench-readonly-data-preflight-v1';manifestPin:Pin;sourceConfigPin:Pin;
 selectedStage?:string;expectedChildFinancialSourceConfigPin?:Pin;
 pythonMappingPins?:Pin[];skillsbenchConsumerInputPin?:Pin;ownedOperationPlanPin?:Pin;
}
export async function preflightData(r:DataPreflightRequest){
 demand(r.protocol==='bench-readonly-data-preflight-v1','data_preflight_protocol');verifyPin(r.manifestPin);validateSourceConfig(r.sourceConfigPin);
 const m=json(r.manifestPin) as TaskManifest;
 const runnerManifest=m.schemaVersion===1;
 if(runnerManifest)validateManifest(m);
 else{demand(r.ownedOperationPlanPin&&['skillsbench','terminal-bench'].includes(m.bench)&&typeof m.taskId==='string'&&isAbsolute(m.root),'owned_parent_requires_signed_plan');for(const p of [...m.provenance.sourcePins,...m.provenance.contractPins])verifyPin(p);}
 uniquePins(m.provenance.sourcePins,'source');uniquePins(m.provenance.contractPins,'contract');
 if(runnerManifest){const adapters=await import('./adapters/index.ts');adapters.getAdapter(m.bench).validate(m);}
 if(r.selectedStage)demand(Object.hasOwn(m.stages??{},r.selectedStage),'selected_stage_missing');
 if(Object.values(m.stages??{}).some(s=>s?.kind==='command'&&s.effect!=='read-only'))validateDriverContractBinding(m);
 const own=m.adapterConfig.financialSourceConfigPin as Pin|undefined;if(own)demand(sameFilePin(own,r.sourceConfigPin),'manifest_financial_source_config_join');
 const history=await import('./nonblocking-history-policy.ts');if(m.adapterConfig.nonblockingHistory)demand(history.historyAdmission(m),'manifest_history_admission_required');
 const mappings:Pin[]=[...(r.pythonMappingPins??[])];let originalReadinessValidated=false;
 if(r.ownedOperationPlanPin){
  const e=json(r.ownedOperationPlanPin),p=e.plan;demand(e.protocol==='bench-root-signed-infrastructure-acceptance-v1'&&p,'owned_plan_protocol');verifyPin(p.authorityPin);
  demand(p.authorityPin.sha256==='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98'&&verify(null,Buffer.from(JSON.stringify(p)),readFileSync(p.authorityPin.path),Buffer.from(e.signature,'base64')),'original_root_operation_signature');
  demand(sameFilePin(p.formalParent.manifestPin,r.manifestPin)&&p.modelCalls===0&&Date.parse(p.expiresAtUtc)>Date.now(),'exact_owned_operation_identity');uniquePins(p.sourcePins,'owned_source');
  const s=p.formalParent.stand;if(s?.pythonBootstrap?.configPin)mappings.push(s.pythonBootstrap.configPin);
  if(p.operationScope==='task-native-qualification'){
   const job=json(p.stageRequestPin);demand(p.noBenchContent===false&&p.taskQualificationOnly===true&&p.formalActivation===false&&p.noNewFeeAllocation===true&&p.actualModelAllocationUsd===0&&job.protocol==='bench-pinned-native-stage-v1'&&job.taskId===p.policyTaskId&&job.bench===p.resource.bench&&JSON.stringify(job.resource)===JSON.stringify(p.resource)&&p.overallTimeoutSeconds===job.originalStageTimeoutSeconds&&p.originalStageTimeoutSeconds===job.originalStageTimeoutSeconds&&Number.isSafeInteger(p.overallTimeoutSeconds)&&p.overallTimeoutSeconds>0&&p.overallTimeoutSeconds<=12000&&p.gradeCalls===job.authorizedGradeCalls&&p.referenceCalls===job.authorizedReferenceCalls,'exact_original_native_qualification_scope');verifyPin(job.originalStageContractPin);
   for(const q of [job.entryPin,job.mappingPin,job.pythonPin,job.bootstrapPin,...(job.inputPins??[])])verifyPin(q);
   validatePythonMappingData(json(job.mappingPin),job.entryPin);mappings.push(job.mappingPin);
  }
 }
 const sb=m.adapterConfig.skillsbenchSingleTask as any;
 if(sb){
  const routeInput=json(sb.configPin);demand(member([...m.provenance.sourcePins,...m.provenance.contractPins],sb.configPin),'single_task_config_actual_manifest_membership');
  const input=r.skillsbenchConsumerInputPin?json(r.skillsbenchConsumerInputPin):routeInput;
  if(input.runId&&input.activationPin)validateSupplierRunId(input.runId,json(input.activationPin),m.bench);
  const modelStage=Object.values(m.stages??{}).some(s=>s?.effect==='model');
  demand(input.runtimePin||!modelStage,'formal_original_consumer_input_pin_required');
  if(input.binding?.pythonBootstrap?.configPin)mappings.push(input.binding.pythonBootstrap.configPin);
  if(input.binding?.pythonPin)validateLauncherScope(m,input.binding,input.activationPin);
  if(input.runtimePin){verifyPin(input.runtimePin);demand(member(m.provenance.sourcePins,input.runtimePin),'single_task_runtime_not_in_scope');
   const runtime=await import(pathToFileURL(input.runtimePin.path).href);demand(typeof runtime.validateOriginalSingleTask==='function','original_readiness_validator_missing');
   await runtime.validateOriginalSingleTask({...input,sourcePins:m.provenance.sourcePins});originalReadinessValidated=true;}
 }
 const tb=m.adapterConfig.terminalDriver as any;
 if(tb&&m.bench==='terminal-bench'&&runnerManifest){
  const d=(await import('./terminal-driver.ts')).validateTerminalDriverData(m);
  if(tb.qualifiedInterfaces){(await import('./qualified-driver-interfaces.ts')).auditQualifiedInterfaceEvidence(m,d);const s=tb.qualifiedInterfaces.stand;if(s.bootstrapBindingMode==='explicit-absolute-launcher-v1')validateLauncherScope(m,s,tb.activationPin);if(s.pythonBootstrap?.configPin)mappings.push(s.pythonBootstrap.configPin);}
 }
 const seen=new Set<string>(),results=[];
 for(const p of mappings){if(seen.has(identity(p)))continue;seen.add(identity(p));const c=json(p);const result=validatePythonMappingData(c);if(c.requireHistoryPolicy){const carrier=json(c.historyPolicy.manifestPin);validateCarrierFinancialJoin(carrier,r.expectedChildFinancialSourceConfigPin??r.sourceConfigPin);demand(history.historyAdmission(carrier),'nested_carrier_authorization_required');demand(c.historyPolicy.taskKey===carrier.bench+':'+carrier.taskId,'child_policy_exact_task');}results.push({mappingPin:p,...result});}
 verifyPin(r.manifestPin);verifyPin(r.sourceConfigPin);
 return {protocol:'bench-readonly-data-preflight-result-v1',passed:true,manifestPin:r.manifestPin,sourceConfigPin:r.sourceConfigPin,taskId:m.taskId,bench:m.bench,originalReadinessValidated,pythonMappings:results,queueWrites:0,resourceAcquires:0,laneClaims:0,models:0,stageExecutions:0,signatureOrDataRewrites:0,scope:'static consumer data only; live capacity/provider/tool execution and post-plan signed entry remain separate gates'};
}
export async function main(args=process.argv.slice(2)){
 demand(args.length===1&&isAbsolute(args[0]),'absolute_preflight_request_required');const requestPin=pin(args[0]),r=json(requestPin);console.log(JSON.stringify(await preflightData(r)));
}
if(import.meta.main)await main();
