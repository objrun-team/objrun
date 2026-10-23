/** Frozen bundled project engine, private proxy key, exact child close receipt. */
import { randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { actualPin, demand, hash, verifyPin, type Pin } from "../../repair-2026-10-08/paid-resource-proof-v2.ts";
import { durable } from "./paid_admission.ts";

const ROOT=resolve(import.meta.dir,"../../..");
export async function freezeEngine(directory:string) {
  mkdirSync(directory,{recursive:true});
  const result=await Bun.build({entrypoints:[join(ROOT,"app/src/main.ts")],outdir:directory,
    target:"bun",minify:false,sourcemap:"external"});
  demand(result.success,"tb12_project_engine_bundle_failed");
  const files=result.outputs.map(output=>actualPin(output.path));
  const executable=files.find(pin=>pin.path.endsWith("main.js"));
  demand(executable,"tb12_project_engine_bundle_missing");
  return {protocol:"tb12-project-engine-frozen-bundle-v1",files,executable,
    hostBun:actualPin(process.execPath),hostBunVersion:Bun.version,
    originalEntry:actualPin(join(ROOT,"app/src/main.ts"))};
}

export async function startEngine(options:{
  directory:string;bundle:Pin;proxyKey:string;graderToken:string;graderOrigins:string[];onSecret?:(value:string)=>void;
}) {
  verifyPin(options.bundle);
  demand(!existsSync(join(dirname(process.execPath),"config.yaml")),"tb12_bun_neighbor_config");
  const probe=Bun.serve({hostname:"127.0.0.1",port:0,fetch:()=>new Response("")});
  const port=probe.port;await probe.stop(true);
  const apiToken=randomBytes(32).toString("hex"),publisherToken=randomBytes(32).toString("hex");
  options.onSecret?.(apiToken);options.onSecret?.(publisherToken);
  mkdirSync(options.directory,{recursive:true});
  const config=join(options.directory,"config.yaml");
  const settings={
    server:{host:"127.0.0.1",port,bodyLimit:1048576,shutdownTimeout:2000},
    log:{level:"warn"},db:{file:"./data/h2h.sqlite",sealed:"./data/sealed.sqlite",
      pragmas:{journal_mode:"WAL",synchronous:"FULL",foreign_keys:"ON",busy_timeout:5000}},
    api:{prefix:"/api",token:apiToken,publisherToken,allowQuery:true,allowWrite:true,maxRows:500,defaultLimit:100},
    llm:{maxTokens:8192,reasoningEffort:"none",temperature:0,seed:42,retryTimes:0,continueTimes:0},
    cors:{enabled:false,origin:"*"},
  };
  writeFileSync(config,JSON.stringify(settings),{flag:"wx",mode:0o600});
  durable(join(options.directory,"config-public.json"),{
    ...settings,api:{...settings.api,token:"REDACTED",publisherToken:"REDACTED"},
    originalConfigSha256:hash(JSON.stringify(settings)),originalConfigPrivate:true});
  const environment:Record<string,string>={};
  for(const name of ["PATH","SystemRoot","WINDIR","TEMP","TMP","APPDATA","LOCALAPPDATA","HOMEDRIVE","HOMEPATH","USERPROFILE","COMSPEC"])
    if(process.env[name])environment[name]=process.env[name]!;
  Object.assign(environment,{TGENGIN_CONFIG:config,TGENGIN_PUBLISHER_TOKEN:publisherToken,
    DEEPSEEK_API_KEY:options.proxyKey,TGENGIN_GRADER_TOKEN:options.graderToken,
    TGENGIN_GRADER_ORIGINS:options.graderOrigins.join(",")});
  const startedAt=new Date().toISOString(),startedMono=performance.now();
  const child=spawn(process.execPath,[options.bundle.path],{env:environment,windowsHide:true,
    cwd:options.directory,stdio:["ignore","pipe","pipe"]});
  demand(child.pid!==undefined,"tb12_engine_pid_missing");
  const chunks:Buffer[][]=[[],[]],bytes=[0,0],captureFaults:string[]=[];
  let exitObserved=false,closeObserved=false,exitCode:number|null=null,signal:string|null=null;
  for(const [index,stream]of [child.stdout,child.stderr].entries())stream?.on("data",(chunk:Buffer)=>{
    bytes[index]+=chunk.length;
    if(bytes[index]>2*1024**2){captureFaults.push("host-engine-stream-limit");child.kill("SIGKILL");return;}
    chunks[index].push(Buffer.from(chunk));
  });
  child.on("exit",(code,why)=>{exitObserved=true;exitCode=code;signal=why;});
  const closed=new Promise<void>(resolveClose=>child.on("close",()=>{closeObserved=true;resolveClose();}));
  child.on("error",error=>captureFaults.push(error.name));
  const base="http://127.0.0.1:"+port+"/api";
  const stop=async()=>{
    if(!closeObserved) {
      child.kill("SIGTERM");
      await Promise.race([closed,Bun.sleep(5000)]);
      if(!closeObserved){child.kill("SIGKILL");await Promise.race([closed,Bun.sleep(5000)]);}
    }
    demand(exitObserved&&closeObserved,"tb12_engine_actual_exit_and_close_required");
    const stdout=join(options.directory,"engine.stdout"),stderr=join(options.directory,"engine.stderr");
    writeFileSync(stdout,Buffer.concat(chunks[0]),{flag:"wx"});writeFileSync(stderr,Buffer.concat(chunks[1]),{flag:"wx"});
    const receipt=durable(join(options.directory,"engine-close.json"),{
      protocol:"tb12-host-engine-exact-close-v1",pid:child.pid,argv:[process.execPath,options.bundle.path],
      startedAtUtc:startedAt,closedAtUtc:new Date().toISOString(),monotonicSeconds:(performance.now()-startedMono)/1000,
      exitObserved,closeObserved,exitCode,signal,port,captureFaults,bundle:options.bundle,
      stdout:actualPin(stdout),stderr:actualPin(stderr),projectApiCredentialInChild:false,
    });
    return receipt;
  };
  let healthy=false;
  for(let step=0;step<200;step++) {
    if(closeObserved)break;
    try {
      const response=await fetch(base+"/health",{signal:AbortSignal.timeout(1000)});
      if(response.ok) {
        const data=await response.json() as any;
        demand(data.db.replaceAll("\\","/").toLowerCase()===join(options.directory,"data/h2h.sqlite").replaceAll("\\","/").toLowerCase(),"tb12_engine_wrong_database");
        healthy=true;break;
      }
    }catch(error){if(error instanceof Error&&error.message==="tb12_engine_wrong_database"){await stop();throw error;}}
    await Bun.sleep(100);
  }
  if(!healthy){await stop();throw Error("tb12_frozen_engine_startup_failed");}
  const unauth=await fetch(base+"/exec",{method:"POST",headers:{"content-type":"application/json"},body:'{"sql":"select 1"}'});
  if(unauth.status!==401){await stop();throw Error("tb12_engine_unauthenticated");}
  return {
    pid:child.pid,port,base,directory:options.directory,stop,
    async api<T=any>(method:string,path:string,body?:unknown):Promise<T> {
      const response=await fetch(base+path,{method,headers:{authorization:"Bearer "+apiToken,
        "X-TGEngin-Publisher":publisherToken,...(body===undefined?{}:{"content-type":"application/json"})},
        ...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(120000)});
      const value=await response.json();
      if(!response.ok)throw Error("Owned engine API "+response.status+" "+path+" "+JSON.stringify(value));
      return value as T;
    },
  };
}
