/** Thin explicit ABI for the independent native D descriptor. No implicit IO/run. */
import { actualPin, demand, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

export const JPG_D_STORAGE_PROTOCOL = 'jpg-owned-D-evidence-storage-v1';
export const JPG_D_PARENT = 'D:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/skillsbench-jpg-small-batch';
export type JpgDDescriptor = {
  protocol: typeof JPG_D_STORAGE_PROTOCOL; ownerNonce: string; storeLogical: string; storePhysical: string;
  directories: Record<string, string>; stageMapping: Record<string, string>; nativeEnvironment: Record<string, string>;
  nativePythonArguments: string[]; profileSourcePin: Pin; storeMaximumAllocatedBytes: number; DMinimumFreeBytes: number;
  FMinimumFreeBytes: number; CMinimumFreeBytes: number; FPointerMaximumAllocatedBytes: number;
  solverUpperMaximumBytes: number; privateSharedRamMaximumBytes: number; dockerMetadataReserveBytes: number;
  FStopBufferBytes: number; FPointerDirectory: string; namespaceReady: false; actualDIdentityValidated: false;
  actualDockerTmpfsValidated: false; paidReady: false;
  DockerMutations: 0; modelCalls: 0; scope: string;
};
const DIRS=['raw','sqlite','journal','cash','source','taskmeta','private-logs','stand','captures','tmp','python-cache','bun-cache','leases','audit'];
const STAGES:Record<string,string>={provider:'raw',engine_db:'sqlite',journal:'journal',cash:'cash',frozen_source_zip:'source',task_metadata:'taskmeta',private_grade:'private-logs',stand:'stand',capture:'captures',host_temp:'tmp',python_bytecode:'python-cache',bun_cache:'bun-cache',native_owner_lease:'leases',closing_audit:'audit'};
/** Input must be a durable native-produced descriptor and separately reviewed native source Pin. */
export function loadJpgDDescriptor(profilePin:Pin,nativeSourcePin:Pin):JpgDDescriptor {
  verifyPin(profilePin);verifyPin(nativeSourcePin);
  const d=JSON.parse(readFileSync(profilePin.path,'utf8')) as JpgDDescriptor;
  demand(d.protocol===JPG_D_STORAGE_PROTOCOL&&/^[0-9a-f]{32}$/.test(d.ownerNonce),'jpg_D_profile_nonce');
  const root=JPG_D_PARENT+'/'+d.ownerNonce;
  demand(d.storeLogical===root&&d.storePhysical===root,'jpg_D_physical_root');
  demand(d.profileSourcePin.path===nativeSourcePin.path&&d.profileSourcePin.sha256===nativeSourcePin.sha256&&d.profileSourcePin.bytes===nativeSourcePin.bytes,'jpg_D_actual_native_source');
  demand(DIRS.length===Object.keys(d.directories).length&&DIRS.every(k=>d.directories[k]===root+'/'+k),'jpg_D_directories');
  demand(Object.keys(STAGES).length===Object.keys(d.stageMapping).length&&Object.entries(STAGES).every(([k,v])=>d.stageMapping[k]===root+'/'+v),'jpg_D_stage_mapping');
  demand(d.storeMaximumAllocatedBytes===3*1024**3&&d.DMinimumFreeBytes===3*1024**3&&d.FMinimumFreeBytes===1024**3&&d.CMinimumFreeBytes===1024**3&&d.FPointerMaximumAllocatedBytes===1024**2&&d.solverUpperMaximumBytes===256*1024**2&&d.privateSharedRamMaximumBytes===512*1024**2&&d.dockerMetadataReserveBytes===16*1024**2&&d.FStopBufferBytes===8*1024**2,'jpg_D_caps');
  demand(resolve(d.FPointerDirectory)===resolve(import.meta.dir,'../../docs/repair-2026-10-08/jpg-D-store-pointers',d.ownerNonce),'jpg_D_pointer_scope');
  const env={TEMP:root+'/tmp',TMP:root+'/tmp',TMPDIR:root+'/tmp',PYTHONDONTWRITEBYTECODE:'1',PYTHONPYCACHEPREFIX:root+'/python-cache',BUN_RUNTIME_TRANSPILER_CACHE_PATH:root+'/bun-cache/transpiler',BUN_INSTALL_CACHE_DIR:root+'/bun-cache/install',XDG_CACHE_HOME:root+'/bun-cache'};
  demand(Object.keys(env).length===Object.keys(d.nativeEnvironment).length&&Object.entries(env).every(([k,v])=>d.nativeEnvironment[k]===v),'jpg_D_native_cache_environment');
  demand(JSON.stringify(d.nativePythonArguments)===JSON.stringify(['-B','-X','utf8'])&&d.namespaceReady===false&&d.actualDIdentityValidated===false&&d.actualDockerTmpfsValidated===false&&d.paidReady===false,'jpg_D_prepared_only');
  demand(d.DockerMutations===0&&d.modelCalls===0&&d.scope==='Only new one-task JPG small-batch evidence; originals/static C depots/source/cache not moved','jpg_D_prepare_claims');
  Object.freeze(d.directories);Object.freeze(d.stageMapping);Object.freeze(d.nativeEnvironment);Object.freeze(d.nativePythonArguments);Object.freeze(d.profileSourcePin);return Object.freeze(d);
}
/** Only the caller's new owned host child gets these values; never mutate global process.env. */
export function jpgDNativeEnvironment(d:JpgDDescriptor,existing:NodeJS.ProcessEnv){return{...existing,...d.nativeEnvironment};}
export function jpgDStagePath(d:JpgDDescriptor,stage:string,relative:string){
  demand(Object.hasOwn(STAGES,stage)&&typeof relative==='string'&&relative.length>0&&!/[\\:\x00-\x1f\x7f]/.test(relative)&&Buffer.byteLength(relative)<=240,'jpg_D_stage_path');
  demand(relative.split('/').every(p=>p!==''&&p!=='.'&&p!=='..'&&!/[ .]$/.test(p)&&!/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$/i.test(p)),'jpg_D_stage_path');
  return d.stageMapping[stage]+'/'+relative;
}
/** F only stores bounded Pins/closing references; no task trace/raw/SQLite goes into pointers. */
export function jpgDPointerPayload(d:JpgDDescriptor,phase:string,pins:Pin[]){
  demand(/^[a-z0-9-]{1,48}$/.test(phase)&&pins.length<=32,'jpg_D_pointer_scope');for(const p of pins)verifyPin(p);
  const record={protocol:'jpg-D-evidence-pointer-v1',ownerNonce:d.ownerNonce,storeLogical:d.storeLogical,storePhysical:d.storePhysical,phase,pins,profileSourcePin:d.profileSourcePin,paidReady:false};
  demand(Buffer.byteLength(JSON.stringify(record))<=16384,'jpg_D_pointer_bound');return record;
}
export function jpgDModulePin(){return actualPin(import.meta.path);}
