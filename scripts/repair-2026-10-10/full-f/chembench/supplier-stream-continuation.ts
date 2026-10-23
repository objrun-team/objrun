/** Offline-prepared transport adapter. No fetch, credentials, admission or broker creation. */
import { closeSync, fsyncSync, mkdirSync, openSync, writeFileSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { gzipSync, gunzipSync } from 'node:zlib';
import { createHash } from 'node:crypto';
import { CapturedTransportFailure } from '../../../repair-2026-10-08/scientific-journal-proxy.ts';
import { verifyPin } from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';

import {supplierProfile} from '../shared/chembench-supplier-profiles.ts';
const MODEL='deepseek/deepseek-v4.1-flash';
const hash=(raw:Uint8Array|string)=>createHash('sha256').update(raw).digest('hex');
const demand=(ok:unknown,code:string)=>{if(!ok)throw new Error(code);};
export function makeApprovedSupplierStreamingWireRequest(originalRequest:string):string {
  const r=JSON.parse(originalRequest);
  const slug=r.provider?.only?.[0];demand(['relace','dekallm','wafer'].includes(slug),'CBStreamingRoutingMismatch');
  demand(r.model===MODEL&&JSON.stringify(r.provider?.only)===JSON.stringify([slug])&&r.provider?.allow_fallbacks===false,'CBStreamingRoutingMismatch');
  demand(r.reasoning?.effort==='high'&&r.reasoning.enabled===true,'CBStreamingReasoningMismatch');
  return JSON.stringify({...r,stream:true,stream_options:{...r.stream_options,include_usage:true}});
}
export type SSECaptureOptions={originalRequest:string;wireRequest:string;evidencePrefix:string;maxBytes?:number};
function persist(path:string,raw:Uint8Array|string){mkdirSync(dirname(path),{recursive:true});const fd=openSync(path,'wx',0o600);try{writeFileSync(fd,raw);fsyncSync(fd);}finally{closeSync(fd);}return{path,bytes:Buffer.byteLength(raw),sha256:hash(raw)};}

/** Paid dispatch is exclusively invoked by the single owned shared broker. Never logs key. */
export async function captureApprovedSupplierStream(raw:string,key:string,evidenceDir:string):Promise<{httpStatus:number;rawResponse:string}> {
  const wireRequest=makeApprovedSupplierStreamingWireRequest(raw);
  const dispatch:any={protocol:'chembench-stream-wire-dispatch-v1',startedAtUtc:new Date().toISOString(),timeoutMs:600000,
    originalRequest:persist(join(evidenceDir,'dispatch.original-request.json.gz'),gzipSync(raw)),
    wireRequest:persist(join(evidenceDir,'dispatch.wire-request.json.gz'),gzipSync(wireRequest)),originalRequestSha256:hash(raw),wireRequestSha256:hash(wireRequest)};
  try {
    const response=await fetch('https://openrouter.ai/api/v1/chat/completions',{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+key,'X-OpenRouter-Title':'TgEngin Bench'},body:wireRequest,signal:AbortSignal.timeout(600000)});
    dispatch.headersAtUtc=new Date().toISOString();dispatch.httpStatus=response.status;
    const result=await captureApprovedSupplierSSE(response,{originalRequest:raw,wireRequest,evidencePrefix:join(evidenceDir,'capture')});
    dispatch.finishedAtUtc=new Date().toISOString();dispatch.capture=result.evidence;persist(join(evidenceDir,'dispatch.evidence.json'),JSON.stringify(dispatch,null,2)+'\n');return result;
  } catch(error){dispatch.finishedAtUtc=new Date().toISOString();dispatch.errorName=error instanceof Error?error.name:null;dispatch.errorCode=typeof (error as any)?.code==='string'?(error as any).code:null;persist(join(evidenceDir,'dispatch.evidence.json'),JSON.stringify(dispatch,null,2)+'\n');throw error;}
}

