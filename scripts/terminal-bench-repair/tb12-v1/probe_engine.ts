/** Freeze and actually start the project engine without any task/model call. */
import { randomBytes, randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { freezeEngine, startEngine } from "./host_engine.ts";
import { durable } from "./paid_admission.ts";
import { actualPin, demand } from "../../benchmark-repair/paid-resource-proof-v2.ts";
const root=resolve(import.meta.dir,"../../.."),nonce=randomUUID().replaceAll("-","");
const output=join(root,"docs/repair-2026-10-09/tb12-preparation-v1/engine-probes",nonce);
mkdirSync(output,{recursive:true});
let machine:Awaited<ReturnType<typeof startEngine>>|undefined,bundle:any,closed:any,fatal:any=null;
try {
  bundle=await freezeEngine(join(output,"frozen-engine"));
  machine=await startEngine({directory:join(output,"engine"),bundle:bundle.executable,
    proxyKey:randomBytes(32).toString("hex"),graderToken:randomBytes(32).toString("hex"),
    graderOrigins:["http://127.0.0.1:1"]});
  const query=await machine.api("POST","/query",{sql:"select count(*) as count from task"});
  demand(query.rows[0].count===0,"tb12_no_model_tasks_in_engine_probe");
  closed=await machine.stop();machine=undefined;
}catch(error){fatal=error instanceof Error?{name:error.name,message:error.message,stack:error.stack}:String(error);}
finally{if(machine)try{closed=await machine.stop();}catch(error){fatal??=String(error);}}
const target=join(output,"probe.json");
durable(target,{protocol:"tb12-frozen-project-engine-control-v1",validated:!fatal,bundle:bundle??null,
  actualClosePin:closed??null,fatal,modelCalls:0,paidLockOperations:0,
  sourcePins:[actualPin(import.meta.path),actualPin(join(import.meta.dir,"host_engine.ts"))]});
console.log(JSON.stringify({report:target,validated:!fatal,fatal,modelCalls:0}));
process.exitCode=fatal?2:0;
