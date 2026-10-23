/** Independent custody receipts; preserves the original launcher's spawn/call/close behavior. */
import {spawn as nativeSpawn} from 'node:child_process';
import {mkdirSync,openSync,writeSync,closeSync} from 'node:fs';
import {join} from 'node:path';
import {filePin,wxJson,processIdentity} from './runtime.ts';
import type {Pin} from './types.ts';
let scope:{directory:string;sourcePins:Pin[]}|undefined,ordinal=0;
export function configureObservedSpawn(directory:string,sourcePins:Pin[]) {if(scope)throw Error('observed_spawn_scope_already_configured');scope={directory,sourcePins};}
export const observedSpawn:typeof nativeSpawn=((command:any,args:any,options:any)=>{
  if(!scope)throw Error('observed_spawn_scope_required');
  if(process.platform==='win32'&&options?.env){
    const programData=process.env.ProgramData??process.env.PROGRAMDATA;
    if(!programData)throw Error('actual_windows_programdata_required');
    const existing=Object.keys(options.env).find(k=>k.toUpperCase()==='PROGRAMDATA');
    if(existing&&options.env[existing]!==programData)throw Error('windows_programdata_mismatch');
    options={...options,env:{...options.env,[existing??'ProgramData']:programData}};
  }
  const directory=join(scope.directory,String(++ordinal));mkdirSync(directory,{recursive:true});
  wxJson(join(directory,'intent.json'),{protocol:'bench-native-spawn-intent-v1',argv:[command,...args],sourcePins:scope.sourcePins,environmentNames:Object.keys(options?.env??{}).sort(),programData:options?.env?.ProgramData??options?.env?.PROGRAMDATA??null,stdio:options?.stdio,atUtc:new Date().toISOString()});
  let child:ReturnType<typeof nativeSpawn>;
  try {child=nativeSpawn(command,args,options);}catch(error){wxJson(join(directory,'spawn-threw.json'),{error:String(error),spawnObserved:false});throw error;}
  let identity:any=null,identityError:string|null=null;
  if(child.pid)try{identity=processIdentity(child.pid);}catch(error){identityError=String(error);}
  wxJson(join(directory,'spawn.json'),{pid:child.pid??null,identity,identityError,argv:[command,...args],atUtc:new Date().toISOString()});
  const paths=[join(directory,'stdout'),join(directory,'stderr')],fds=paths.map(p=>openSync(p,'wx')),counts=[0,0],truncated=[false,false];
  for(const [i,stream]of [child.stdout,child.stderr].entries())stream?.on('data',(chunk:Buffer)=>{
    const remaining=2*1024**2-counts[i],part=chunk.subarray(0,Math.max(0,remaining));if(part.length)writeSync(fds[i],part);counts[i]+=chunk.length;if(chunk.length>remaining)truncated[i]=true;
  });
  child.on('error',error=>wxJson(join(directory,'error.json'),{name:error.name,message:error.message,atUtc:new Date().toISOString()}));
  let exitObserved=false,exitCode:number|null=null,signal:string|null=null;
  child.on('exit',(code,why)=>{exitObserved=true;exitCode=code;signal=why;wxJson(join(directory,'exit.json'),{pid:child.pid??null,identity,exitObserved,exitCode,signal,atUtc:new Date().toISOString()});});
  child.on('close',(code,why)=>{fds.forEach(closeSync);wxJson(join(directory,'close.json'),{protocol:'bench-native-observed-close-v1',pid:child.pid??null,identity,exitObserved,exitCode,signal,closeObserved:true,closeCode:code,closeSignal:why,stdout:filePin(paths[0]),stderr:filePin(paths[1]),bytes:counts,truncated,atUtc:new Date().toISOString()});});
  return child;
}) as typeof nativeSpawn;
