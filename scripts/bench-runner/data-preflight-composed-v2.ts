/** Additive read-only joins. Accepted consumer validators remain the authority. */
import {readFileSync,realpathSync} from 'node:fs';
import {resolve,join} from 'node:path';import {pathToFileURL} from 'node:url';
import {verifyPin,pin,demand} from './manifest.ts';import type {Pin} from './types.ts';
import type {DataPreflightRequest} from './data-preflight.ts';
const home=resolve(import.meta.dir,'../../docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/coordinator/universal-runner');
const tbHelper:Pin={path:join(home,'parallel-owners-20261015/tb_git/readonly-tb-relative-preflight-v1/data-preflight-tb-relative.ts'),bytes:13732,sha256:'bc7341bd7e2bf9486aae9e96ea4863aa6020531182a6379d0d55f6de7008f412'};
const catalogHelper:Pin={path:join(home,'parallel-owners-20261015/sb_python_kernel/public-patches/original-catalog-join-v1/original-catalog-join.ts'),bytes:4869,sha256:'5e41a37d10df6535ac183c4db3c5871045833515191f5480b6dba65a249f6c88'};
const json=(p:Pin)=>{verifyPin(p);return JSON.parse(readFileSync(p.path,'utf8').replace(/^\uFEFF/,''))};
function canonical(value:any):string {if(Array.isArray(value))return'['+value.map(canonical).join(',')+']';if(value&&typeof value==='object')return'{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';return JSON.stringify(value);}
/** owned_native_stage.checked() compares the whole Python dictionary, not normalized identities. */
export function validateNativeCheckedPin(p:Pin){
 verifyPin(p);const actual=pin(realpathSync(p.path));
 demand(canonical(actual)===canonical(p),'native_stage_pin_changed');return actual;
}
export function validateNativeStageData(job:any,mapping:any){
 demand(job?.protocol==='bench-pinned-native-stage-v1'&&job.modelCalls===0,'native_stage_protocol_and_zero_model');
 for(const p of[job.mappingPin,job.entryPin,...(job.inputPins??[])])validateNativeCheckedPin(p);
 // Exact original line 40: entryMappings transform bytes but do not grant execution authority.
 demand([mapping.originalStandPin,...(mapping.allowedEntryPins??[])].some((p:any)=>canonical(p)===canonical(job.entryPin)),'native_stage_entry_not_in_original_allowlist');
 for(const item of job.inputFiles??[]){validateNativeCheckedPin(item.pin);demand(typeof item.relative==='string'&&item.relative.length>0&&!item.relative.startsWith('/')&&!item.relative.split('/').includes('..'),'native_stage_input_relative_escape');const jail=resolve('preflight-placeholder','inputs'),target=resolve(jail,item.relative);demand(target.startsWith(jail+'\\')||target.startsWith(jail+'/'),'native_stage_input_relative_escape');}
 return{passed:true,originalWholeDictionaryEquality:true,selectedEntryInOriginalAllowlist:true,entryMappingsAreNotExecutionAuthority:true,inputPins:(job.inputPins??[]).length,inputFiles:(job.inputFiles??[]).length};
}
export async function validateOriginalCatalogData(input:any,manifest:any){verifyPin(catalogHelper);const module=await import(pathToFileURL(catalogHelper.path).href);return module.validateOriginalCatalogJoin(input,manifest);}
export interface ComposedDataPreflightRequest extends Omit<DataPreflightRequest,'protocol'>{protocol:'bench-readonly-data-preflight-v2';nativeStageRequestPins?:Pin[]}
export async function preflightData(r:ComposedDataPreflightRequest){
 demand(r.protocol==='bench-readonly-data-preflight-v2','composed_data_preflight_protocol');verifyPin(tbHelper);verifyPin(catalogHelper);
 const base=await import(pathToFileURL(tbHelper.path).href),m=json(r.manifestPin);let nativeStage:any;
 if(r.ownedOperationPlanPin){const e=json(r.ownedOperationPlanPin),p=e.plan;if(p?.stageRequestPin){validateNativeCheckedPin(p.stageRequestPin);const job=json(p.stageRequestPin);if(job.protocol==='bench-pinned-native-stage-v1'){demand(job.taskId===p.policyTaskId&&job.bench===p.resource?.bench&&canonical(job.resource)===canonical(p.resource),'native_stage_original_plan_join');nativeStage=validateNativeStageData(job,json(job.mappingPin));}}}
 const additionalNativeStages=[];for(const p of r.nativeStageRequestPins??[]){validateNativeCheckedPin(p);const job=json(p);additionalNativeStages.push({stageRequestPin:p,...validateNativeStageData(job,json(job.mappingPin))});}
 const result=await base.preflightData({...r,protocol:'bench-readonly-data-preflight-v1'});let originalCatalog:any;
 const sb=m.adapterConfig?.skillsbenchSingleTask;
 if(sb){const route=json(sb.configPin),input=r.skillsbenchConsumerInputPin?json(r.skillsbenchConsumerInputPin):route;if(input.runtimePin){demand(input.skillCatalogPin,'original_catalog_source_membership');originalCatalog=await validateOriginalCatalogData(input,m);}}
 verifyPin(r.manifestPin);verifyPin(r.sourceConfigPin);verifyPin(tbHelper);verifyPin(catalogHelper);
 return{...result,protocol:'bench-readonly-data-preflight-result-v2',nativeStage:nativeStage??null,additionalNativeStages,originalCatalog:originalCatalog??null,delegatedAcceptedHelperPins:[tbHelper,catalogHelper],queueWrites:0,resourceAcquires:0,laneClaims:0,models:0,stageExecutions:0,signatureOrDataRewrites:0};
}
