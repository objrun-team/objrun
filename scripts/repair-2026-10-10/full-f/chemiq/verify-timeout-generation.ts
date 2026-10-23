/** Read-only generation metadata GET for an already-billed request, with only the inner .env credential. */
import {readFileSync,writeFileSync,existsSync} from 'node:fs';
import {join} from 'node:path';
import {ROOT,OUT} from './prepare.ts';
import {actualPin,verifyPin,hash} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
const evidence=JSON.parse(readFileSync(join(OUT,'diagnostics/unknown-charge-investigation.json'),'utf8'));
const received=evidence.brokerEvents.find((e:any)=>e.kind==='response'&&e.requestSeq===65);
if(!received?.responsePin)throw Error('No complete captured provider response');verifyPin(received.responsePin);
const response=JSON.parse(readFileSync(received.responsePin.path,'utf8'));
const filename=join(OUT,'diagnostics/request65-generation-metadata.json');
if(existsSync(filename)){console.log(JSON.stringify({alreadyVerified:true,file:filename}));process.exit(0);}
const line=readFileSync(join(ROOT,'.env'),'utf8').split(/\r?\n/).find(v=>/^\s*(export\s+)?OPENROUTER_API_KEY\s*=/.test(v));
if(!line)throw Error('Inner .env credential missing');const key=line.slice(line.indexOf('=')+1).trim().replace(/^(['"])(.*)\1$/,'$2');
const uri='https://openrouter.ai/api/v1/generation?id='+encodeURIComponent(response.id);
const cached=join(OUT,'diagnostics/request65-generation-metadata-raw.json');
const result=existsSync(cached)?new Response(readFileSync(cached,'utf8'),{status:200}):await fetch(uri,{headers:{authorization:'Bearer '+key},signal:AbortSignal.timeout(30000)}),raw=await result.text();
if(!result.ok)throw Error('Generation metadata HTTP '+result.status);const metadata=JSON.parse(raw);
writeFileSync(join(OUT,'diagnostics/request65-generation-metadata-raw.json'),raw);
const costDeltaUsd=metadata.data.total_cost-response.usage.cost;
if(metadata.data?.id!==response.id||Math.abs(costDeltaUsd)>1e-9||metadata.data.provider_name!=='Relace')throw Error('Metadata identity/provider/cost mismatch beyond 1e-9 USD precision bound');
const originalStart=evidence.originalJournalEvents.find((e:any)=>e.kind==='start'&&e.requestSeq===65),brokerDispatch=evidence.brokerEvents.find((e:any)=>e.kind==='dispatch'&&e.requestSeq===65);
if(originalStart.record.requestSha256!==brokerDispatch.requestSha256)throw Error('Broker and local request hash mismatch');
writeFileSync(filename,JSON.stringify({protocol:'chemiq-readonly-generation-cost-verification-v1',observedAtUtc:new Date().toISOString(),method:'GET',url:uri,httpStatus:result.status,rawResponseSha256:hash(raw),metadata,capturedResponsePin:received.responsePin,requestSha256:brokerDispatch.requestSha256,generationId:response.id,costUsd:response.usage.cost,metadataCostUsd:metadata.data.total_cost,costDeltaUsd,costsExactlyEqual:costDeltaUsd===0,costsWithinPrecisionBound:Math.abs(costDeltaUsd)<=1e-9,precisionBoundUsd:1e-9,costAuthority:'raw usage.cost kept at full precision; metadata reports 9 decimal places',verified:true,modelCalls:0,originalUnknownLedgerUnmodified:true,notCashReleaseCertification:true},null,2)+'\n');
console.log(JSON.stringify({verified:true,generationId:response.id,costUsd:response.usage.cost,provider:metadata.data.provider_name,modelCalls:0}));
