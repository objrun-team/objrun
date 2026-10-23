import {createServer} from 'node:http';
import {gradeFixedCandidate} from './campaign-contract-local-grader-20261013.next.ts';
const observed:any[]=[];
const server=createServer((req,res)=>{let body='';req.on('data',x=>body+=x);req.on('end',()=>{observed.push({auth:req.headers['x-objrun-grader-token'],body:JSON.parse(body)});res.setHeader('content-type','application/json');res.end('{"value":true}');});});
await new Promise<void>(ok=>server.listen(0,'127.0.0.1',ok));
const address=server.address();if(!address||typeof address==='string')throw Error('listener');
const origin='http://127.0.0.1:'+address.port;
process.env.TGENGIN_GRADER_TOKEN='synthetic-local-control-only';process.env.TGENGIN_GRADER_ORIGINS=JSON.stringify([origin]);
try{
 const result=await gradeFixedCandidate({objective:{nodes:[{name:'ran',domain:'bool',moment:'done',handle:origin+'/ran'}],edges:[],root:'ran'},task:{id:'control'},candidate:'synthetic',generation:{valid:true,kind:'candidate',outcome:'candidate',why:'',runtimeOutcome:'passed',runtimeVerdict:{}},timeoutMs:2000});
 if(!result.valid||!result.passed||observed.length!==1||observed[0].auth!=='synthetic-local-control-only')throw Error(JSON.stringify({valid:result.valid,why:result.why,count:observed.length}));
 console.log(JSON.stringify({passed:true,modelCalls:0,officialScoresChanged:false,authenticatedLocalContract:true}));
}finally{delete process.env.TGENGIN_GRADER_TOKEN;delete process.env.TGENGIN_GRADER_ORIGINS;server.closeAllConnections();await new Promise<void>(ok=>server.close(()=>ok()));}
