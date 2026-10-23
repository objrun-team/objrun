import { expect, test } from "bun:test";
import { closeSync, existsSync, readFileSync, writeFileSync, appendFileSync, mkdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { createHash, randomBytes } from "node:crypto";
import { gunzipSync } from "node:zlib";
import { createCampaignJournal, inspectCampaignJournal, type JournalIoOperation } from "../scripts/benchmark-repair/campaign-journal.ts";

const base = resolve(import.meta.dir, "../.scratch", `campaign-journal-${randomBytes(6).toString("hex")}`);
mkdirSync(base, { recursive: true });
const campaign = "repair-2026-10-08T00-00-00-000Z";
const rawRequest = JSON.stringify({ model: "deepseek-flash", max_tokens: 32, temperature: 0, seed: 42, reasoning_effort: "none", messages: [{ role: "user", content: "synthetic local receipt" }] });
const rawResponse = (id: string, prompt = 10, completion = 2) => JSON.stringify({ id, model: "local-file-fixture", choices: [{ message: { role: "assistant", content: "synthetic" } }], usage: { prompt_tokens: prompt, completion_tokens: completion } });
const sha = (raw: string | Buffer) => createHash("sha256").update(raw).digest("hex");
const reports: unknown[] = [];
function fixture(name: string, hooks?: { before?: (op: JournalIoOperation) => void; after?: (op: JournalIoOperation) => void }, cap = 1) {
  const directory = join(base, name); mkdirSync(directory);
  return { directory, journal: createCampaignJournal({ directory, campaign, capUsd: cap, priorCampaignCostUpperBoundUsd: 0.1 }, hooks) };
}
function finish(j: ReturnType<typeof createCampaignJournal>, seq: number, id: string, prompt = 10) { return j.finish({ requestSeq: seq, providerAttempted: true, httpStatus: 200, rawResponse: rawResponse(id, prompt) }); }
function save(name: string, directory: string, details: unknown) { reports.push({ name, directory, details }); writeFileSync(join(base, "results.json"), JSON.stringify({ formalRun: false, apiCalled: false, networkCalled: false, dockerCalled: false, eWrite: false, fixtures: reports }, null, 2)+"\n"); }

test("four real raw captures, serial fsync and out-of-order finish export current ledger fields", () => {
  const operations: JournalIoOperation[] = [];
  const {directory,journal:j}=fixture("four-pending",{after:o=>operations.push({...o})});
  const tickets=Array.from({length:4},(_,i)=>j.admit({route:`${campaign}/chemiq/F/0/fixture-${i}`,rawRequest}));
  expect(tickets.every(t=>t.admitted)).toBe(true);
  expect(j.admit({route:"fifth",rawRequest})).toMatchObject({admitted:false,reason:"pending_limit"});
  expect(Object.values(j.snapshot().pending).reduce((a,b)=>a+b,0)).toBe(4);
  for(const seq of [2,0,3,1]) finish(j,seq,`response-${seq}`);
  const s=j.snapshot(); expect(s.reservedUpperBoundUsd).toBe(0);expect(s.pending).toEqual({});
  expect(s.recordedUsageUpperBoundUsd).toBeCloseTo(4*0.0000054,12);
  const exported=j.exportLegacyLedger();
  expect(exported.accountingClosed).toBe(true);
  const ledger=JSON.parse(readFileSync(exported.path,"utf8"));
  expect(ledger.calls.map((c:any)=>c.requestId)).toEqual(["response-0","response-1","response-2","response-3"]);
  expect(ledger.calls.map((c:any)=>sha(gunzipSync(readFileSync(c.requestFile))))).toEqual(Array(4).fill(sha(rawRequest)));
  expect(ledger.calls.reduce((s:number,c:any)=>s+c.usdUpperBound,0)).toBeCloseTo(ledger.recordedUsageUpperBoundUsd,12);
  expect([...j.closedCalls(`${campaign}/chemiq/F/0/fixture-2`)].map(c=>c.requestId)).toEqual(["response-2"]);
  expect(operations.filter(o=>o.kind==="fsync"&&o.stage.startsWith("raw_request")).length).toBe(4);
  const stages=operations.filter(o=>o.kind==="fsync").map(o=>o.stage);
  const start=stages.indexOf("journal:start:0");
  expect(stages.indexOf("raw_request:0")).toBeLessThan(start);
  expect(stages.indexOf("checkpoint:start:0")).toBeGreaterThan(start);
  expect(inspectCampaignJournal(directory).valid).toBe(true);
  save("four_real_captures_serial_fsync_out_of_order_export",directory,{snapshot:s,exported,operations});j.close();
});

test("budget and four-pending checks admit nothing and never call provider or release a lock", () => {
  const {directory,journal:j}=fixture("cap",undefined,0.100001);
  expect(j.admit({route:"cost-rejected",rawRequest})).toMatchObject({admitted:false,reason:"local_budget_exhausted"});
  expect(j.snapshot().acceptedRequestCount).toBe(0);
  expect(existsSync(join(directory,"provider-0-request.json.gz"))).toBe(false);
  const lock=join(directory,"owned-paid-campaign.lock.json");writeFileSync(lock,'{"owned":"outside-module"}');
  j.close();expect(readFileSync(lock,"utf8")).toBe('{"owned":"outside-module"}');
  save("cap_reject_and_external_lock_untouched",directory,j.snapshot());
});

test("actual initialization fsync error is typed and preserves its exclusive config", () => {
  const directory=join(base,"initialization-fsync-failure");mkdirSync(directory);
  expect(()=>createCampaignJournal({directory,campaign,capUsd:1,priorCampaignCostUpperBoundUsd:0.1},{before:o=>{if(o.stage==="config"&&o.kind==="fsync")closeSync(o.fd!);}})).toThrow("journal_create_io");
  expect(existsSync(join(directory,"journal-config.json"))).toBe(true);
  expect(()=>createCampaignJournal({directory,campaign,capUsd:1,priorCampaignCostUpperBoundUsd:0.1})).toThrow("existing_journal");
  expect(inspectCampaignJournal(directory).accountingClosed).toBe(false);
  save("actual_init_fsync_EBADF_config_preserved",directory,inspectCampaignJournal(directory));
});

test("actual EBADF fsync after durable start keeps reservation and rejects new admission", () => {
  let fired=false; const operations:JournalIoOperation[]=[];
  const {directory,journal:j}=fixture("start-checkpoint-failure",{before:o=>{if(!fired&&o.kind==="fsync"&&o.stage==="checkpoint:start:0"){fired=true;closeSync(o.fd!);}},after:o=>operations.push({...o})});
  expect(()=>j.admit({route:"unacknowledged-start",rawRequest})).toThrow("checkpoint_io");
  const s=j.snapshot();expect(s.acceptedRequestCount).toBe(1);expect(s.reservedUpperBoundUsd).toBeGreaterThan(0);expect(s.recordedUsageUpperBoundUsd).toBe(0);
  expect(()=>j.admit({route:"later",rawRequest})).toThrow("journal_poisoned");
  expect(inspectCampaignJournal(directory)).toMatchObject({valid:false,accountingClosed:false});
  expect(readFileSync(join(directory,"api-events.jsonl"),"utf8").trim().split("\n").length).toBe(1);
  expect(operations.some(o=>o.kind==="fsync"&&o.stage==="journal:start:0")).toBe(true);
  save("real_fsync_EBADF_after_durable_start",directory,{snapshot:s,operations,inspection:inspectCampaignJournal(directory)});j.close();
});

test("durable finish then failed checkpoint preserves actual cost, not zero or a second charge", () => {
  let fired=false;
  const {directory,journal:j}=fixture("finish-checkpoint-failure",{before:o=>{if(!fired&&o.kind==="fsync"&&o.stage==="checkpoint:finish:0"){fired=true;closeSync(o.fd!);}}});
  j.admit({route:"charged-finish",rawRequest});
  expect(()=>finish(j,0,"finish-is-durable")).toThrow("checkpoint_io");
  const s=j.snapshot();expect(s.finishedRequestCount).toBe(1);expect(s.reservedUpperBoundUsd).toBe(0);expect(s.recordedUsageUpperBoundUsd).toBeCloseTo(0.0000054,12);
  expect(()=>finish(j,0,"again")).toThrow("journal_poisoned");
  expect(j.snapshot().recordedUsageUpperBoundUsd).toBe(s.recordedUsageUpperBoundUsd);
  expect(inspectCampaignJournal(directory)).toMatchObject({valid:false,accountingClosed:false});
  save("real_fsync_EBADF_after_durable_finish",directory,{snapshot:s,inspection:inspectCampaignJournal(directory)});j.close();
});

test("actual post-fsync descriptor failure cannot conceal a durable finish cost", () => {
  let fired=false;
  const {directory,journal:j}=fixture("post-fsync-identity-failure",{after:o=>{if(!fired&&o.kind==="fsync"&&o.stage==="journal:finish:0"){fired=true;closeSync(o.fd!);}}});
  j.admit({route:"durable-finish",rawRequest});expect(()=>finish(j,0,"durable-bill")).toThrow("journal_identity_io");
  expect(j.snapshot().finishedRequestCount).toBe(1);expect(j.snapshot().reservedUpperBoundUsd).toBe(0);expect(j.snapshot().recordedUsageUpperBoundUsd).toBeCloseTo(0.0000054,12);
  expect(()=>j.admit({route:"new",rawRequest})).toThrow("journal_poisoned");expect(inspectCampaignJournal(directory).accountingClosed).toBe(false);
  save("actual_fstat_EBADF_after_finish_fsync",directory,j.snapshot());j.close();
});

test("partial actual journal write is retained and cannot be reopened, exported or retried", () => {
  let fired=false;
  const {directory,journal:j}=fixture("partial-write",{before:o=>{if(!fired&&o.kind==="write"&&o.stage==="journal:start:0"){fired=true;writeFileSync(o.fd!,Buffer.from('{"partial":'));closeSync(o.fd!);}}});
  expect(()=>j.admit({route:"partial",rawRequest})).toThrow("journal_io");
  expect(readFileSync(join(directory,"api-events.jsonl"),"utf8")).toBe('{"partial":');
  expect(()=>j.exportLegacyLedger()).toThrow();
  expect(()=>createCampaignJournal({directory,campaign,capUsd:1,priorCampaignCostUpperBoundUsd:0.1})).toThrow("existing_journal");
  expect(inspectCampaignJournal(directory)).toMatchObject({valid:false,accountingClosed:false});
  save("actual_partial_write_preserved_fail_closed",directory,j.snapshot());j.close();
});

test("unknown or duplicate finish and duplicate/truncated disk events refuse certification", () => {
  for(const mode of ["duplicate_finish","unknown_finish","duplicate_disk","truncated_disk"]){
    const {directory,journal:j}=fixture(mode);j.admit({route:mode,rawRequest});finish(j,0,mode);
    if(mode==="duplicate_finish") expect(()=>finish(j,0,"double")).toThrow("duplicate_finish");
    if(mode==="unknown_finish") expect(()=>finish(j,4,"unknown")).toThrow("unknown_finish");
    if(mode==="duplicate_disk") appendFileSync(join(directory,"api-events.jsonl"),readFileSync(join(directory,"api-events.jsonl"),"utf8").split("\n")[0]+"\n");
    if(mode==="truncated_disk") {const p=join(directory,"api-events.jsonl");const raw=readFileSync(p);writeFileSync(p,raw.subarray(0,raw.length-1));}
    expect(()=>j.exportLegacyLedger()).toThrow();expect(inspectCampaignJournal(directory).valid).toBe(false);
    save(mode,directory,{snapshot:j.snapshot(),inspection:inspectCampaignJournal(directory)});j.close();
  }
});

test("unknown transport is attributable, no-forward is explicitly zero, and excess usage is retained", () => {
  for(const mode of ["transport","unforwarded","usage_over_reserve"]){
    const {directory,journal:j}=fixture(mode);j.admit({route:mode,rawRequest});const reserve=j.snapshot().reservedUpperBoundUsd;
    if(mode==="transport")j.finish({requestSeq:0,providerAttempted:true,fault:"ProviderTransportError"});
    if(mode==="unforwarded")j.finish({requestSeq:0,providerAttempted:false,confirmedNoForward:true,fault:"LocalBeforeForwardError"});
    if(mode==="usage_over_reserve")finish(j,0,mode,1_000_000);
    const s=j.snapshot();expect(s.reservedUpperBoundUsd).toBe(0);
    if(mode==="transport")expect(s.recordedUsageUpperBoundUsd).toBe(reserve);
    if(mode==="unforwarded")expect(s.recordedUsageUpperBoundUsd).toBe(0);
    if(mode==="usage_over_reserve")expect(s.recordedUsageUpperBoundUsd).toBeCloseTo(0.3000024,12);
    expect(j.admit({route:"later",rawRequest}).admitted).toBe(false);
    expect(j.exportLegacyLedger().accountingClosed).toBe(true);
    save(mode,directory,s);j.close();
  }
});

test("raw corruption after response, or export fsync failure, cannot certify a completed ledger", () => {
  for(const mode of ["raw_corruption","export_fsync_failure"]){
    let fired=false;
    const {directory,journal:j}=fixture(mode,{before:o=>{if(mode==="export_fsync_failure"&&!fired&&o.kind==="fsync"&&o.stage==="legacy_export"){fired=true;closeSync(o.fd!);}}});
    j.admit({route:mode,rawRequest});finish(j,0,mode);
    if(mode==="raw_corruption")appendFileSync(join(directory,"provider-0-response.json.gz"),"corrupt");
    expect(()=>j.exportLegacyLedger()).toThrow();expect(existsSync(join(directory,"api-ledger.json"))).toBe(false);
    expect(inspectCampaignJournal(directory).valid).toBe(false);save(mode,directory,j.snapshot());j.close();
  }
});

test("truncated checkpoint is retained and cannot be silently replaced by a later admission", () => {
  const {directory,journal:j}=fixture("checkpoint-corruption");j.admit({route:"first",rawRequest});finish(j,0,"first");
  const p=join(directory,"api-state.json");writeFileSync(p,'{"truncated":');
  expect(()=>j.admit({route:"later",rawRequest})).toThrow("checkpoint_changed");
  expect(readFileSync(p,"utf8")).toBe('{"truncated":');expect(existsSync(join(directory,"provider-1-request.json.gz"))).toBe(false);
  expect(inspectCampaignJournal(directory).valid).toBe(false);save("checkpoint_corruption_refuses_new_admission",directory,j.snapshot());j.close();
});

test("excess actual cost stops new admission but still records every already admitted finish", () => {
  const {directory,journal:j}=fixture("four-cost-spill");for(let i=0;i<4;i++)j.admit({route:`already-${i}`,rawRequest});
  finish(j,2,"cost-spill",4_000_000);
  expect(j.admit({route:"new",rawRequest})).toMatchObject({admitted:false,reason:"usage_exceeded_reservation"});
  for(const seq of [0,3,1])finish(j,seq,`settled-${seq}`);
  const s=j.snapshot();expect(s.recordedUsageUpperBoundUsd).toBeGreaterThan(1);expect(s.finishedRequestCount).toBe(4);expect(s.reservedUpperBoundUsd).toBe(0);
  const proof=j.exportLegacyLedger();expect(proof.accountingClosed).toBe(true);expect(proof.eligibleForScoreCertification).toBe(false);
  const data=JSON.parse(readFileSync(proof.path,"utf8"));expect(data.calls.length).toBe(4);expect(data.fatal).toBe("usage_exceeded_reservation");
  save("over_cap_actual_cost_and_prior_calls_all_preserved",directory,{snapshot:s,proof});j.close();
});

test("all route names retain positive pending counts, including prototype-like strings", () => {
  const {directory,journal:j}=fixture("positive-pending-keys");
  for(const route of ["__proto__","constructor","__proto__","toString"])j.admit({route,rawRequest});
  expect(Object.values(j.snapshot().pending).reduce((a,b)=>a+b,0)).toBe(4);
  expect(j.snapshot().pending["__proto__"]).toBe(2);
  for(const i of [3,1,2,0])finish(j,i,`key-${i}`);
  expect(j.snapshot().pending).toEqual({});expect(inspectCampaignJournal(directory).valid).toBe(true);
  save("prototype_like_routes_positive_pending",directory,j.snapshot());j.close();
});

test("300 real-file receipts keep bounded checkpoints and logical writes linear, then stream export once", () => {
  const {directory,journal:j}=fixture("linear-hot-path");
  for(let i=0;i<300;i++){j.admit({route:`${campaign}/chemiq/F/0/fixture-${i%4}`,rawRequest});finish(j,i,`linear-${i}`);}
  const s=j.snapshot();const checkpoint=JSON.parse(readFileSync(join(directory,"api-state.json"),"utf8"));
  expect(checkpoint.calls).toBeUndefined();expect(statSync(join(directory,"api-state.json")).size).toBeLessThan(8192);
  expect(s.metrics.journalBytesWritten).toBe(statSync(join(directory,"api-events.jsonl")).size);
  expect(s.metrics.journalBytesWritten).toBeLessThan(300*8192);
  expect(s.metrics.checkpointBytesWritten).toBeLessThan(601*8192);
  expect(s.metrics.fsyncCallsReturned).toBeGreaterThanOrEqual(300*6);
  expect(existsSync(join(directory,"api-ledger.json"))).toBe(false);
  const proof=j.exportLegacyLedger();const ledger=JSON.parse(readFileSync(proof.path,"utf8"));expect(ledger.calls.length).toBe(300);
  for(let i=0;i<4;i++)expect([...j.closedCalls(`${campaign}/chemiq/F/0/fixture-${i}`)].length).toBe(75);
  expect(()=>j.exportLegacyLedger()).toThrow("already_exported");
  save("300_real_file_receipts_linear_metadata",directory,{snapshot:j.snapshot(),proof});j.close();
},30000);
