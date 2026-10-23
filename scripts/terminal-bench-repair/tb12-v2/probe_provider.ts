/** Actual local-only journal/cash/auth lifecycle. No real provider or lock. */
import { randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { providerGateway } from "./provider_gateway.ts";
import { actualPin, demand, jsonPin } from "../../benchmark-repair/paid-resource-proof-v2.ts";
import { verifyCashClosure } from "../../benchmark-repair/cny-cash-shadow-v2.ts";
import { durable } from "./paid_admission.ts";
const root=resolve(import.meta.dir,"../../.."),nonce=randomUUID().replaceAll("-","");
const output=join(root,"docs/repair-2026-10-09/tb12-preparation-v1/provider-probes",nonce);
mkdirSync(output,{recursive:true});
const prices=actualPin(join(root,"docs/repair-2026-10-09/tb12-preparation-v1/price-observations/20261009T0959/prices.json"));
let guardCalls=0;
const gateway=providerGateway({runId:"repair-"+new Date().toISOString().replace(/[:.]/g,"-"),output,prices,kind:"local-mock",sourceGuard:()=>{guardCalls++;}});
gateway.register("control/F/chess-best-move","chess-best-move","F");
const endpoint=gateway.origin+"/control/F/chess-best-move/v1/chat/completions";
const raw=JSON.stringify({model:"deepseek-flash",messages:[{role:"user",content:"Local provider control."}],
  tools:[{type:"function",function:{name:"submit",parameters:{type:"object",properties:{answer:{type:"string"}},required:["answer"]}}}],
  tool_choice:{type:"function",function:{name:"submit"}},max_tokens:8192,stream:false});
const records:any[]=[];
let fatal:any=null,closed:any;
try {
  for(const authorization of ["","Bearer invalid-probe"]) {
    const response=await fetch(endpoint,{method:"POST",headers:{"content-type":"application/json",authorization},body:raw});
    demand(response.status===401,"tb12_provider_auth_control");
    records.push({kind:"unauthorized",status:response.status});
  }
  const response=await fetch(endpoint,{method:"POST",headers:{"content-type":"application/json",authorization:"Bearer "+gateway.token},body:raw});
  const value=await response.json();
  demand(response.status===200,"tb12_local_provider_transport");
  demand((value as any).choices[0].message.tool_calls[0].function.name==="submit","tb12_local_submit_shape");
  records.push({kind:"local-mock",status:response.status,response:value});
  gateway.seal("control/F/chess-best-move");
  const after=await fetch(endpoint,{method:"POST",headers:{"content-type":"application/json",authorization:"Bearer "+gateway.token},body:raw});
  demand(after.status===409,"tb12_sealed_provider_no_forward");
  records.push({kind:"sealed-denial",status:after.status});
  await gateway.stop();
  closed=gateway.close();
  const verified=verifyCashClosure(closed.cashClose);
  demand(verified.config.providerKind==="local-mock"&&verified.proof.snapshot.newExposureNanoCny==="0"&&guardCalls===1,"tb12_local_zero_cash");
} catch(error) {
  fatal=error instanceof Error?{name:error.name,message:error.message,stack:error.stack}:String(error);
  try{await gateway.stop();}catch{}
}
const target=join(output,"probe.json");
durable(target,{protocol:"tb12-local-provider-financial-control-v1",validated:!fatal,records,fatal,closed:closed??null,
  guardCalls,modelCalls:0,canonicalLockOperations:0,realProviderForwarded:0,
  sourcePins:[actualPin(import.meta.path),actualPin(join(import.meta.dir,"provider_gateway.ts")),actualPin(join(import.meta.dir,"paid_admission.ts"))]});
console.log(JSON.stringify({report:target,validated:!fatal,fatal,modelCalls:0}));
process.exitCode=fatal?2:0;
