/** The already reviewed common history transform, isolated to this asset caller. */
import {readFileSync} from 'node:fs';import {resolve,dirname,join,isAbsolute} from 'node:path';
import {pathToFileURL} from 'node:url';
import {verifyPin,demand} from './manifest.ts';import {nonblockingHistorySource} from './nonblocking-history-source.ts';
export async function ownedPolicyRuntime(runtimePin:any){
 verifyPin(runtimePin);demand(resolve(runtimePin.path)===resolve(join(import.meta.dir,'runtime.ts')),'original_common_runtime_pin_required');
 const namespace='owned-policy-history-'+runtimePin.sha256.slice(0,16),specifier=namespace+':runtime';
 Bun.plugin({name:namespace,setup(build){
  build.onResolve({filter:/./,namespace},args=>{if(args.path==='runtime')return{path:runtimePin.path,namespace};if(args.path.startsWith('node:'))return;return{path:isAbsolute(args.path)?args.path:resolve(dirname(runtimePin.path),args.path),namespace:'file'}});
  build.onLoad({filter:/./,namespace},()=>{verifyPin(runtimePin);const text=nonblockingHistorySource(runtimePin.path,readFileSync(runtimePin.path,'utf8'),import.meta.dir).replace(/from\s+(['"])([^'"\r\n]+)\1/g,(whole,quote,specifier)=>specifier.startsWith('.')||isAbsolute(specifier)?'from '+JSON.stringify(pathToFileURL(isAbsolute(specifier)?specifier:resolve(dirname(runtimePin.path),specifier)).href):whole);return{contents:text,loader:'ts',resolveDir:dirname(runtimePin.path)}});
 }});
 return await import(specifier);
}
