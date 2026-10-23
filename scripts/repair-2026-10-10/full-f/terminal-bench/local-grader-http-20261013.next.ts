/** Staged loopback transport only. Does not change verifier/solver deadlines. */
import {request} from 'node:http';

export async function localGraderFetch(url:string, init:RequestInit, trustedOrigin:string):Promise<Response>{
 const parsed=new URL(url);
 if(parsed.origin!==trustedOrigin||parsed.protocol!=='http:'||parsed.hostname!=='127.0.0.1'||parsed.username||parsed.password)
  throw Error('exact_loopback_grader_origin_required');
 if(init.method!=='POST'||typeof init.body!=='string'||!init.signal)
  throw Error('explicit_grader_post_body_and_deadline_required');
 if(init.signal.aborted)throw init.signal.reason;
 const headers=Object.fromEntries(new Headers(init.headers).entries());
 const signal=init.signal;
 return new Promise<Response>((resolve,reject)=>{
  let settled=false;
  const finish=(error?:unknown,value?:Response)=>{
   if(settled)return;settled=true;signal.removeEventListener('abort',abort);
   if(error)reject(error);else resolve(value!);
  };
  const req=request(parsed,{method:'POST',headers,agent:false},res=>{
   const parts:Buffer[]=[];let bytes=0;
   res.on('data',(chunk:Buffer)=>{bytes+=chunk.length;if(bytes>2*1024**2){req.destroy();finish(Error('grader_response_bound'));}else parts.push(Buffer.from(chunk));});
   res.on('aborted',()=>finish(Error('grader_response_incomplete')));
   res.on('error',finish);
   res.on('end',()=>{
    if(!res.complete)return finish(Error('grader_response_incomplete'));
    const output=new Headers();
    for(const [name,value] of Object.entries(res.headers))if(value!==undefined)output.set(name,Array.isArray(value)?value.join(', '):value);
    finish(undefined,new Response(Buffer.concat(parts),{status:res.statusCode??500,headers:output}));
   });
  });
  const abort=()=>{req.destroy();finish(signal.reason??Error('original_verifier_deadline'));};
  signal.addEventListener('abort',abort,{once:true});
  req.on('error',finish);
  // No independent socket-idle deadline; the original explicit signal governs.
  req.setTimeout(0);
  req.end(init.body);
  if(signal.aborted)abort();
 });
}
