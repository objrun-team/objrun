/** One process per lane: isolates the project grader's process-wide auth env. */
import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { actualPin, demand, jsonPin, nanoCny, REAL_CLOCK, same } from "../repair-2026-10-08/paid-resource-proof-v2.ts";
import { durable } from "./tb12-v2/paid_admission.ts";
import { executePaired } from "./tb12-v2/paired_trial.ts";
import { executedSources } from "./tb12-v2/freeze_sources.ts";
const ROOT=resolve(import.meta.dir,"../.."),master=resolve(process.argv[2]),lane=Number(process.argv[3]);
const manifest=jsonPin(actualPin(join(master,"manifest.json"))),lock=join(ROOT,".phase1-data/tb12-owned-fast-v3.lock.json");
const parent=JSON.parse(readFileSync(lock,"utf8"));demand(parent.runId===manifest.runId&&[0,1].includes(lane),"tb12_process_lane_parent");
const assertOwned=()=>demand(same(JSON.parse(readFileSync(lock,"utf8")),parent),"tb12_process_lane_parent_changed");
const runId="repair-"+new Date().toISOString().replace(/[:.]/g,"-");
const output=join(ROOT,"docs/repair-2026-10-09/tb12-runs-v1",runId),selected=manifest.taskIds.filter((_:string,index:number)=>index%2===lane);
const envelope=BigInt(manifest.actualAvailableCashEnvelopeNanoCny)/2n,owned={...parent,runId,pid:process.pid,ownerNonce:randomBytes(24).toString("hex")};
const sourcePins=[...executedSources(),actualPin(import.meta.path)];
const proofPin=durable(join(output,"fast-admission.json"),{protocol:"paid-resource-admission-v2",scope:"production",runId,owned,sourcePins,
  selectedNewEnvelopeNanoCny:envelope.toString(),carryNanoCny:"0",parentRunId:parent.runId,fixedHumanFeeCap:null,independentProcessLane:true});
durable(join(master,"process-lane-"+lane+".json"),{lane,runId,output,selected,proofPin,
  initialLaneRetriedForInfrastructureOnly:true,reason:"Parent process-wide grader token collision; isolated process prevents contamination"});
const lease:any={protocol:"paid-resource-admission-v2",root:ROOT,runId,path:lock,proofPin,owned,envelopeNanoCny:envelope,
  balanceNanoCny:envelope,headroomNanoCny:0n,carryNanoCny:0n,carry:[],clock:REAL_CLOCK,scope:"production",sourcePins,
  assertOwned,validateForwardSource(){assertOwned();},registerCash(pin:any){durable(join(output,"fast-cash-registration.json"),{pin,parentRunId:parent.runId});},
  registerOwnedProcess(){assertOwned();},release(){throw Error("Parent owns lifecycle");}};
const found=readFileSync(join(ROOT,".env"),"utf8").match(/^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=\s*(.*?)\s*$/m);
demand(found,"tb12_process_lane_credential");const providerKey=found[1].replace(/^(['"])(.*)\1$/,"$2");
const records:any[]=[];
console.log(JSON.stringify({output,selected,lane,independentProcess:true}));
const result=await executePaired({kind:"real-provider",runId,output,sourcePins,
  prices:actualPin(join(ROOT,"docs/repair-2026-10-09/tb12-preparation-v1/price-observations/20261009T0959/prices.json")),
  admission:lease,providerKey,initialDelivery:true,realTaskIds:selected,onRecord(record){
    records.push({taskId:record.officialId,arm:record.arm,passed:record.acceptance.passed,outcome:record.acceptance.outcome,
      valid:record.acceptance.valid,generationValid:record.generationValid,originalFinalGradePerformed:record.generation.kind!=="experimental_failure",
      modelRequests:record.calls.filter((row:any)=>row.providerAttempted).length,rawRecordPin:actualPin(join(output,"task-"+record.index+".json"))});
    durable(join(master,"process-lane-"+lane+"-results.json"),{lane,runId,output,records},true);
    console.log(JSON.stringify({lane,taskId:record.officialId,arm:record.arm,passed:record.acceptance.passed,valid:record.acceptance.valid}));
  }});
durable(join(master,"process-lane-"+lane+"-closed.json"),{lane,runId,output,...result});
console.log(JSON.stringify({lane,complete:result.complete,output}));process.exitCode=result.complete?0:2;
