/** New task-specific gateway; frozen TB/JPG timeout policy is unchanged. */
import { timingSafeEqual } from 'node:crypto';
import { gzipSync } from 'node:zlib';
import { join } from 'node:path';
import { closeSync,fsyncSync,mkdirSync,openSync,readFileSync,writeFileSync } from 'node:fs';
import { demand,hash } from './paid-resource-proof-v2.ts';
import { graderFetch } from '../../app/src/engine/registry.ts';
import { SIX_TOOLS } from './tb-nginx-contract.ts';
import type { ToolReceipt } from './tb-tool-gateway.ts';

export function skbToolGateway(options:{stand:string;token:string;store:string;ledger:(r:ToolReceipt[])=>void;beforeCapture:()=>void}){
  const receipts:ToolReceipt[]=[],places=new Map<string,{eligible:()=>string|undefined;deadline:()=>number;pending:Set<Promise<void>>;sealed?:string}>();let fault:string|undefined;
  const durable=(path:string,raw:Buffer)=>{options.beforeCapture();mkdirSync(options.store,{recursive:true});const fd=openSync(path,'wx',0o600);try{writeFileSync(fd,raw);fsyncSync(fd);}finally{closeSync(fd);}demand(readFileSync(path).equals(raw),'skb_tool_capture_readback');};
  const persist=()=>{try{options.ledger(receipts);}catch{fault='tool_ledger_capture_error';}};
  const equal=(value:string)=>{const a=Buffer.from(value),b=Buffer.from(options.token);return a.length===b.length&&timingSafeEqual(a,b);};
  const server=Bun.serve({hostname:'127.0.0.1',port:0,maxRequestBodySize:4*1024**2,async fetch(request){
    if(!equal(request.headers.get('X-ObjRun-Grader-Token')??''))return Response.json({error:'Unauthorized gateway'},{status:401});
    if(request.method!=='POST'||new URL(request.url).pathname!=='/place')return Response.json({error:'Unknown gateway route'},{status:404});
    let raw:string,body:any;try{raw=await request.text();body=JSON.parse(raw);}catch{return Response.json({error:'Malformed request'},{status:400});}
    const place=String(body.place??''),owner=places.get(place);if(!owner)return Response.json({error:'Foreign place'},{status:422});
    if(body.op!=='ping'&&!SIX_TOOLS.includes(body.tool))return Response.json({error:'Unsupported tool'},{status:422});
    let denial=owner.sealed??fault;try{denial??=owner.eligible();}catch{denial='tool_admission_evidence_error';}
    const deadline=owner.deadline();if(Date.now()>=deadline)denial??='task_deadline';if(denial)owner.sealed??=denial;
    const row:ToolReceipt={index:receipts.length,place,tool:body.op==='ping'?'ping':body.tool,admittedAt:Date.now(),requestSha256:hash(raw),forwarded:false};receipts.push(row);
    if(denial){row.denial=denial;row.finishedAt=Date.now();persist();return Response.json(body.op==='ping'?{alive:false,closed:true}:{error:'Task tools closed',reason:denial},{status:body.op==='ping'?200:409});}
    let complete!:()=>void;const pending=new Promise<void>(ok=>complete=ok);owner.pending.add(pending);
    try{
      durable(join(options.store,'tool-'+row.index+'-request.json.gz'),gzipSync(raw));persist();demand(!fault,'skb_tool_ledger_failed');
      const remaining=owner.deadline()-Date.now();demand(remaining>0&&!owner.sealed,'skb_tool_deadline_pre_dispatch');row.forwarded=true;
      const response=await graderFetch(options.stand+'/place',{method:'POST',headers:{'content-type':'application/json'},body:raw,signal:AbortSignal.timeout(remaining+30000)});
      const text=await response.text();demand(Buffer.byteLength(text)<=8*1024**2,'skb_tool_result_cap');row.httpStatus=response.status;row.responseSha256=hash(text);
      durable(join(options.store,'tool-'+row.index+'-response.json.gz'),gzipSync(text));return new Response(text,{status:response.status,headers:{'content-type':'application/json'}});
    }catch{row.fault='tool_completion_or_capture_error';fault??=row.fault;return Response.json({error:'Tool completion could not be certified'},{status:503});}
    finally{row.finishedAt=Date.now();persist();owner.pending.delete(pending);complete();}
  }});
  return {origin:'http://127.0.0.1:'+server.port,receipts,
    register(place:string,eligible:()=>string|undefined,deadline:()=>number){demand(!places.has(place),'skb_duplicate_place');places.set(place,{eligible,deadline,pending:new Set()});},
    seal(place:string,why='task_terminal'){const p=places.get(place);demand(p,'skb_unknown_seal');p.sealed??=why;},
    async drain(place:string){const p=places.get(place);demand(p,'skb_unknown_drain');this.seal(place);const end=Math.max(Date.now(),p.deadline())+60000;
      while(p.pending.size&&Date.now()<end)await Bun.sleep(10);demand(p.pending.size===0&&!fault,'skb_tool_drain_incomplete');
      return {sealed:true,finishedAt:Date.now(),outstanding:0,receipts:receipts.filter(x=>x.place===place)};},
    async stop(){for(const p of places.values())p.sealed??='gateway_closed';await server.stop(true);},
  };
}
