import {infrastructureHttpFetch} from 'F:/git/TgEngin-handoff-2026-10-07/TgEngin/scripts/benchmark-campaign/full-f/novaeve_formal_v1/http_transport_v5/fetch.ts';
/** Owned stand process. Closure is HTTP cleanup, native exit and stream close. */
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { actualPin, demand } from "F:/git/TgEngin-handoff-2026-10-07/TgEngin/scripts/benchmark-repair/paid-resource-proof-v2.ts";
import { durable } from "F:/git/TgEngin-handoff-2026-10-07/TgEngin/scripts/terminal-bench-repair/tb12-v2/paid_admission.ts";

export async function startStand(options:{output:string;script:string;baseProof:string;token:string}) {
  mkdirSync(options.output,{recursive:true});
  const python="D:/ProgramData/anaconda3/python.exe";
  const args=["-B","-X","utf8",options.script,"--base-proof",options.baseProof,"--output",join(options.output,"stand")];
  const environment:Record<string,string>={};
  for(const name of ["PATH","SystemRoot","WINDIR","TEMP","TMP","APPDATA","LOCALAPPDATA","USERPROFILE","COMSPEC"])
    if(process.env[name])environment[name]=process.env[name]!;
  environment.OBJRUN_TB12_STAND_TOKEN=options.token;
  for(const key of ['NOVAEVE_RESOURCE_PARENT_PID','NOVAEVE_RESOURCE_LEASE_PID','NOVAEVE_RESOURCE_MEMORY_MB','NOVAEVE_RESOURCE_GROWTH_BYTES','NOVAEVE_RESOURCE_BENCH','NOVAEVE_RESOURCE_TOKEN','NOVAEVE_ROOT_ONLY_DISPATCH']){demand(process.env[key],'pipeline_actual_resource_env_required:'+key);environment[key]=process.env[key]!;}
  environment.NOVAEVE_ACTIVATION_PATH="F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\docs\\repair-2026-10-10\\full-f-rerun\\novaeve-formal-20261013\\activation-adopted-v48.json";
  environment.NOVAEVE_BROKER_CONTROL_PATH="F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\docs\\repair-2026-10-10\\full-f-rerun\\novaeve-formal-20261013\\broker\\control-adopted-v48.private.json";
  environment.DOCKER_HOST="tcp://127.0.0.1:18750";
  const child=spawn(python,args,{env:environment,windowsHide:true,stdio:["ignore","pipe","pipe"]});
  demand(child.pid!==undefined,"tb12_stand_native_pid_required");
  const start=new Date().toISOString(),chunks:Buffer[][]=[[],[]],bytes=[0,0],faults:string[]=[];
  let carry="",ready:any,exitObserved=false,closeObserved=false,exitCode:number|null=null,signal:string|null=null;
  for(const [index,stream]of [child.stdout,child.stderr].entries())stream?.on("data",(chunk:Buffer)=>{
    bytes[index]+=chunk.length;
    if(bytes[index]>2*1024**2){faults.push("stand-stream-bound");child.kill("SIGKILL");return;}
    chunks[index].push(Buffer.from(chunk));
    if(index===0&&!ready) {
      carry+=chunk.toString("utf8");
      const newline=carry.indexOf("\n");
      if(newline>=0)try{ready=JSON.parse(carry.slice(0,newline));}catch{faults.push("stand-ready-frame");}
    }
  });
  child.on("exit",(code,why)=>{exitObserved=true;exitCode=code;signal=why;});
  const closed=new Promise<void>(resolve=>child.on("close",()=>{closeObserved=true;resolve();}));
  child.on("error",error=>faults.push(error.name));
  for(let step=0;step<600&&!ready&&!closeObserved;step++)await Bun.sleep(100);
  const origin="http://127.0.0.1:"+(ready?.port??0);
  const call=async(path:string,body:unknown,timeoutMs=(path==="/up"||path==="/close"?600000:120000))=>{
    const response=await infrastructureHttpFetch(origin+path,{method:"POST",headers:{"content-type":"application/json",
      "X-ObjRun-Grader-Token":options.token},body:JSON.stringify(body),},timeoutMs);
    const raw=await response.text();demand(Buffer.byteLength(raw)<=2*1024**2,"tb12_stand_response_limit");
    if(!response.ok)throw Error("Owned stand "+response.status+" "+path+" "+raw);
    return JSON.parse(raw);
  };
  const finishCapture=()=>{
    const stdout=join(options.output,"stand.stdout"),stderr=join(options.output,"stand.stderr");
    writeFileSync(stdout,Buffer.concat(chunks[0]),{flag:"wx"});
    writeFileSync(stderr,Buffer.concat(chunks[1]),{flag:"wx"});
    return durable(join(options.output,"stand-close.json"),{
      protocol:"tb12-stand-native-close-v1",pid:child.pid,argv:[python,...args],port:ready?.port??null,
      startedAtUtc:start,closedAtUtc:new Date().toISOString(),exitObserved,closeObserved,exitCode,signal,faults,
      stdout:actualPin(stdout),stderr:actualPin(stderr),script:actualPin(options.script),python:actualPin(python),
      standReceipt:existsSync(join(options.output,"stand/stand-receipts.json"))?actualPin(join(options.output,"stand/stand-receipts.json")):null,tokenExcluded:true,
    });
  };
  if(!(ready?.protocol==="tb12-stand-ready-v1"&&ready.pid===child.pid&&ready.modelCalls===0&&!faults.length)) {
    if(!closeObserved){child.kill("SIGKILL");await Promise.race([closed,Bun.sleep(5000)]);}
    finishCapture();throw Error("tb12_stand_actual_startup");
  }
  return{
    origin,pid:child.pid,port:ready.port,call,isClosed:()=>closeObserved,waitForClose:()=>closed,
    async close() {
      let closeError:unknown,actorsAbsent=false;
      try{const result=await call("/close",{});actorsAbsent=result.allExactOwnedActorsAbsent===true;}catch(error){closeError=error;}
      await Promise.race([closed,Bun.sleep(30000)]);
      if(!closeObserved&&actorsAbsent){child.kill("SIGKILL");await Promise.race([closed,Bun.sleep(5000)]);faults.push("stand_close_timeout");}
      if(closeError||!actorsAbsent){faults.push("stand_close_without_actor_absence");finishCapture();throw Object.assign(new Error("stand_close_requires_owned_actor_reconciliation"),{childPid:child.pid,closeObserved});}
      demand(exitObserved&&closeObserved&&exitCode===0&&!faults.length,"tb12_stand_exit_and_close");
      return finishCapture();
    },
  };
}