/** Caller sends wireRequest through its owned shared broker, then supplies the real response. */
export async function captureApprovedSupplierSSE(response:Response,options:SSECaptureOptions):Promise<{httpStatus:number;rawResponse:string;evidence:any}> {
  demand(options.wireRequest===makeApprovedSupplierStreamingWireRequest(options.originalRequest),'CBStreamingWireChanged');
  const limit=options.maxBytes??64*1024**2;demand(Number.isSafeInteger(limit)&&limit>0&&limit<=64*1024**2,'CBStreamingCaptureLimit');
  const chunks:Uint8Array[]=[];let bytes=0,bodyComplete=false;
  const evidence:any={protocol:'chembench-sse-capture-v1',httpStatus:response.status,atUtc:new Date().toISOString(),
    originalRequest:persist(options.evidencePrefix+'.original-request.json.gz',gzipSync(options.originalRequest)),
    wireRequest:persist(options.evidencePrefix+'.wire-request.json.gz',gzipSync(options.wireRequest)),
    originalRequestSha256:hash(options.originalRequest),wireRequestSha256:hash(options.wireRequest)};
  const decoder=new TextDecoder('utf-8',{fatal:true});let frameBuffer='';
  const observe=(chunk:Uint8Array)=>{const now=new Date().toISOString();evidence.firstByteAtUtc??=now;frameBuffer+=decoder.decode(chunk,{stream:true});let boundary:number;while((boundary=frameBuffer.replace(/\r\n/g,'\n').indexOf('\n\n'))>=0){frameBuffer=frameBuffer.replace(/\r\n/g,'\n');const frame=frameBuffer.slice(0,boundary);frameBuffer=frameBuffer.slice(boundary+2);const data=frame.split('\n').filter(l=>l.startsWith('data:')).map(l=>l.slice(5).replace(/^ /,'')).join('\n');if(!data)continue;evidence.lastDataFrameAtUtc=now;if(data.trim()==='[DONE]'){evidence.doneAtUtc=now;continue;}evidence.firstDataAtUtc??=now;try{const v=JSON.parse(data);if(v.choices?.some((c:any)=>c.delta?.reasoning||c.delta?.reasoning_content||c.delta?.reasoning_details?.length))evidence.firstReasoningAtUtc??=now;}catch{}}};
  const saveRaw=()=>{const raw=Buffer.concat(chunks,bytes);evidence.rawResponseSha256=hash(raw);evidence.rawResponseBytes=raw.length;evidence.rawSSE=persist(options.evidencePrefix+'.response.raw.gz',gzipSync(raw));evidence.bodyComplete=bodyComplete;return raw;};
  let raw:Buffer;
  try{
    const reader=response.body?.getReader();if(reader)while(true){const value=await reader.read();if(value.done)break;const remain=limit-bytes;chunks.push(value.value.subarray(0,remain));bytes+=Math.min(remain,value.value.length);if(value.value.length>remain){await reader.cancel();throw Error('CBStreamingResponseTooLarge');}observe(value.value);}
    decoder.decode();bodyComplete=true;evidence.bodyFinishedAtUtc=new Date().toISOString();raw=saveRaw();
  }catch(error){raw=saveRaw();evidence.fault=error instanceof Error?error.message:'CBStreamingBodyReadError';persist(options.evidencePrefix+'.evidence.json',JSON.stringify(evidence,null,2)+'\n');throw new CapturedTransportFailure({httpStatus:response.status,rawBytes:raw,bodyComplete:false,fault:evidence.fault});}
  try{
    const text=new TextDecoder('utf-8',{fatal:true}).decode(raw);
    let aggregate:string;
    // A provider may return a complete JSON error despite requesting SSE. Preserve it verbatim.
    if(text.trimStart().startsWith('{')){const v=JSON.parse(text);demand(v.error,'CBStreamingUnexpectedNonSSESuccess');aggregate=text;evidence.providerError=true;}
    else{const parsed=aggregateSSE(text,supplierProfile(JSON.parse(options.originalRequest).provider.only[0]).providerName);aggregate=parsed.rawResponse;evidence.providerError=parsed.providerError;}
    evidence.aggregateSha256=hash(aggregate);evidence.aggregate=persist(options.evidencePrefix+'.aggregate.json',aggregate);evidence.complete=true;
    persist(options.evidencePrefix+'.evidence.json',JSON.stringify(evidence,null,2)+'\n');return{httpStatus:response.status,rawResponse:aggregate,evidence};
  }catch(error){const fault=error instanceof Error?error.message:'CBStreamingParseError';evidence.fault=fault;evidence.complete=false;persist(options.evidencePrefix+'.evidence.json',JSON.stringify(evidence,null,2)+'\n');throw new CapturedTransportFailure({httpStatus:response.status,rawBytes:raw,bodyComplete:false,fault});}
}

