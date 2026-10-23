import fs from 'node:fs';
import {machine,outside} from '../../../../test/_lib.ts';
const out=await outside({'/unit':()=>({role:'assistant',kind:'prompt',body:'fixture answer'}),'/infer':()=>null,'/grade':async()=>{await Bun.sleep(1800);return true;},'/root':arg=>arg.feed[0]?.value===true});
const m=await machine();
try{
await m.api('POST','/declare',{handles:[{name:out.url('/unit'),expectMs:5000},{name:out.url('/infer'),expectMs:1000},{name:out.url('/grade'),expectMs:5000},{name:out.url('/root'),expectMs:1000}],places:[{place:'local'}],modes:[{mode:'fixture',cycles:[{cycle:'answer',maxUnits:1,from:[],next:[],infer:out.url('/infer')}]}],agents:[{name:'bot',apis:[],unit:out.url('/unit')}]});
const t=Date.now();await m.api('POST','/tasks',{id:'finalization-fixture',mode:'fixture',agent:'bot',place:'local',source:'user',description:'fixture answer',solveSeconds:1,readable:false,objective:{nodes:[{name:'grade',moment:'done',domain:'bool',handle:out.url('/grade')},{name:'root',moment:'done',domain:'bool',handle:out.url('/root')}],edges:[{src:'grade',out:0,dst:'root'}],sink:'root',checks:1}});
const source=fs.readFileSync(new URL('./run.ts'+(process.argv.includes('--pending')?'.pending':''),import.meta.url),'utf8');const cap=parseInt(source.split('Date.now()-started<')[1],10)/900000;
let verdict;while(Date.now()-t<cap*1000){const s=await m.api('POST','/query',{sql:'select state,result from task where id=:id',params:{id:'finalization-fixture'}});verdict=JSON.parse(s.rows[0].result??'{}');if(verdict.valid===true)break;await Bun.sleep(25);}
console.log(JSON.stringify({fixtureOnly:true,paidModelCalls:0,scaledCutoffSeconds:cap,elapsedMs:Date.now()-t,verdict}));
if(verdict.valid!==true)process.exitCode=1;
}finally{await m.stop();out.stop();}
