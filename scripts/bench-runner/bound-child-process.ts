/** Explicit Bun -> Python boundary; no global subprocess/module monkeypatch. */
import{spawn as nativeSpawn,spawnSync as nativeSpawnSync}from'node:child_process';
import{readFileSync}from'node:fs';import{resolve,join}from'node:path';
import{pin,verifyPin,demand}from'./manifest.ts';
function bound(executable:string,args:string[],options:any){
 const env=options?.env??process.env,path=env.NOVAEVE_PYTHON_MAPPING_CONFIG;
 demand(path&&pin(path).sha256===env.NOVAEVE_PYTHON_MAPPING_SHA256,'explicit_child_mapping_required');
 const c=JSON.parse(readFileSync(path,'utf8'));verifyPin(c.pythonExecutablePin);verifyPin(c.bootstrapPin);
 demand(resolve(executable)===resolve(c.pythonExecutablePin.path),'explicit_bound_python_executable');
 const rest=[...args],flags:string[]=[];while(['-B','-u'].includes(rest[0]))flags.push(rest.shift()!);
 const entry=rest.shift();demand(entry,'explicit_child_entry_required');const candidates=[c.originalStandPin,...(c.allowedEntryPins??[])].filter((p:any)=>resolve(p.path)===resolve(entry));
 demand(candidates.length===1,'child_entry_not_approved');verifyPin(candidates[0]);
 return {executable,args:[...flags,c.bootstrapPin.path,'--config',path,'--original-script',entry,'--',...rest]};
}
export const spawn:typeof nativeSpawn=((executable:any,args:any,options:any)=>{const a=bound(executable,args,options);return nativeSpawn(a.executable,a.args,options)})as typeof nativeSpawn;
export const spawnSync:typeof nativeSpawnSync=((executable:any,args:any,options:any)=>{const a=bound(executable,args,options);return nativeSpawnSync(a.executable,a.args,options)})as typeof nativeSpawnSync;
