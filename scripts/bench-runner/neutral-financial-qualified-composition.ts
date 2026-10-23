import{readFileSync,writeFileSync}from'node:fs';import{resolve,join}from'node:path';import{pathToFileURL}from'node:url';import{installUnlimitedFinancialLoader}from'./financial-policy-loader-composite.ts';
const [configPath,directory]=process.argv.slice(2);installUnlimitedFinancialLoader(configPath);const names=['campaign','launcher','gateway'],callbacks:string[]=[];
const exact=(p:string)=>new RegExp('^'+resolve(p).replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'$');
Bun.plugin({name:'actual-qualified-hook-after-financial',setup(b){
 for(const name of names){
  const path=join(directory,name+'.ts');
  b.onLoad({filter:exact(path)},()=>{callbacks.push(name);return{contents:readFileSync(path,'utf8').replace("'original'","'qualified'"),loader:'ts',resolveDir:directory}});
 }
}});
for(const name of names){const m=await import(pathToFileURL(join(directory,name+'.ts')).href);if(m.marker!=='qualified')throw Error('qualified_source_hook_shadowed:'+name)}
const q=await import('./qualified-mapped-interfaces.ts'),gatewayPin={path:join(directory,'gateway.ts'),bytes:readFileSync(join(directory,'gateway.ts')).length,sha256:new Bun.CryptoHasher('sha256').update(readFileSync(join(directory,'gateway.ts'))).digest('hex')};
const manifest:any={provenance:{sourcePins:[gatewayPin]}},driver:any={qualifiedInterfaces:{gateway:{pin:gatewayPin,mode:'original-admit-prejournal-v1'}}};const cb=await q.qualifiedCampaignCallbacks(manifest,driver,async()=>null as any);if(await cb.benchBeforeJournalGuard()!==null)throw Error('actual_qualified_unlimited_callback');let finiteRejected=false;try{await(await q.qualifiedCampaignCallbacks(manifest,driver,async()=>5)).benchBeforeJournalGuard()}catch{finiteRejected=true}if(!finiteRejected)throw Error('finite_policy_not_rejected');
writeFileSync(join(directory,'composition.actual.json'),JSON.stringify({protocol:'bench-actual-financial-qualified-hook-composition-v1',complete:true,financialRegisteredFirst:true,qualifiedRegisteredSecond:true,actualQualifiedCallbacks:callbacks,allThreeQualifiedTransformsApplied:true,actualOriginalQualifiedCallbackAcceptedNull:true,finitePolicyRejected:true,modelRequests:0,gradeCalls:0},null,2)+'\n',{flag:'wx'});console.log(JSON.stringify({complete:true,callbacks,finiteRejected,modelRequests:0}));
