/** Separate provider runtime: original Relace evidence and verifier sources remain immutable. */
import {readFileSync,writeFileSync,existsSync} from 'node:fs';
import {join,resolve} from 'node:path';
const root=resolve(import.meta.dir,'../../../..'),old=join(root,'scripts/benchmark-repair');
const names:Record<string,string>={
 'benchmark-provider.ts':'digitalocean-provider.ts',
 'benchmark-inference.ts':'digitalocean-inference.ts',
 'campaign-journal.ts':'digitalocean-journal.ts',
 'benchmark-usd-cash.ts':'digitalocean-usd-cash.ts',
 'scientific-journal-proxy.ts':'digitalocean-proxy.ts',
 'openrouter-paid-admission.ts':'digitalocean-admission.ts',
};
for(const [source,target] of Object.entries(names)){
 const path=join(import.meta.dir,target);if(existsSync(path))throw Error('Refuse to replace an existing runtime: '+target);
 let body=readFileSync(join(old,source),'utf8');
 body=body.replace(/from (["'])(\.\/[^"']+)\1/g,(_all,q,relative)=>{
  const file=relative.slice(2);return 'from '+q+(names[file]?'./'+names[file]:'../../../benchmark-repair/'+file)+q;
 });
 if(source==='benchmark-provider.ts')body=body.replace('providerName: "Relace", providerSlug: "relace"','providerName: "DigitalOcean", providerSlug: "digitalocean"').replace('only: ["relace"]','only: ["digitalocean"]');
 if(source==='campaign-journal.ts'){
  body=body.replace('pendingLimit: 4;','pendingLimit: number;').replace('config.pendingLimit === 4','Number.isSafeInteger(config.pendingLimit) && config.pendingLimit >= 4 && config.pendingLimit <= 50').replace('pendingLimit: 4, model:','pendingLimit: 50, model:');
  body=body.replace('active.size < 4','active.size < config.pendingLimit').replace('this.active.size >= 4','this.active.size >= this.config.pendingLimit');
  body=body.replace('["deepseek", "relace"].includes(slug)','["deepseek", "relace", "digitalocean"].includes(slug)').replace('(slug === "relace" ? "Relace" : "DeepSeek")','({relace:"Relace",deepseek:"DeepSeek",digitalocean:"DigitalOcean"}[slug])');
 }
 if(source==='benchmark-usd-cash.ts')body=body.replace("(providerSlug === 'relace' ? 'Relace' : 'DeepSeek')","({relace:'Relace',deepseek:'DeepSeek',digitalocean:'DigitalOcean'}[providerSlug])");
 writeFileSync(path,body,{flag:'wx'});
}
console.log(JSON.stringify({created:Object.values(names),originalRelaceSourcesChanged:false,modelCalls:0}));
