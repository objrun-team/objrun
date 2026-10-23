/** Reuse the real formal launcher source transformation, observation and child boundary. */
import{readFileSync}from'node:fs';import{dirname,join}from'node:path';import{pathToFileURL}from'node:url';
import{legacyLauncherSource}from'./qualified-source-mappings.ts';import{verifyPin,demand}from'./manifest.ts';
export async function formalNeutralStand(p:any,planPath:string,out:string,actualDeadline:number){
 const s=p.formalParent.stand;for(const q of[s.launcherPin,s.observedSpawnPin,s.pythonBootstrap.bootstrapPin,s.pythonBootstrap.configPin,s.standEntryPin])verifyPin(q);
 const observer=await import(pathToFileURL(s.observedSpawnPin.path).href);observer.configureObservedSpawn(join(out,'formal-launcher-process'),p.sourcePins);
 const transformed=(s.bootstrapBindingMode==='explicit-absolute-launcher-v1'?readFileSync(s.launcherPin.path,'utf8'):legacyLauncherSource(readFileSync(s.launcherPin.path,'utf8'),s)).replace('import { spawn } from "node:child_process";','import { observedSpawn as spawn } from '+JSON.stringify(s.observedSpawnPin.path.replaceAll('\\','/'))+';');
 const exact=new RegExp('^'+s.launcherPin.path.replaceAll('\\','/').split('/').map((x:string)=>x.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('[/\\\\]')+'$');
 Bun.plugin({name:'neutral-actual-formal-launcher',setup(build){build.onLoad({filter:exact},()=>({contents:transformed,loader:'ts',resolveDir:dirname(s.launcherPin.path)}))}});
 const launcher=await import(pathToFileURL(s.launcherPin.path).href);
 const stand=await launcher.startStand({output:join(out,'stand-process'),script:s.standEntryPin.path,baseProof:planPath,token:crypto.randomUUID()+crypto.randomUUID()});
 let error:any;try{const result=await stand.call('/up',{},Math.max(1,actualDeadline-Date.now()));demand(result.complete===true,'neutral_formal_up_failed')}catch(e){error=e}finally{await stand.close()}
 if(error)throw error;
}
