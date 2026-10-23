import { startupFetchOptions as originalStandUpFetchOptions } from "F:/git/TgEngin-handoff-2026-10-07/TgEngin/scripts/bench-runner/stand-up-startup-deadline-v1.ts";
/** Owned stand process. Closure is HTTP cleanup, native exit and stream close. */
import { observedSpawn as spawn } from "F:/git/TgEngin-handoff-2026-10-07/TgEngin/docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/coordinator/universal-runner/takeover-tb-preparation/owned-hard-quota-filesystem-repair-v1/formal-consumer-scope-v1/genuine-task-qualification-admission-v1/source-candidates/811b111cc126dc6107834f8cbbfec262caec10fb2ac6b439ec3cf10241338139/owned-quota-configured-relative-observed-spawn.ts";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { actualPin, demand } from "../../repair-2026-10-08/paid-resource-proof-v2.ts";
import { durable } from "./paid_admission.ts";

export async function startStand(options:{output:string;script:string;baseProof:string;token:string}) {
  mkdirSync(options.output,{recursive:true});
  const python="D:\\ProgramData\\anaconda3\\python.exe";
  const args=["-B","-X","utf8","F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\repair-2026-10-10\\full-f\\terminal-bench\\stand_v1.py","--base-proof",options.baseProof,"--output",join(options.output,"stand")];const __entry="F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\repair-2026-10-10\\full-f\\terminal-bench\\stand_v1.py";const __before=args.slice();const __clean=__before.filter(x=>x!=="-B"&&x!=="-X"&&x!=="utf8"&&x!==__entry&&x!==options.script);const __after=(__before[0]==="-B"&&__before[1]==="-X"&&__before[2]==="utf8")?__before:["-B","-X","utf8",__entry,...__clean];try{const __fs=await import("node:fs");const __rd=process.env.BENCH_RUN_DIR;if(__rd){const __p=__rd+"/command-intent.json";const __ci=JSON.parse(__fs.readFileSync(__p,"utf8"));__ci.standArgvBinding={before:__before,after:__after,command:python};__fs.writeFileSync(__p,JSON.stringify(__ci));}}catch{}
  const environment:Record<string,string>={};
  for(const name of ["PATH","SystemRoot","WINDIR","TEMP","TMP","APPDATA","LOCALAPPDATA","USERPROFILE","COMSPEC"])
    if(process.env[name])environment[name]=process.env[name]!;
  for(const key of ["DOCKER_HOST","NOVAEVE_ACTIVATION_PATH","NOVAEVE_BROKER_CONTROL_PATH","NOVAEVE_RESOURCE_PARENT_PID","NOVAEVE_RESOURCE_LEASE_PID","NOVAEVE_RESOURCE_MEMORY_MB","NOVAEVE_RESOURCE_GROWTH_BYTES","NOVAEVE_RESOURCE_BENCH","NOVAEVE_RESOURCE_TOKEN","NOVAEVE_RESOURCE_SLOTS","NOVAEVE_ROOT_ONLY_DISPATCH"]){demand(typeof process.env[key]==="string"&&process.env[key]!.length>0,"qualified_actual_standard_environment_required:"+key);environment[key]=process.env[key]!;}
environment.OBJRUN_TB12_STAND_TOKEN=options.token;
  const child=spawn(python,["-B","-X","utf8","F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\bench-runner\\python_child_entry.py","--config","F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\work\\remaining12-parallel-20261018\\group-a\\install-windows-3.11\\formal-v2\\python-source-mapping.json","--original-script",options.script,"--",...args.slice(4)],{env:environment,windowsHide:true,stdio:["ignore","pipe","pipe"]});
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
  for(let step=0;step<1200&&!ready&&!closeObserved;step++)await Bun.sleep(100);
  const origin="http://127.0.0.1:"+(ready?.port??0);
  const call=async(path:string,body:unknown,timeoutMs=120000)=>{
    const response=await fetch(origin+path,{method:"POST",headers:{"content-type":"application/json",
      "X-ObjRun-Grader-Token":options.token},body:JSON.stringify(body),...(path==="/up"?originalStandUpFetchOptions({"protocol":"bench-original-stand-up-parent-deadline-v1","path":"/up","preBeginOnly":true,"originalHttpDefaultMs":120000,"scope":"original-task-pre-begin","helperPin":{"path":"F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\bench-runner\\stand-up-startup-deadline-v1.ts","bytes":5289,"sha256":"522149c871d2e52efcf75dafe4039132c0c6feccc2dcc51f42109d62e3069a3a"},"acceptancePin":{"path":"F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\docs\\repair-2026-10-10\\full-f-rerun\\novaeve-formal-20261013\\coordinator\\universal-runner\\takeover-tb-preparation\\owned-hard-quota-filesystem-repair-v1\\formal-consumer-scope-v1\\genuine-task-qualification-admission-v1\\stand-up-startup-deadline-repair-v1\\actual-bound-v4\\ORIGINAL-STAND-UP-DEADLINE-ACCEPTED.owner-signed.json","bytes":16013,"sha256":"6bc30eef44174f7f3af59b6ee9b263a48fb64691babb0a02c37824d6ced8aa5e"}}):{signal:AbortSignal.timeout(timeoutMs)})});
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