function aggregateSSE(text:string,expectedProvider:string):{rawResponse:string;providerError:boolean}{
  const normalized=text.replace(/^\uFEFF/,'').replace(/\r\n/g,'\n').replace(/\r/g,'\n');
  demand(normalized.endsWith('\n\n'),'CBStreamingUnterminatedEvent');
  let done=false,id:string|undefined,model:string|undefined,provider:string|undefined,created:number|undefined,usage:any,finish:string|undefined;
  let content='',reasoning='';const tools=new Map<number,{id:string;type:string;function:{name:string;arguments:string}}>();
  const reasoningDetails=new Map<string,any>();let anonymousDetail=0;
  const metadata=(current:string|undefined,next:unknown,code:string)=>{if(next===undefined)return current;demand(typeof next==='string'&&next.length>0,code);demand(!current||current===next,code);return next as string;};
  for(const event of normalized.split('\n\n')){
    const data=event.split('\n').filter(l=>l.startsWith('data:')).map(l=>l.slice(5).replace(/^ /,'')).join('\n');if(!data)continue;
    demand(!done,'CBStreamingDataAfterDone');if(data.trim()==='[DONE]'){done=true;continue;}
    const v=JSON.parse(data);if(v.error)return{rawResponse:data,providerError:true};
    id=metadata(id,v.id,'CBStreamingGenerationChanged');model=metadata(model,v.model,'CBStreamingModelChanged');provider=metadata(provider,v.provider,'CBStreamingProviderChanged');
    if(v.created!==undefined){demand(Number.isFinite(v.created),'CBStreamingCreatedInvalid');created=v.created;}
    if(v.usage!=null){demand(!usage||JSON.stringify(usage)===JSON.stringify(v.usage),'CBStreamingUsageChanged');usage=v.usage;}
    demand(Array.isArray(v.choices),'CBStreamingChoicesMissing');
    for(const choice of v.choices){demand(choice.index===0,'CBStreamingMultipleChoices');if(choice.finish_reason!=null){demand(typeof choice.finish_reason==='string'&&(!finish||finish===choice.finish_reason),'CBStreamingFinishChanged');finish=choice.finish_reason;}
      const d=choice.delta??{};if(d.role!==undefined)demand(d.role==='assistant','CBStreamingRoleInvalid');
      for(const key of ['content','reasoning','reasoning_content'])if(d[key]!=null){demand(typeof d[key]==='string','CBStreamingDeltaInvalid');if(key==='content')content+=d[key];else reasoning+=d[key];}
      if(d.reasoning_details!==undefined){demand(Array.isArray(d.reasoning_details),'CBStreamingReasoningDetailsInvalid');for(const detail of d.reasoning_details){demand(detail&&typeof detail==='object'&&!Array.isArray(detail),'CBStreamingReasoningDetailInvalid');const key=detail.index!==undefined?'index:'+detail.index:detail.id?'id:'+detail.id:'anonymous:'+anonymousDetail++;const target=reasoningDetails.get(key)??{};for(const [field,value]of Object.entries(detail)){if(['text','summary','data'].includes(field)&&typeof value==='string')target[field]=(target[field]??'')+value;else{demand(target[field]===undefined||JSON.stringify(target[field])===JSON.stringify(value),'CBStreamingReasoningDetailChanged');target[field]=value;}}reasoningDetails.set(key,target);}}
      if(d.tool_calls!==undefined){demand(Array.isArray(d.tool_calls),'CBStreamingToolsInvalid');for(const t of d.tool_calls){demand(Number.isSafeInteger(t.index)&&t.index>=0&&t.index<128,'CBStreamingToolIndex');const target=tools.get(t.index)??{id:'',type:'function',function:{name:'',arguments:''}};if(t.id!==undefined){demand(typeof t.id==='string'&&(!target.id||target.id===t.id),'CBStreamingToolIdChanged');target.id=t.id;}if(t.type!==undefined)demand(t.type==='function','CBStreamingToolType');for(const key of ['name','arguments'] as const)if(t.function?.[key]!==undefined){demand(typeof t.function[key]==='string','CBStreamingToolFragmentInvalid');target.function[key]+=t.function[key];}tools.set(t.index,target);}}
    }
  }
  demand(done,'CBStreamingMissingDone');demand(id&&/^gen-/.test(id),'CBStreamingMissingGeneration');demand([MODEL,MODEL+'-20260910'].includes(model??''),'CBStreamingModelMismatch');demand(provider===expectedProvider,'CBStreamingProviderMismatch');
  demand(usage&&typeof usage.cost==='number'&&Number.isFinite(usage.cost)&&usage.cost>=0,'CBStreamingMissingUsdCost');for(const k of ['prompt_tokens','completion_tokens','total_tokens'])demand(Number.isSafeInteger(usage[k])&&usage[k]>=0,'CBStreamingUsageInvalid');demand(usage.total_tokens===usage.prompt_tokens+usage.completion_tokens,'CBStreamingUsageTotalMismatch');
  demand(finish,'CBStreamingMissingFinish');demand(['stop','tool_calls','length'].includes(finish!),'CBStreamingInvalidFinish');demand(finish!=='tool_calls'||tools.size>0,'CBStreamingMissingToolCalls');demand(content.length>0||tools.size>0||(finish==='length'&&(reasoning.length>0||reasoningDetails.size>0)),'CBStreamingMissingMessage');
  const calls=[...tools.entries()].sort(([a],[b])=>a-b).map(([index,t],position)=>{demand(index===position&&t.id&&t.function.name,'CBStreamingIncompleteTool');JSON.parse(t.function.arguments);return t;});demand(new Set(calls.map(t=>t.id)).size===calls.length,'CBStreamingDuplicateTool');
  return{rawResponse:JSON.stringify({id,object:'chat.completion',created,model,provider,choices:[{index:0,message:{role:'assistant',content:content||null,...(reasoning?{reasoning}:{}),...(reasoningDetails.size?{reasoning_details:[...reasoningDetails.values()]}:{}),...(calls.length?{tool_calls:calls}:{})},finish_reason:finish}],usage}),providerError:false};
}

