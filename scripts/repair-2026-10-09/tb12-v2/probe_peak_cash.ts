/** Synthetic arithmetic only: no provider, no canonical lock, no candidate. */
import { randomBytes } from "node:crypto";
import { join, resolve } from "node:path";
import { createCampaignJournal } from "../../repair-2026-10-08/campaign-journal.ts";
import { actualPin, demand, jsonPin, REAL_CLOCK } from "../../repair-2026-10-08/paid-resource-proof-v2.ts";
import { createCnyCashShadow, verifyCashClosure } from "./peak_cash_shadow.ts";
import { durable } from "./paid_admission.ts";
const ROOT=resolve(import.meta.dir,"../../.."),nonce=randomBytes(24).toString("hex");
const home=join(ROOT,"docs/repair-2026-10-09/tb12-preparation-v1/peak-cash-controls",nonce);
const runId="repair-"+new Date().toISOString().replace(/[:.]/g,"-");
const owned={ownerNonce:nonce,pid:process.pid,runId,mode:"arithmetic-fixture-not-paid"};
const proof=durable(join(home,"fixture-admission.json"),{protocol:"paid-resource-admission-v2",scope:"f-fixture",runId,owned,
  selectedNewEnvelopeNanoCny:"1000000000",carryNanoCny:"0",realFinancialAdmission:false});
let cashPin:any;
const lease:any={protocol:"paid-resource-admission-v2",root:ROOT,runId,path:join(home,"fixture-only-not-canonical.json"),proofPin:proof,owned,
  envelopeNanoCny:1000000000n,balanceNanoCny:1000000000n,headroomNanoCny:0n,carryNanoCny:0n,carry:[],clock:REAL_CLOCK,scope:"f-fixture",sourcePins:[],
  assertOwned(){demand(jsonPin(proof).owned.ownerNonce===nonce,"tb12_fixture_pin");},validateForwardSource(){},
  registerCash(pin:any){demand(!cashPin,"tb12_fixture_duplicate");cashPin=pin;},registerOwnedProcess(){throw Error("No fixture child processes");},release(){throw Error("No canonical release in arithmetic fixture");}};
const directory=join(home,"provider"),journal=createCampaignJournal({directory,campaign:runId,capUsd:1,priorCampaignCostUpperBoundUsd:0,outputDirectory:directory});
const shadow=createCnyCashShadow({directory:join(home,"cash"),runId,providerKind:"real-provider",admission:lease,
  prices:actualPin(join(ROOT,"docs/repair-2026-10-09/tb12-preparation-v1/price-observations/20261009T0959/prices.json")),
  journal:{directory,configPin:actualPin(join(directory,"journal-config.json")),sourcePin:actualPin(join(ROOT,"scripts/repair-2026-10-08/campaign-journal.ts"))}});
const request=JSON.stringify({model:"deepseek-flash",messages:[{role:"user",content:"Synthetic arithmetic fixture. No connection to a provider."}],
  temperature:0,seed:42,reasoning_effort:"none",thinking:{type:"disabled"},max_tokens:8192,stream:false});
const admitted=journal.admit({route:"synthetic-only",rawRequest:request});demand(admitted.admitted,"tb12_fixture_start");
const start=jsonPin(actualPin(join(directory,"api-state.json")));
const ticket=shadow.beforeForward({id:runId+"/0",route:"synthetic-only",rawRequest:Buffer.from(request),
  journal:{admitted:admitted as any,startPrefix:start.durablePrefix},capturedRequest:actualPin((admitted as any).requestFile)});
demand(ticket.admitted,"tb12_fixture_cash_start");
const before=journal.snapshot().durablePrefix.bytes;
const usage={prompt_tokens:1000,completion_tokens:100,total_tokens:1100,prompt_cache_hit_tokens:100,prompt_cache_miss_tokens:900};
const rawResponse=JSON.stringify({id:"explicit-synthetic-price-fixture",model:"deepseek-flash",usage,
  choices:[{index:0,finish_reason:"stop",message:{role:"assistant",content:"Synthetic response; no network request."}}]});
journal.finish({requestSeq:(admitted as any).requestSeq,providerAttempted:true,httpStatus:200,rawResponse});
const finish=journal.snapshot().durablePrefix;
shadow.finish(ticket.ticket,{kind:"journal-finish",journalRef:{finishOffset:before,finishEnd:finish.bytes,finishLineSha256:finish.lastSha256}});
const close=shadow.close(),checked=verifyCashClosure(close);
demand(checked.config.scope==="f-fixture"&&checked.config.pricingMode==="published-peak-conservative-upper-bound"&&checked.proof.snapshot.newKnownEstimatedNanoCny==="2604000","tb12_actual_peak_arithmetic_replay");
const exported=journal.exportLegacyLedger();journal.close();
const report=durable(join(home,"probe.json"),{protocol:"tb12-synthetic-peak-arithmetic-control-v1",validated:true,
  actualProviderRequests:0,modelCalls:0,canonicalLockOperations:0,syntheticAttemptFlagUsedOnlyForArithmetic:true,
  usage,expectedPeakNanoCny:"2604000",cashClosePin:close,exportedPin:exported,source:actualPin(import.meta.path)});
console.log(JSON.stringify({report,validated:true,modelCalls:0,canonicalLockOperations:0}));
