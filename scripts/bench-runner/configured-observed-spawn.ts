/** Explicit binding for original absolute launchers; configuration crosses the child boundary in argv. */
import{readFileSync}from'node:fs';import{resolve}from'node:path';
import{spawn as nativeSpawn}from'node:child_process';
import{configureObservedSpawn as configure,observedSpawn as observed}from'./observed-spawn.ts';
import{verifyPin,demand}from'./manifest.ts';
let pins:any[]=[];
export function configureObservedSpawn(directory:string,sourcePins:any[]){pins=sourcePins;configure(directory,sourcePins)}
export const observedSpawn:typeof nativeSpawn=((command:any,args:any,options:any)=>{
 const path=process.env.BENCH_MANIFEST_PATH;demand(path,'explicit_launcher_manifest_required');
 const m=JSON.parse(readFileSync(path!,'utf8')),d=m.adapterConfig.terminalDriver,s=d.qualifiedInterfaces.stand;
 demand(s.bootstrapBindingMode==='explicit-absolute-launcher-v1','explicit_absolute_launcher_binding_required');
 const check=(p:any)=>{verifyPin(p);demand(m.provenance.sourcePins.some((q:any)=>resolve(q.path)===resolve(p.path)&&q.sha256===p.sha256&&q.bytes===p.bytes),'explicit_launcher_pin_not_in_scope');return p.path};
 const python=check(s.pythonPin),entry=check(s.standEntryPin),bootstrap=check(s.pythonBootstrap.bootstrapPin),config=check(s.pythonBootstrap.configPin),activation=check(d.activationPin);
 demand(resolve(command)===resolve(python)&&args[0]==='-B'&&args[1]==='-X'&&args[2]==='utf8'&&resolve(args[3])===resolve(entry),'absolute_launcher_original_argv_required');
 const a=JSON.parse(readFileSync(activation,'utf8'));
 demand(process.env.NOVAEVE_ACTIVATION_PATH===activation&&process.env.DOCKER_HOST===a.dockerHost&&process.env.NOVAEVE_BROKER_CONTROL_PATH===a.brokerControlPath,'actual_parent_activation_binding_required');
 for(const k of ['NOVAEVE_RESOURCE_PARENT_PID','NOVAEVE_RESOURCE_LEASE_PID','NOVAEVE_RESOURCE_MEMORY_MB','NOVAEVE_RESOURCE_GROWTH_BYTES','NOVAEVE_RESOURCE_BENCH','NOVAEVE_RESOURCE_TOKEN','NOVAEVE_RESOURCE_SLOTS','NOVAEVE_ROOT_ONLY_DISPATCH'])demand(options.env[k]===process.env[k]&&typeof options.env[k]==='string','actual_parent_lease_binding_required:'+k);
 return observed(command,['-B','-X','utf8',bootstrap,'--config',config,'--original-script',entry,'--',...args.slice(4)],{...options,env:{...options.env,DOCKER_HOST:a.dockerHost,NOVAEVE_ACTIVATION_PATH:activation,NOVAEVE_BROKER_CONTROL_PATH:a.brokerControlPath}});
}) as typeof nativeSpawn;
