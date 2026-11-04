/** Finite retries for read-only control-plane GETs; never dispatches inference. */
export async function controlRead(url:string, init:any={}, options:{deadline?:number;onAttempt?:(entry:any)=>void;backoffMs?:number}={}){
 const deadline=options.deadline??Date.now()+65000;
 let last='NoAttempt';
 for(let attempt=0;attempt<3;attempt++){
  if(Date.now()>=deadline)break;
  const started=Date.now();let status=0,permanent=false;
  try{
   const r=await fetch(url,{...init,method:'GET',headers:{...init.headers,connection:'close'},timeout:false,signal:AbortSignal.timeout(Math.max(1,Math.min(10000,deadline-Date.now())))} as any);
   status=r.status;
   if(!r.ok){permanent=![408,425,429].includes(status)&&status<500;throw Error('HTTP'+status);}
   const data=await r.json();
   options.onAttempt?.({attempt,status,seconds:(Date.now()-started)/1000,ok:true});
   return data as any;
  }catch(e){last=String(e);options.onAttempt?.({attempt,status,seconds:(Date.now()-started)/1000,ok:false,error:last});}
  if(permanent||attempt===2||Date.now()>=deadline)break;
  await Bun.sleep(Math.max(0,Math.min((options.backoffMs??250)*(attempt+1),deadline-Date.now())));
 }
 throw Error('ControlPlaneReadFailed:'+new URL(url).pathname+':'+last);
}
