import {writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
const rows:any[]=[];
for(const keepalive of [true,false]){
 for(let n=0;n<4;n++){
  const start=Date.now();
  try{const r=await fetch('https://openrouter.ai/api/v1/models',{proxy:'http://127.0.0.1:10809',keepalive,signal:AbortSignal.timeout(15000)} as any);const body=await r.text();rows.push({route:'existing-proxy',keepalive,n,httpStatus:r.status,bytes:Buffer.byteLength(body),seconds:(Date.now()-start)/1000});}
  catch(e){rows.push({route:'existing-proxy',keepalive,n,error:String(e),seconds:(Date.now()-start)/1000});}
 }
}
writeFileSync(resolve(import.meta.dir,'../../docs/evalplus-20261012/mbpp/diagnosis/interface-readonly-probe.json'),JSON.stringify({atUtc:new Date().toISOString(),modelCalls:0,credentialSent:false,rows},null,2)+'\n');
console.log(JSON.stringify(rows));
