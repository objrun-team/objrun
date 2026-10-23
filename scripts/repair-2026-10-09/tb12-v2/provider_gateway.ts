/** Authenticated provider boundary with raw fsync journal and CNY shadow. */
import { randomBytes, timingSafeEqual } from "node:crypto";
import { existsSync, readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";
import { createCampaignJournal } from "../../repair-2026-10-08/campaign-journal.ts";
import { isNonGenerationRateRejection } from "../../repair-2026-10-08/campaign-contract.ts";
import { createCnyCashShadow } from "./peak_cash_shadow.ts";
import { actualPin, demand, hash, jsonPin, verifyPin, type Pin } from "../../repair-2026-10-08/paid-resource-proof-v2.ts";
import type { AdmissionLease } from "../../repair-2026-10-08/paid-resource-admission-v2.ts";
import { durable, TB12_FAMILY } from "./paid_admission.ts";
import { benchmarkProviderRequest, BENCHMARK_INFERENCE, type BenchmarkInference } from "../../repair-2026-10-08/benchmark-inference.ts";
import { benchmarkFetch, type BenchmarkProvider } from "../../repair-2026-10-08/benchmark-provider.ts";
import { createBenchmarkCash, type UsdAdmission } from "../../repair-2026-10-08/benchmark-usd-cash.ts";

type Plan={taskId:string;arm:"U"|"F";sealed:boolean;steps:number;board?:Pin};
export function providerGateway(options:{
  runId:string;output:string;prices:Pin;kind:"real-provider"|"local-mock";
  provider?:BenchmarkProvider;inference?:BenchmarkInference;admission?:AdmissionLease|UsdAdmission;providerKey?:string;sourceGuard:()=>void;
}) {
  demand(options.kind==="local-mock"||options.admission&&options.providerKey,"tb12_provider_admission_required");
  const token=randomBytes(32).toString("hex"),directory=join(options.output,"provider");
  mkdirSync(directory,{recursive:true});
  const journal=createCampaignJournal({directory,campaign:options.runId,capUsd:options.provider ? (options.admission as UsdAdmission|undefined)?.capUsd??100 : 100,
    priorCampaignCostUpperBoundUsd:0,outputDirectory:directory,provider:options.provider});
  const journalSource=actualPin(join(import.meta.dir,"../../repair-2026-10-08/campaign-journal.ts"));
  const cashOptions={directory:join(options.output,"cash"),runId:options.runId,providerKind:options.kind,admission:options.admission,prices:options.prices,
    journal:{directory,configPin:actualPin(join(directory,"journal-config.json")),sourcePin:journalSource}};
  const cash=options.provider ? createBenchmarkCash(cashOptions,options.provider) : createCnyCashShadow(cashOptions as any);
  const plans=new Map<string,Plan>(),calls:any[]=[],pending=new Map<string,number>();
  let fatal:string|undefined,stopped=false;
  const equal=(value:string)=>{const a=Buffer.from(value),b=Buffer.from(token);return a.length===b.length&&timingSafeEqual(a,b);};
  const persist=()=>durable(join(options.output,"provider-route-receipts.json"),{
    protocol:"tb12-provider-route-receipts-v1",family:TB12_FAMILY,runId:options.runId,providerKind:options.kind,
    calls,pending:Object.fromEntries(pending),fatal:fatal??null,
    modelCalls:options.kind==="real-provider"?calls.filter(call=>call.providerAttempted).length:0,
    cashSnapshot:cash.snapshot(),journalSnapshot:journal.snapshot(),
    legacyUsdFieldsUsePublishedPeakUpperBound:true,realApiCredentialNotGivenToEngine:true,
    authenticationTokenExcluded:true,
  },true);
  const finishTicket=(ticket:any,input:Parameters<typeof journal.finish>[0])=>{
    const before=journal.snapshot().durablePrefix.bytes;
    const result=journal.finish(input),after=journal.snapshot().durablePrefix;
    cash.finish(ticket,{kind:"journal-finish",journalRef:{
      finishOffset:before,finishEnd:after.bytes,finishLineSha256:after.lastSha256}});
    return result;
  };
  const server=Bun.serve({hostname:"127.0.0.1",port:0,maxRequestBodySize:4*1024**2,
    async fetch(request) {
      if(!equal(request.headers.get("authorization")?.replace(/^Bearer /,"")??""))return Response.json({error:{message:"Unauthorized TB12 provider gateway"}},{status:401});
      const path=new URL(request.url).pathname;
      if(request.method!=="POST"||!path.endsWith("/v1/chat/completions"))return Response.json({error:{message:"Unsupported route"}},{status:404});
      const route=path.slice(1,-"/v1/chat/completions".length),plan=plans.get(route);
      if(!plan)return Response.json({error:{message:"Unknown owned attempt"}},{status:422});
      if(stopped||plan.sealed||fatal)return Response.json({error:{message:"Owned provider admission closed"}},{status:409});
      let attempted=false,ticket:any,admitted:any,row:any,rawResponse:string|undefined,httpStatus:number|undefined;
      try {
        const coreRaw=await request.text();let body=JSON.parse(coreRaw);
        demand(body.model===(options.provider?.model??"deepseek-flash")&&Array.isArray(body.messages)&&body.stream!==true,"tb12_provider_profile");
        options.sourceGuard();
        body=benchmarkProviderRequest(body,options.inference??BENCHMARK_INFERENCE,options.provider);
        if(plan.board) {
          verifyPin(plan.board);const image=readFileSync(plan.board.path);
          const user=body.messages.find((message:any)=>message.role==="user");
          demand(user&&typeof user.content==="string","tb12_initial_public_image_message");
          user.content=[{type:"text",text:user.content},{type:"image_url",image_url:{url:"data:image/png;base64,"+image.toString("base64")}}];
        }
        const wire=JSON.stringify(body);
        demand(!options.providerKey||!wire.includes(options.providerKey),"tb12_credential_in_request_body");
        admitted=journal.admit({route,rawRequest:wire});
        if(!admitted.admitted)return Response.json({error:{message:admitted.reason}},{status:409});
        const seq=admitted.requestSeq,corePath=join(directory,"core-"+seq+"-request.json.gz");
        writeFileSync(corePath,gzipSync(coreRaw),{flag:"wx"});
        const state=jsonPin(actualPin(join(directory,"api-state.json")));
        const cashAdmission=cash.beforeForward({id:options.runId+"/"+seq,route,rawRequest:Buffer.from(wire),
          journal:{admitted,startPrefix:state.durablePrefix},capturedRequest:actualPin(admitted.requestFile)});
        ticket=cashAdmission.ticket;
        row={index:seq,route,taskId:plan.taskId,arm:plan.arm,requestSha256:hash(wire),
          coreRequestPin:actualPin(corePath),providerRequestPin:actualPin(admitted.requestFile),startedAt:new Date().toISOString(),
          wireParameters:{model:body.model,temperature:body.temperature,seed:body.seed,reasoning_effort:body.reasoning_effort,
            thinking:body.thinking,max_tokens:body.max_tokens,tool_choice:body.tool_choice??null},
          publicImagePin:plan.board??null,providerAttempted:false};
        calls.push(row);pending.set(route,(pending.get(route)??0)+1);persist();
        if(!cashAdmission.admitted) {
          finishTicket(ticket,{requestSeq:seq,providerAttempted:false,confirmedNoForward:true,fault:cashAdmission.reason});
          return Response.json({error:{message:cashAdmission.reason}},{status:409});
        }
        if(options.kind==="local-mock") {
          const steps:any[]=[
            {name:"bash",args:{command:"printf 'before\\n' > /app/objrun-tb12-mock.txt",timeout_ms:10000}},
            {name:"read",args:{file_path:"/app/objrun-tb12-mock.txt"}},
            {name:"write",args:{file_path:"/app/objrun-tb12-mock.txt",content:"written\n"}},
            {name:"edit",args:{file_path:"/app/objrun-tb12-mock.txt",old_string:"written",new_string:"edited"}},
            {name:"glob",args:{pattern:"objrun-tb12-mock.txt",path:"/app"}},
            {name:"grep",args:{pattern:"edited",path:"/app/objrun-tb12-mock.txt"}},
            ...(plan.arm==="F"?[{name:"verify",args:{answer:"tb12-mock-final"}}]:[]),
            {name:"submit",args:{answer:"tb12-mock-final"}},
            ...(plan.arm==="F"?[
              {name:"write",args:{file_path:"/app/objrun-tb12-mock.txt",content:"repaired-after-failed-submit\n"}},
              {name:"verify",args:{answer:"tb12-mock-repaired"}},
              {name:"submit",args:{answer:"tb12-mock-repaired"}},
            ]:[]),
          ];
          // Forced finalization does not consume the next scripted repair step.
          const action=body.tool_choice?.function?.name==="submit"?
            {name:"submit",args:{answer:"tb12-mock-final"}}:steps[Math.min(plan.steps++,steps.length-1)];
          demand(body.tools?.some((tool:any)=>tool.function?.name===action.name),"tb12_mock_tool_unavailable");
          httpStatus=200;
          rawResponse=JSON.stringify({id:"tb12-local-mock-"+route.replaceAll("/","-")+"-"+seq,model:options.provider?.model??"deepseek-flash",provider:options.provider?"DeepSeek":undefined,
            choices:[{index:0,finish_reason:"tool_calls",message:{role:"assistant",content:null,tool_calls:[{
              id:"tb12-mock-tool-"+seq,type:"function",function:{name:action.name,arguments:JSON.stringify(action.args)},
            }]}}],usage:{cost:0,prompt_tokens:0,completion_tokens:0,prompt_cache_hit_tokens:0,prompt_cache_miss_tokens:0}});
          attempted=true;row.providerAttempted=false;row.mockTransportAttempted=true;
        } else {
          options.admission!.validateForwardSource();
          attempted=true;row.providerAttempted=true;
          const response=options.provider ? await benchmarkFetch(wire,options.providerKey!) : await fetch("https://api.deepseek.com/chat/completions",{
            method:"POST",headers:{"content-type":"application/json",authorization:"Bearer "+options.providerKey!},
            body:wire,signal:AbortSignal.timeout(300000)});
          httpStatus=response.status;
          const reader=response.body!.getReader(),parts:Uint8Array[]=[];let bytes=0;
          while(true){const part=await reader.read();if(part.done)break;bytes+=part.value.length;
            demand(bytes<=2*1024**2,"tb12_provider_response_limit");parts.push(part.value);}
          rawResponse=new TextDecoder("utf-8",{fatal:true}).decode(Buffer.concat(parts.map(part=>Buffer.from(part))));
          row.safeResponseHeaders=Object.fromEntries(["date","content-type","x-request-id"].map(key=>[key,response.headers.get(key)]));
        }
        const finished=finishTicket(ticket,{requestSeq:seq,providerAttempted:attempted,httpStatus,rawResponse});
        Object.assign(row,finished.receipt);
        row.responseSha256=hash(rawResponse!);row.usage=finished.receipt.usage;row.servedModel=finished.receipt.servedModel;
        row.requestId=finished.receipt.requestId;row.httpStatus=httpStatus;row.finishedAt=finished.receipt.finishedAt;
        if(!isNonGenerationRateRejection(finished.receipt)&&(finished.receipt.fault||finished.receipt.completionValid!==true))fatal??="provider_receipt_or_completion_fault";
        return new Response(rawResponse,{status:httpStatus,headers:{"content-type":"application/json"}});
      } catch(error) {
        fatal??=error instanceof Error?error.message:"ProviderGatewayFault";
        if(row)row.fault=fatal;
        if(rawResponse!==undefined&&row) {
          const path=join(directory,"failed-"+row.index+"-response.json.gz");
          if(!existsSync(path))writeFileSync(path,gzipSync(rawResponse),{flag:"wx"});
          row.failedResponsePin=actualPin(path);
        }
        if(admitted?.admitted)try{
          finishTicket(ticket,{requestSeq:admitted.requestSeq,providerAttempted:attempted,httpStatus,rawResponse,
            confirmedNoForward:attempted?undefined:true,fault:fatal});
        }catch{/* Durable failures remain errors and cannot mint a release certificate. */}
        return Response.json({error:{message:"Owned provider evidence fault"}},{status:503});
      } finally {
        if(row){row.providerAttempted=options.kind==="real-provider"&&attempted;pending.set(route,Math.max(0,(pending.get(route)??1)-1));}
        try{persist();}catch{fatal??="provider_route_capture_fault";}
      }
    },
  });
  persist();
  return {
    origin:"http://127.0.0.1:"+server.port,token,journal,cash,calls,pending,
    register(route:string,taskId:string,arm:"U"|"F",board?:Pin){demand(!plans.has(route),"tb12_duplicate_route");plans.set(route,{taskId,arm,sealed:false,steps:0,board});},
    seal(route:string){const plan=plans.get(route);demand(plan,"tb12_unknown_route");plan.sealed=true;},
    fault(){return fatal;},
    async stop(){stopped=true;for(const plan of plans.values())plan.sealed=true;
      const expiry=Date.now()+330000;
      while([...pending.values()].some(value=>value!==0)&&Date.now()<expiry)await Bun.sleep(100);
      demand([...pending.values()].every(value=>value===0),"tb12_provider_transfers_still_pending");await server.stop(true);persist();
      durable(join(options.output,"provider-native-close.json"),{protocol:"tb12-provider-native-close-v1",runId:options.runId,
        port:server.port,serverClosed:true,pendingCount:0,closedAtUtc:new Date().toISOString(),tokenExcluded:true});},
    close(){const exported=journal.exportLegacyLedger(),cashClose=cash.close();journal.close();persist();return{exported,cashClose};},
  };
}
