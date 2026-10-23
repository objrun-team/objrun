/** Owned stand process. Closure is HTTP cleanup, native exit and stream close. */
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { actualPin, demand } from "../../repair-2026-10-08/paid-resource-proof-v2.ts";
import { durable } from "./paid_admission.ts";

export async function startStand(options:{output:string;script:string;baseProof:string;token:string}) {
  mkdirSync(options.output,{recursive:true});
  const python="D:/ProgramData/anaconda3/python.exe";
  const args=["-B","-X","utf8",options.script,"--base-proof",options.baseProof,"--output",join(options.output,"stand")];
  const environment:Record<string,string>={};
  for(const name of ["PATH","SystemRoot","WINDIR","TEMP","TMP","APPDATA","LOCALAPPDATA","USERPROFILE","COMSPEC"])
    if(process.env[name])environment[name]=process.env[name]!;
  environment.OBJRUN_TB12_STAND_TOKEN=options.token;
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
  const call=async(path:string,body:unknown,timeoutMs=120000)=>{
    const response=await fetch(origin+path,{method:"POST",headers:{"content-type":"application/json",
      "X-ObjRun-Grader-Token":options.token},body:JSON.stringify(body),signal:AbortSignal.timeout(timeoutMs)});
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
    origin,pid:child.pid,port:ready.port,call,
    async close() {
      await call("/close",{});
      await Promise.race([closed,Bun.sleep(30000)]);
      if(!closeObserved){child.kill("SIGKILL");await Promise.race([closed,Bun.sleep(5000)]);faults.push("stand_close_timeout");}
      demand(exitObserved&&closeObserved&&exitCode===0&&!faults.length,"tb12_stand_exit_and_close");
      return finishCapture();
    },
  };
}
