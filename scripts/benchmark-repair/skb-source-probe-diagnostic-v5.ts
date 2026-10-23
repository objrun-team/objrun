import {readFileSync} from 'node:fs';import {jsonPin,actualPin,verifyPin,demand} from './paid-resource-proof-v2.ts';
const r=jsonPin(actualPin(process.argv[2]));for(const p of [...r.forwardSourcePins,r.prices]){try{verifyPin(p);}catch(e){console.log(JSON.stringify({path:p.path,error:e.code??e.message}));}}
const lock=JSON.parse(readFileSync('.phase1-data/owned-paid-campaign.lock.json','utf8')),a=jsonPin(actualPin(r.output+'/skb-admission.json'));console.log(JSON.stringify({lockMatches:JSON.stringify(lock)===JSON.stringify(a.owned)}));
