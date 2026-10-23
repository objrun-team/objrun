import { randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { Machine } from "../../test/_lib.ts";

/** Private host control plane for a solver that can reach host.docker.internal. */
export async function tbEngine(llm: Record<string,string|number>, directory: string): Promise<Machine> {
  if (existsSync(join(dirname(process.execPath), "config.yaml"))) throw new Error("A Bun-neighbor configuration would override the private TB engine");
  const probe = Bun.serve({hostname:"127.0.0.1",port:0,fetch:()=>new Response("")}); const port=probe.port;await probe.stop(true);
  const apiToken=randomBytes(32).toString("hex"), publisherToken=randomBytes(32).toString("hex");
  mkdirSync(directory,{recursive:true});
  const config=join(directory,"config.yaml");
  writeFileSync(config,[
    "server: {host: 127.0.0.1, port: "+port+", bodyLimit: 1048576, shutdownTimeout: 2000}",
    "log: {level: warn}",
    "db: {file: ./data/h2h.sqlite, sealed: ./data/sealed.sqlite, pragmas: {journal_mode: WAL, synchronous: NORMAL, foreign_keys: ON, busy_timeout: 5000}}",
    "api: {prefix: /api, token: "+JSON.stringify(apiToken)+", publisherToken: "+JSON.stringify(publisherToken)+", allowQuery: true, allowWrite: true, maxRows: 500, defaultLimit: 100}",
    "llm: {"+Object.entries(llm).map(([key,value])=>key+": "+value).join(", ")+"}",
    "cors: {enabled: false, origin: '*'}", "",
  ].join("\n"),{encoding:"utf8",mode:0o600});
  const root=join(import.meta.dir,"../..");
  const child=spawn(process.execPath,["--env-file="+join(root,".env"),join(root,"app/src/main.ts")],{env:{...process.env,TGENGIN_CONFIG:config,TGENGIN_PUBLISHER_TOKEN:publisherToken},windowsHide:true,stdio:["ignore","pipe","pipe"]});
  child.stdout?.resume(); child.stderr?.resume();
  if(child.pid===undefined) throw new Error("Private TB engine did not receive a PID");
  const base="http://127.0.0.1:"+port+"/api";
  const stop=async()=>{if(child.exitCode===null&&child.signalCode===null)await new Promise<void>(resolve=>{const timer=setTimeout(()=>child.kill("SIGKILL"),3000);child.once("exit",()=>{clearTimeout(timer);resolve();});child.kill();});};
  for(let i=0;i<100;i++){
    try{const response=await fetch(base+"/health");if(response.ok){const health=await response.json() as {db:string};if(health.db.replaceAll("\\","/").toLowerCase()!==join(directory,"data/h2h.sqlite").replaceAll("\\","/").toLowerCase())throw new Error("Private TB engine opened a different database");break;}}catch(error){if(error instanceof Error&&error.message.includes("different database")){await stop();throw error;}}
    if(child.exitCode!==null||i===99){await stop();throw new Error("Private TB engine did not start");}await Bun.sleep(100);
  }
  if((await fetch(base+"/exec",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({sql:"select 1"})})).status!==401){await stop();throw new Error("TB host control plane is not authenticated");}
  const request=async(method:string,path:string,body?:unknown)=>{const response=await fetch(base+path,{method,headers:{authorization:"Bearer "+apiToken,"X-TGEngin-Publisher":publisherToken,...(body===undefined?{}:{"content-type":"application/json"})},...(body===undefined?{}:{body:JSON.stringify(body)})});return {response,data:await response.json()};};
  return {pid:child.pid,base,directory,stop,async api<T>(method:string,path:string,body?:unknown){const value=await request(method,path,body);if(!value.response.ok)throw new Error("Private TB engine request failed: "+value.response.status+" "+path+" "+JSON.stringify(value.data));return value.data as T;},async bad(method:string,path:string,body?:unknown){const value=await request(method,path,body);if(value.response.ok)throw new Error("Expected private engine rejection");return value.data as Record<string,unknown>;} };
}
