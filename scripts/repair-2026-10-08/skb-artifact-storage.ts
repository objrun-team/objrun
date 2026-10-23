/** New ten-task geometry. Frozen one-task JPG geometry is never relabelled. */
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { actualPin, demand, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { SKB_ARTIFACT_SELECTION_SHA } from './skb-artifact-journal-contract.ts';

export const SKB_ARTIFACT_D_PARENT='D:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/skillsbench-ten-small-batch';
export type SkbStorageDescriptor={protocol:'skb-ten-owned-D-evidence-storage-v1';ownerNonce:string;storeLogical:string;storePhysical:string;directories:Record<string,string>;stageMapping:Record<string,string>;nativeEnvironment:Record<string,string>;nativePythonArguments:string[];profileSourcePin:Pin;selectionManifestPin:Pin;storeMaximumAllocatedBytes:number;DMinimumFreeBytes:number;FMinimumFreeBytes:number;CMinimumFreeBytes:number;FPointerMaximumAllocatedBytes:number;solverUpperMaximumBytes:number;privateSharedRamMaximumBytes:number;dockerMetadataReserveBytes:number;FStopBufferBytes:number;FPointerDirectory:string;scope:string;namespaceReady:false;actualDIdentityValidated:false;actualDockerTmpfsValidated:false;paidReady:false;DockerMutations:0;modelCalls:0};
const DIRS=['raw','sqlite','journal','cash','source','taskmeta','private-logs','stand','captures','tmp','python-cache','bun-cache','leases','audit'];
const STAGES:Record<string,string>={provider:'raw',engine_db:'sqlite',journal:'journal',cash:'cash',frozen_source_zip:'source',task_metadata:'taskmeta',private_grade:'private-logs',stand:'stand',capture:'captures',host_temp:'tmp',python_bytecode:'python-cache',bun_cache:'bun-cache',native_owner_lease:'leases',closing_audit:'audit'};
const samePin=(a:Pin,b:Pin)=>resolve(a.path)===resolve(b.path)&&a.bytes===b.bytes&&a.sha256===b.sha256;
export function loadSkbStorageDescriptor(descriptorPin:Pin,storageSourcePin:Pin):SkbStorageDescriptor{
  verifyPin(descriptorPin);verifyPin(storageSourcePin);demand(resolve(storageSourcePin.path)===join(import.meta.dir,'skb_artifact_storage.py'),'skb_new_storage_source_role');
  const d=JSON.parse(readFileSync(descriptorPin.path,'utf8')) as SkbStorageDescriptor,root=SKB_ARTIFACT_D_PARENT+'/'+d.ownerNonce;
  demand(d.protocol==='skb-ten-owned-D-evidence-storage-v1'&&/^[a-f0-9]{32}$/.test(d.ownerNonce)&&d.storeLogical===root&&d.storePhysical===root,'skb_new_storage_owner_scope');
  demand(samePin(d.profileSourcePin,storageSourcePin)&&d.selectionManifestPin.sha256===SKB_ARTIFACT_SELECTION_SHA,'skb_storage_source_selection');verifyPin(d.selectionManifestPin);
  demand(DIRS.length===Object.keys(d.directories).length&&DIRS.every(k=>d.directories[k]===root+'/'+k)&&Object.keys(STAGES).length===Object.keys(d.stageMapping).length&&Object.entries(STAGES).every(([k,v])=>d.stageMapping[k]===root+'/'+v),'skb_storage_stage_geometry');
  const env={TEMP:root+'/tmp',TMP:root+'/tmp',TMPDIR:root+'/tmp',PYTHONDONTWRITEBYTECODE:'1',PYTHONPYCACHEPREFIX:root+'/python-cache',BUN_RUNTIME_TRANSPILER_CACHE_PATH:root+'/bun-cache/transpiler',BUN_INSTALL_CACHE_DIR:root+'/bun-cache/install',XDG_CACHE_HOME:root+'/bun-cache'};
  demand(Object.keys(env).length===Object.keys(d.nativeEnvironment).length&&Object.entries(env).every(([k,v])=>d.nativeEnvironment[k]===v)&&JSON.stringify(d.nativePythonArguments)===JSON.stringify(['-B','-X','utf8']),'skb_native_cache_namespace');
  demand(d.storeMaximumAllocatedBytes===3*1024**3&&d.DMinimumFreeBytes===3*1024**3&&d.FMinimumFreeBytes===1024**3&&d.CMinimumFreeBytes===1024**3&&d.FPointerMaximumAllocatedBytes===1024**2&&d.solverUpperMaximumBytes===10*1024**3&&d.privateSharedRamMaximumBytes===512*1024**2&&d.dockerMetadataReserveBytes===16*1024**2&&d.FStopBufferBytes===8*1024**2,'skb_physical_geometry_caps');
  demand(resolve(d.FPointerDirectory)===resolve(import.meta.dir,'../../docs/repair-2026-10-08/skb-ten-D-store-pointers',d.ownerNonce),'skb_F_pointer_scope');
  demand(d.scope==='Only fixed ten-distinct-task paired U/F SkillsBench evidence; physical geometry reused in a new explicit scope; originals not moved'&&d.namespaceReady===false&&d.actualDIdentityValidated===false&&d.actualDockerTmpfsValidated===false&&d.paidReady===false&&d.DockerMutations===0&&d.modelCalls===0,'skb_prepared_geometry_not_readiness');
  return Object.freeze(d);
}
export function skbArtifactNativeEnvironment(d:SkbStorageDescriptor,env:NodeJS.ProcessEnv){return{...env,...d.nativeEnvironment};}
export function skbArtifactResourceRequirements(d:SkbStorageDescriptor,input:{initial:boolean;solverActive:boolean;solverWritableBytes:number;solverWritableLimitBytes:number}){
  demand(typeof input.initial==='boolean'&&typeof input.solverActive==='boolean'&&Number.isSafeInteger(input.solverWritableBytes)&&input.solverWritableBytes>=0&&Number.isSafeInteger(input.solverWritableLimitBytes)&&input.solverWritableLimitBytes>0&&input.solverWritableLimitBytes<=d.solverUpperMaximumBytes&&input.solverWritableBytes<=input.solverWritableLimitBytes,'skb_task_specific_solver_reservation');
  const remaining=input.solverActive?input.solverWritableLimitBytes-input.solverWritableBytes:0;
  return{C:d.CMinimumFreeBytes,D:d.DMinimumFreeBytes+(input.initial?d.storeMaximumAllocatedBytes:0),F:d.FMinimumFreeBytes+d.FPointerMaximumAllocatedBytes+d.dockerMetadataReserveBytes+d.FStopBufferBytes+remaining,solverRemainingBytes:remaining,kernelQuotaCertified:false,creditForUnmeasuredVhdSlackBytes:0};
}
export function skbStorageModulePin(){return actualPin(import.meta.path);}
