import {controlRead} from './control_read.ts';
import {ROOT,save} from './common.ts';
import {join} from 'node:path';
const counts:Record<string,number>={};
const server=Bun.serve({hostname:'127.0.0.1',port:0,fetch(req){
 const path=new URL(req.url).pathname,n=counts[path]=(counts[path]??0)+1;
 if(path==='/transient'&&n<3)return new Response('retry',{status:503});
 if(path==='/malformed'&&n===1)return new Response('incomplete');
 if(path==='/permanent')return new Response('unauthorized',{status:401});
 if(path==='/exhausted')return new Response('unavailable',{status:503});
 return Response.json({data:{remaining:1}});
}});
try{
 const base='http://127.0.0.1:'+server.port;
 const actualFetch=globalThis.fetch;let socketAttempts=0;
 globalThis.fetch=((url:any,init:any)=>{
  if(String(url).endsWith('/socket')&&++socketAttempts<3)throw Error('Injected socket connection closed');
  return actualFetch(url,init);
 }) as any;
 try{
  if((await controlRead(base+'/socket',{}, {backoffMs:1})).data.remaining!==1||socketAttempts!==3)throw Error('SocketRecoveryFailed');
 }finally{globalThis.fetch=actualFetch;}
 for(const path of ['/transient','/malformed']){
  const result=await controlRead(base+path,{}, {backoffMs:1});
  if(result.data.remaining!==1)throw Error('RecoveryFailed');
 }
 for(const path of ['/permanent','/exhausted']){
  let rejected=false;try{await controlRead(base+path,{}, {backoffMs:1});}catch(e){rejected=String(e).includes('ControlPlaneReadFailed');}
  if(!rejected)throw Error('FailureNotClosed');
 }
 if(counts['/transient']!==3||counts['/malformed']!==2||counts['/permanent']!==1||counts['/exhausted']!==3)throw Error('IncorrectFiniteRetryCount');
 const report={passed:true,readOnlyGetRetries:true,socketRecoveryAttempts:socketAttempts,noInferenceCalls:true,counts};
 save(join(ROOT,'control/control-plane-controls.json'),report);console.log(JSON.stringify(report));
}finally{await server.stop(true);}
