/** Same original queue and Runner; a signed singleton handoff, never a second scheduler. */
import{readFileSync}from'node:fs';import{resolve}from'node:path';import{verify}from'node:crypto';import{dlopen,FFIType,ptr}from'bun:ffi';
import{installUnlimitedFinancialLoader}from'./provider-task-route-loader-v3.ts';
export async function main(args=process.argv.slice(2)){
 const[configPath,planPath]=args;installUnlimitedFinancialLoader(configPath);
 const{verifyPin,pin,demand}=await import('./manifest.ts'),{processIdentity}=await import('./runtime.ts');
 const e=JSON.parse(readFileSync(planPath,'utf8')),p=e.plan;verifyPin(e.authorityPublicPin);
 demand(e.protocol==='bench-signed-same16-provider-watch-handoff-v1'&&e.authorityPublicPin.sha256==='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98'&&verify(null,Buffer.from(JSON.stringify(p)),readFileSync(e.authorityPublicPin.path),Buffer.from(e.signature,'base64')),'signed_same16_watch_handoff');
 verifyPin(p.watchEntryPin);demand(pin(import.meta.path).sha256===p.watchEntryPin.sha256,'exact_recovery_watch_entry');
 for(const x of[p.humanAuthorityPin,p.oldWatchClosedProofPin,p.originalQueueSnapshotPin,p.newBrokerActivationPin,p.sourceConfigPin])verifyPin(x);
 demand(p.humanAuthorityPin.sha256==='430a105d94afce428ddd4fa9e5d31b67589e91a22b84aecc665ebe3ef686d48e'&&p.previousWatchPid===46400&&p.previousWatchIncarnation==='134365514389802716'&&p.maxConcurrentStages===16&&p.preparationLimit===4&&pin(configPath).sha256===p.sourceConfigPin.sha256,'same_original_watch_scope_and_source');
 const closed=JSON.parse(readFileSync(p.oldWatchClosedProofPin.path,'utf8'));
 demand(closed.originalWatchPid===46400&&closed.originalWatchIncarnation===p.previousWatchIncarnation&&(closed.originalProcessWaitedExited===true||(closed.originalProcessFreshAbsentExact===true&&closed.oldWaitReceiptsMissing===true&&closed.processes.some((x:any)=>x.pid===46400&&x.originalIncarnation===p.previousWatchIncarnation&&x.originalGone===true&&x.error87===true)))&&closed.activeTasksAtHandoff===0,'original_watch_exact_closure_required');
 const api=dlopen('C:/Windows/System32/kernel32.dll',{OpenProcess:{args:[FFIType.u32,FFIType.i32,FFIType.u32],returns:FFIType.u64},GetLastError:{args:[],returns:FFIType.u32},CloseHandle:{args:[FFIType.u64],returns:FFIType.i32}});let originalGone=false;const handle=api.symbols.OpenProcess(0x1000,0,46400);try{if(handle)originalGone=processIdentity(46400).incarnation!==p.previousWatchIncarnation;else originalGone=api.symbols.GetLastError()===87}finally{if(handle)api.symbols.CloseHandle(handle);api.close()}
 demand(originalGone,'no_double_watch');
 demand(resolve(p.databasePath)===resolve(import.meta.dir,'../../docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/coordinator/universal-runner/queue.sqlite'),'original_same_queue');
 const{verifyAdoptedActivation}=await import('./unlimited-readonly-guard-retry.ts'),v=await verifyAdoptedActivation(p.newBrokerActivationPin.path);demand(v.health.targetMax===16&&Number.isSafeInteger(v.health.maxInFlight)&&v.health.maxInFlight>0&&v.health.maxInFlight<=16&&v.health.activeRequests===0&&v.health.queuedRequests===0,'same16_unique_broker_ready');
 const{DurableQueue}=await import('./queue.ts'),{Runner}=await import('./runner.ts'),{getAdapter}=await import('./adapters/index.ts'),q=new DurableQueue(p.databasePath),abort=new AbortController();
 try{demand(!q.status().jobs.some((j:any)=>j.state==='running'),'all_previous_jobs_naturally_closed');process.once('SIGINT',()=>abort.abort());process.once('SIGTERM',()=>abort.abort());console.log(JSON.stringify({protocol:'bench-same16-provider-watch-start-v1',pid:process.pid,incarnation:processIdentity(process.pid).incarnation,queue:p.databasePath,maxConcurrentStages:16,preparationLimit:4,noDoubleWatch:true}));await new Runner(q,getAdapter).dispatch({watch:true,maxConcurrentStages:16,preparationLimit:4,signal:abort.signal})}finally{q.close()}
}
if(import.meta.main)main().catch(e=>{console.error(String(e));process.exitCode=1});
