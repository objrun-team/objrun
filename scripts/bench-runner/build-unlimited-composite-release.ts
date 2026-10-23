import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {pin} from './manifest.ts';
import {financialPolicy} from './financial-policy.ts';
const here=import.meta.dir,original=join(here,'build-nonblocking-history-release.ts');
export async function buildUnlimitedRelease(outputRoot:string,kind:'runner'|'terminal-driver'){
 const anchor='contents=nonblockingHistorySource(path,contents,here);';const raw=readFileSync(original,'utf8');if(raw.split(anchor).length!==2)throw Error('financial_common_builder_anchor');
 const transformed='import {unlimitedFinancialSource} from '+JSON.stringify(join(here,'financial-policy-source-composite.ts'))+';\n'+raw.replace(anchor,anchor+'contents=unlimitedFinancialSource(path,contents);');
 Bun.plugin({name:'unlimited-existing-common-builder',setup(b){b.onLoad({filter:/build-nonblocking-history-release\.ts$/},args=>{if(resolve(args.path)!==resolve(original))throw Error('financial_builder_identity');return{contents:transformed,loader:'ts',resolveDir:here}})}});
 const api=await import(original);const release=await api.buildCandidateInventoryRelease(outputRoot,kind);
 const attestation={protocol:'bench-unlimited-common-release-v1',kind,...release,financialPolicy:financialPolicy(),builderPin:pin(import.meta.path),originalBuilderPin:pin(original),transformPin:pin(join(here,'financial-policy-source-composite.ts')),runtimePolicyPin:pin(join(here,'financial-policy-runtime.ts')),transformedBuilderSha256:createHash('sha256').update(transformed).digest('hex'),originalSourcesModified:false};
 const out=join(resolve(outputRoot),'financial-composite-release-'+kind+'.json');writeFileSync(out,JSON.stringify(attestation,null,2)+'\n',{flag:'wx'});return{...release,financialReleasePin:pin(out)};
}
if(import.meta.main){console.log(JSON.stringify(await buildUnlimitedRelease(process.argv[2],process.argv[3] as any)))}