/** Independent read-only replay for coordinator audits. Failure captures are rejected, never certified. */
export function verifyApprovedSupplierStreamEvidence(evidenceDir:string){
  const proof=JSON.parse(readFileSync(join(evidenceDir,'capture.evidence.json'),'utf8'));
  demand(proof.protocol==='chembench-sse-capture-v1'&&proof.complete===true&&proof.bodyComplete===true,'CBStreamingEvidenceIncomplete');
  const original=gunzipSync(readFileSync(verifyPin(proof.originalRequest))).toString('utf8'),wire=gunzipSync(readFileSync(verifyPin(proof.wireRequest))).toString('utf8');
  demand(wire===makeApprovedSupplierStreamingWireRequest(original)&&hash(original)===proof.originalRequestSha256&&hash(wire)===proof.wireRequestSha256,'CBStreamingEvidenceWireMismatch');
  const raw=gunzipSync(readFileSync(verifyPin(proof.rawSSE)));demand(raw.length===proof.rawResponseBytes&&hash(raw)===proof.rawResponseSha256,'CBStreamingEvidenceRawMismatch');
  const text=new TextDecoder('utf-8',{fatal:true}).decode(raw);let replay:{rawResponse:string;providerError:boolean};
  if(text.trimStart().startsWith('{')){demand(JSON.parse(text).error,'CBStreamingUnexpectedNonSSESuccess');replay={rawResponse:text,providerError:true};}else replay=aggregateSSE(text,supplierProfile(JSON.parse(original).provider.only[0]).providerName);
  const aggregate=readFileSync(verifyPin(proof.aggregate),'utf8');demand(aggregate===replay.rawResponse&&hash(aggregate)===proof.aggregateSha256&&proof.providerError===replay.providerError,'CBStreamingEvidenceAggregateMismatch');
  const a=JSON.parse(aggregate);return{valid:true,providerError:replay.providerError,httpStatus:proof.httpStatus,generation:a.id??null,provider:a.provider??null,model:a.model??null,usage:a.usage??null,wireOnlyStreamChange:true,sourceEvidence:proof,scoreCertificate:false};
}
