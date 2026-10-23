/** Content-addressed common release. Never rewrites qualified or earlier common source files. */
import {readFileSync,mkdirSync,writeFileSync,existsSync,renameSync,rmSync} from 'node:fs';
import {resolve,dirname,join} from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {pin} from './manifest.ts';
const root=resolve(import.meta.dir,'../..'),entry=join(import.meta.dir,'terminal-driver.ts');
export function preserveModuleLocations(source:string,path:string) {
  let output='',i=0;
  while(i<source.length){
    const start=i,c=source[i];
    if(c==='"'||c==="'"||c==='`'){
      i++;while(i<source.length){if(source[i]==='\\'){i+=2;continue;}if(source[i++]===c)break;}
      const quoted=source.slice(start,i);if(c==='`'&&/\$\{[^}]*import\.meta\./.test(quoted))throw Error('unsupported_template_module_location');output+=quoted;continue;
    }
    if(source.startsWith('//',i)){const end=source.indexOf('\n',i);i=end<0?source.length:end;output+=source.slice(start,i);continue;}
    if(source.startsWith('/*',i)){const end=source.indexOf('*/',i+2);if(end<0)throw Error('unterminated_source_comment');i=end+2;output+=source.slice(start,i);continue;}
    const hit=source.slice(i).match(/^import\.meta\.(dir|file|url)\b/);
    if(hit){output+=JSON.stringify(hit[1]==='dir'?dirname(path):hit[1]==='file'?path:pathToFileURL(path).href);i+=hit[0].length;continue;}
    output+=c;i++;
  }
  return output;
}
function once(source:string,from:string,to:string){if(source.split(from).length!==2)throw Error('release_anchor_not_unique:'+from);return source.replace(from,to);}
export function injectedDriverSource(source:string) {
  source='import {prepareStandInjection,installStandInjection,type StandInjection} from '+JSON.stringify(join(root,'scripts/bench-runner/campaign-stand-adapter.ts').replaceAll('\\','/'))+';\n'+source;
  source='export {prepareStandInjection,installStandInjection} from '+JSON.stringify(join(root,'scripts/bench-runner/campaign-stand-adapter.ts').replaceAll('\\','/'))+';\n'+source;
  source='import {inspectPreNativeHistory} from '+JSON.stringify(join(root,'scripts/bench-runner/pre-native-history.ts').replaceAll('\\','/'))+';\n'+source;
  source=once(source,'identity.attempts.length+retries.length===budget.cashClosePins?.length','identity.attempts.length+retries.length+((m.adapterConfig.preNativeRecoveryHistory??[]) as any[]).length===budget.cashClosePins?.length');
  source=once(source,"  demand(typeof closure.originalResultRecoveryFinding==='string'", "  const preNative=inspectPreNativeHistory(m,budget,seen);known+=preNative.knownUsd;unknown+=preNative.unknownUsd;calls+=preNative.calls;\n  demand(typeof closure.originalResultRecoveryFinding==='string'");
  source=once(source,"protocol:'bench-terminal-driver-v1';","protocol:'bench-terminal-driver-v1';standInjection:StandInjection;");
  source=once(source,'const api=await importsFor(d),ready=readPinned(d.readinessPin);',`if(d.standInjection.campaignPin.sha256!==d.imports.campaign.pin.sha256||d.standInjection.campaignPin.path!==d.imports.campaign.pin.path)throw Error('injected_campaign_must_equal_reviewed_import');
  const prepared=prepareStandInjection(m,d.standInjection);
  const proofPath=join(c.runDir,'stand-injection-proof.json');
  if(existsSync(proofPath)){if(JSON.stringify(JSON.parse(readFileSync(proofPath,'utf8')))!==JSON.stringify(prepared.proof))throw Error('injection_proof_changed');}
  else {wxJson(proofPath,prepared.proof);wxJson(join(c.runDir,'stand-injected-sources.json'),{campaign:prepared.contents,launcher:prepared.launcherContents});}
  await installStandInjection(d.standInjection,prepared,join(c.runDir,'native-spawn-custody'));
  const api=await importsFor(d),ready=readPinned(d.readinessPin);`);
  source=once(source,'recoveryBudgetProofPin:d.aggregateBudgetPin,hostCapacityGuard:guard,','standScriptPath:d.standInjection.standEntryPin.path,recoveryBudgetProofPin:d.aggregateBudgetPin,hostCapacityGuard:guard,');
  return source;
}
export async function buildRelease(outputRoot:string,kind:'terminal-driver'|'runner'='terminal-driver') {
  const inputs=new Map<string,ReturnType<typeof pin>>(),original=readFileSync(entry,'utf8'),transformed=injectedDriverSource(original);
  const entrypoint=kind==='runner'?join(import.meta.dir,'cli.ts'):entry;
  const result=await Bun.build({entrypoints:[entrypoint],target:'bun',format:'esm',minify:false,plugins:[{name:'common-release-inputs',setup(build){build.onLoad({filter:/\.ts$/},args=>{
    const path=resolve(args.path);inputs.set(path,pin(path));let contents=path===entry?transformed:readFileSync(path,'utf8');
    if(kind==='runner'&&path===entrypoint)contents='export {getAdapter} from "./adapters/index.ts";\n'+contents;
    // Preserve each module's original asset-relative location after bundling.
    contents=preserveModuleLocations(contents,path);
    return {contents,loader:'ts',resolveDir:dirname(path)};
  });}}]});
  if(!result.success)throw Error(result.logs.map(String).join('\n'));
  if(result.outputs.length!==1)throw Error('single_common_bundle_required');
  const bytes=Buffer.from(await result.outputs[0].arrayBuffer()),sha=createHash('sha256').update(bytes).digest('hex'),directory=join(resolve(outputRoot),sha);
  const path=join(directory,kind+'.js');if(!existsSync(directory)){mkdirSync(directory,{recursive:false});writeFileSync(path,bytes,{flag:'wx'});}else if(pin(path).sha256!==sha)throw Error('existing_content_address_mismatch');
  const manifest={protocol:'bench-common-content-addressed-release-v1',kind,entrypointPin:pin(entrypoint),bundlePin:pin(path),inputPins:[...inputs.values()],builderPin:pin(import.meta.path),originalDriverPin:pin(entry),
    sourceDelta:{originalDriverSha256:pin(entry).sha256,transformedDriverSha256:createHash('sha256').update(transformed).digest('hex'),changes:['manifest-declared Stand injection pre-effect check','same prepared injection used for campaign','independent native spawn custody']},taskSpecificSourceClones:0};
  const releasePath=join(directory,'release-'+manifest.builderPin.sha256+'.json'),deltaPath=join(directory,'driver-source-delta-'+manifest.builderPin.sha256+'.json');
  const save=(path:string,value:any)=>{const bytes=JSON.stringify(value,null,2)+'\n';if(existsSync(path)){if(readFileSync(path,'utf8')!==bytes)throw Error('existing_build_attestation_changed');}else writeFileSync(path,bytes,{flag:'wx'});};
  save(releasePath,manifest);save(deltaPath,{original,transformed});
  return {directory,bundlePin:pin(path),releasePin:pin(releasePath)};
}
if(import.meta.main){if(!process.argv[2]||!['terminal-driver','runner'].includes(process.argv[3]??'terminal-driver'))throw Error('explicit_release_output_root_and_known_kind_required');console.log(JSON.stringify(await buildRelease(process.argv[2],process.argv[3] as any)));}
