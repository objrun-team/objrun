import { expect, test } from 'bun:test';
import { createHash, randomBytes } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { gzipSync } from 'node:zlib';
import { actualPin } from '../../../benchmark-repair/paid-resource-proof-v2.ts';
import { resolveUnknownReceipt } from './cash-reconciliation.ts';
const root=resolve(import.meta.dir,'../../../..'),dir=join(root,'.scratch/full-f-reconciliation-tests',randomBytes(8).toString('hex'));
mkdirSync(dir,{recursive:true});
const hash=(value:Buffer)=>createHash('sha256').update(value).digest('hex');
const payload={id:'synthetic-local-generation',provider:'Relace',model:'deepseek/deepseek-v4.1-flash',choices:[{index:0,finish_reason:'stop',message:{role:'assistant',content:'42'}}],usage:{prompt_tokens:10,completion_tokens:2,total_tokens:12,cost:0.0000054}};
const bodyPath=join(dir,'late-provider.json');writeFileSync(bodyPath,JSON.stringify(payload));
const response={requestSeq:65,httpStatus:200,responsePin:actualPin(bodyPath),generationId:payload.id,billedUsd:payload.usage.cost};
const record={requestSha256:'captured-request-sha',reservationUsd:0.0225024};
const dispatch={requestSeq:65,requestSha256:record.requestSha256};

test('a complete late receipt recovers actual USD cost while preserving the original conservative record',()=>{
  const before=JSON.stringify(record),resolved=resolveUnknownReceipt(record,65,dispatch,response,true);
  expect(resolved.actualCostUsd).toBe(0.0000054);expect(resolved.generationId).toBe(payload.id);expect(JSON.stringify(record)).toBe(before);
});
test('late receipt rejects request/generation/cost mismatches and missing completion',()=>{
  expect(()=>resolveUnknownReceipt(record,65,{...dispatch,requestSha256:'wrong'},response,true)).toThrow('dispatch_request_mismatch');
  expect(()=>resolveUnknownReceipt(record,65,dispatch,{...response,generationId:'another'},true)).toThrow('late_response_cost_or_id_mismatch');
  expect(()=>resolveUnknownReceipt(record,65,dispatch,{...response,billedUsd:0},true)).toThrow('late_response_cost_or_id_mismatch');
  expect(()=>resolveUnknownReceipt(record,65,dispatch,undefined,true)).toThrow('late_complete_response_required');
});
test('absence of a dispatch cannot settle an active broker or a real provider response as zero',()=>{
  expect(()=>resolveUnknownReceipt(record,65,undefined,undefined,false)).toThrow('broker_generation_not_fenced');
  expect(()=>resolveUnknownReceipt({...record,httpStatus:200,responseFile:bodyPath},65,undefined,undefined,true)).toThrow('unforwarded_rejection_evidence_required');
});
test('only bound stopped-broker bytes and no dispatch settle a local rejected request as zero',()=>{
  const raw=Buffer.from(JSON.stringify({error:{message:'Shared Bench broker stopped',code:'bench_broker_stopped'}})),zipped=gzipSync(raw),path=join(dir,'local-response.gz');writeFileSync(path,zipped);
  const local={...record,httpStatus:503,responseFile:path,responseCompressedSha256:hash(zipped),responseSha256:hash(raw)};
  const resolved=resolveUnknownReceipt(local,66,undefined,undefined,true);expect(resolved.actualCostUsd).toBe(0);expect(resolved.classification).toBe('fenced_broker_never_dispatched');
  expect(()=>resolveUnknownReceipt({...local,responseSha256:'tampered'},66,undefined,undefined,true)).toThrow('local_rejection_bytes_changed');
  expect(()=>resolveUnknownReceipt(local,66,{requestSeq:66,requestSha256:record.requestSha256},undefined,true)).toThrow('late_complete_response_required');
});
