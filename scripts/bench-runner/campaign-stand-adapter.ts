/** One reviewed Stand-path injection into an immutable qualified campaign. */
import {readFileSync,existsSync,readdirSync} from 'node:fs';
import {dirname,resolve,join} from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import type {Pin,TaskManifest} from './types.ts';
import {checkPin} from './runtime.ts';
export interface StandInjection {
  protocol:'bench-qualified-stand-injection-v1';campaignPin:Pin;expectedExpression:string;
  standEntryPin:Pin;launcherPin:Pin;pythonPin:Pin;dependencyPins:Pin[];
  pythonModules:Record<string,Pin>;standardLibraryModules:string[];
  observedSpawnPin:Pin;launcherSpawnImport:string;
  dependencyManifestPins:Pin[];
  pythonPackages:Record<string,{directory:string;pins:Pin[]}>;
}
const digest=(s:string)=>createHash('sha256').update(s).digest('hex');
function requireTrue(x:unknown,message:string):asserts x {if(!x)throw Error(message);}
export function prepareStandInjection(m:TaskManifest,s:StandInjection) {
  requireTrue(s?.protocol==='bench-qualified-stand-injection-v1','stand_injection_protocol');
  const pins=[s.campaignPin,s.standEntryPin,s.launcherPin,s.pythonPin,s.observedSpawnPin,...s.dependencyPins,...s.dependencyManifestPins,...Object.values(s.pythonModules)];
  for(const pkg of Object.values(s.pythonPackages)){
    const actual:string[]=[];const walk=(dir:string)=>{for(const e of readdirSync(dir,{withFileTypes:true})){const p=join(dir,e.name);if(e.isDirectory()&&e.name!=='__pycache__')walk(p);else if(e.isFile()&&/\.(py|pyd|dll)$/.test(e.name))actual.push(resolve(p));}};walk(pkg.directory);
    requireTrue(actual.length>0&&actual.length===pkg.pins.length&&actual.every(p=>pkg.pins.some(x=>resolve(x.path)===p)),'python_package_complete_pin_inventory');pins.push(...pkg.pins);
  }
  for(const p of s.dependencyManifestPins){checkPin(p);const data=JSON.parse(readFileSync(p.path,'utf8'));requireTrue(Array.isArray(data.sourcePins)&&data.sourcePins.length>0,'qualified_dependency_manifest_empty');pins.push(...data.sourcePins);}
  for(const p of pins){checkPin(p);requireTrue(m.provenance.sourcePins.some(x=>x.path===p.path&&x.sha256===p.sha256&&x.bytes===p.bytes),'stand_dependency_not_manifest_bound:'+p.path);}
  const source=readFileSync(s.campaignPin.path,'utf8');
  requireTrue(/^script:join\(import\.meta\.dir,"[^"\r\n]+\.py"\)$/.test(s.expectedExpression),'only_reviewed_stand_expression_permitted');
  requireTrue(source.split(s.expectedExpression).length===2,'stand_expression_must_match_exactly_once');
  const launcher=readFileSync(s.launcherPin.path,'utf8');
  requireTrue(source.includes(JSON.stringify(s.launcherPin.path.replaceAll('\\','/')))&&launcher.includes(JSON.stringify(s.pythonPin.path.replaceAll('\\','/'))),'actual_launcher_python_binding');
  requireTrue(launcher.includes('options.script'),'launcher_script_parameter_missing');
  requireTrue(s.launcherSpawnImport==='import { spawn } from "node:child_process";'&&launcher.split(s.launcherSpawnImport).length===2,'only_unique_original_spawn_import_permitted');
  const launcherContents=launcher.replace(s.launcherSpawnImport,'import { observedSpawn as spawn } from '+JSON.stringify(s.observedSpawnPin.path.replaceAll('\\','/'))+';');
  const localPaths=new Set(Object.values(s.pythonModules).map(p=>resolve(p.path)));
  requireTrue(localPaths.has(resolve(s.standEntryPin.path)),'python_entry_not_in_dependency_graph');
  const imports=[] as {path:string;module:string}[];
  for(const p of Object.values(s.pythonModules)){
    const code=readFileSync(p.path,'utf8');
    const names=[...code.matchAll(/^\s*from\s+([A-Za-z_][\w.]*)\s+import\s/gm)].map(x=>x[1].split('.')[0]);
    for(const line of code.matchAll(/^\s*import\s+([^\r\n#]+)/gm))for(const item of line[1].split(','))names.push(item.trim().split(/\s+as\s+/)[0].split('.')[0]);
    for(const name of names){const local=join(dirname(p.path),name+'.py');if(existsSync(local))requireTrue(resolve(s.pythonModules[name]?.path??'')===resolve(local),'local_python_import_not_exact:'+name);requireTrue(s.pythonModules[name]||s.pythonPackages[name]||s.standardLibraryModules.includes(name),'unbound_python_import:'+name);imports.push({path:p.path,module:name});}
  }
  const contents=source.replace(s.expectedExpression,'script:options.standScriptPath');
  new Bun.Transpiler({loader:'ts'}).transformSync(contents);new Bun.Transpiler({loader:'ts'}).transformSync(launcherContents);
  return {contents,launcherContents,resolveDir:dirname(s.campaignPin.path),standScriptPath:s.standEntryPin.path,
    proof:{protocol:'bench-qualified-stand-injection-proof-v1',originalCampaignPin:s.campaignPin,standEntryPin:s.standEntryPin,launcherPin:s.launcherPin,pythonPin:s.pythonPin,
      dependencyPins:pins,imports,originalSourceSha256:digest(source),injectedSourceSha256:digest(contents),launcherSourceSha256:digest(launcher),observedLauncherSourceSha256:digest(launcherContents),replacement:{from:s.expectedExpression,to:'script:options.standScriptPath',count:1},launcherReplacement:{from:s.launcherSpawnImport,to:'pinned observedSpawn import',count:1},originalSourceUnchanged:true}};
}
/** Same prepared object is used in preflight and execution; no source file is rewritten. */
export async function installStandInjection(s:StandInjection,prepared:ReturnType<typeof prepareStandInjection>,custodyDirectory:string) {
  const exact=resolve(s.campaignPin.path),launcher=resolve(s.launcherPin.path);checkPin(s.observedSpawnPin);
  const observer=await import(pathToFileURL(s.observedSpawnPin.path).href);observer.configureObservedSpawn(custodyDirectory,prepared.proof.dependencyPins);
  const exactFilter=(path:string)=>new RegExp('^'+path.replaceAll('\\','/').split('/').map(part=>part.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('[/\\\\]')+'$');
  Bun.plugin({name:'qualified-stand-injection-'+prepared.proof.injectedSourceSha256,setup(build){
    build.onLoad({filter:exactFilter(exact)},args=>{requireTrue(resolve(args.path)===exact,'campaign_exact_module_identity');checkPin(s.campaignPin);return {contents:prepared.contents,loader:'ts',resolveDir:prepared.resolveDir};});
    build.onLoad({filter:exactFilter(launcher)},args=>{requireTrue(resolve(args.path)===launcher,'launcher_exact_module_identity');checkPin(s.launcherPin);return {contents:prepared.launcherContents,loader:'ts',resolveDir:dirname(s.launcherPin.path)};});
  }});
}
