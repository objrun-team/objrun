/** Read-only financial audit. No provider, scorer, SQLite, resume, registry or lock mutation API. */
import {closeSync,existsSync,fsyncSync,lstatSync,mkdirSync,openSync,readFileSync,readSync,readdirSync,realpathSync,statSync,writeSync} from 'node:fs';
import {basename,dirname,join,resolve} from 'node:path';
import {gzipSync} from 'node:zlib';
import {inspectCampaignJournal} from './campaign-journal.ts';
import {completionFault,tokenCostUpperBound,validTokenUsage} from './campaign-contract.ts';
import {actualPin,demand,gzipProof,hash,inside,JournalBinding,jsonPin,peakWindow,pricedUsage,requestValues,same,validatePrices,verifyPin,type Pin,type Prefix} from './paid-resource-proof-v2.ts';

const ROOT=resolve(import.meta.dir,'../..'),RUN='repair-2026-10-08T18-32-57-118Z';
const STORE='D:/objrun-experiment-stores/01a119ed-fdf7-7c32-b323-de9bab1290b6/scientific-journal-v2-'+RUN;
const META=join(ROOT,'docs/repair-2026-10-08/campaigns',RUN),SELF=actualPin(import.meta.path);
const FIRST={path:join(ROOT,'docs/repair-2026-10-08/scientific-interruption-'+RUN,'first-pass.json'),sha256:'204cc6a0bfa793934b4abdfd78534a57ee606295feffe24a6878c76732652758'};
const CASH_REVIEW={path:join(ROOT,'docs/repair-2026-10-08/scientific-interruption-'+RUN,'cash-metadata-review.json'),sha256:'796c3870bb7919ed6fa655272b8f955ed100eea38b170e6680fb587a8352107a'};
const FROZEN={ 'campaign-journal.ts':'139a28eadf4fd570c04796430a419bfbba6ec0cc8d14eb28c2a4ef480cc90a56','cny-cash-shadow-v2.ts':'6ad11d7b32b8aee895e620306107cd7864fd35c5413ab5aa3e13b8966338f334','paid-resource-proof-v2.ts':'b1bacd465d2a76ca166e8048ac8ee83f152f6b9f21600770b39ec6a9864813fe'};
const INTRINSIC:Pin[]=[{path:join(import.meta.dir,'paid-resource-admission-v2.ts'),bytes:41347,sha256:'0b752576bd37235140a7b97dafee16741ebaadd9cafda3370e20317d9fdddb0e'},{path:join(import.meta.dir,'paid-resource-proof-v2.ts'),bytes:10106,sha256:'b1bacd465d2a76ca166e8048ac8ee83f152f6b9f21600770b39ec6a9864813fe'},{path:join(import.meta.dir,'campaign-contract.ts'),bytes:11488,sha256:'8ddbc1428a470ca18e5f6605f2bb48eccabc1bb5140ac777879601e4aec66305'}];
/** The original factory concatenated three intrinsic Pins and 81 executed Pins; duplicates are retained. */
export function assertOriginalAdmissionSources(admitted:readonly Pin[],executed:readonly Pin[],recipe:readonly Pin[]){
 const key=(p:Pin)=>{demand(p&&typeof p.path==='string'&&Number.isSafeInteger(p.bytes)&&p.bytes!>=0&&/^[a-f0-9]{64}$/.test(p.sha256)&&same(Object.keys(p).sort(),['bytes','path','sha256']),'invalid_original_source_pin');return JSON.stringify([resolve(p.path),p.bytes,p.sha256]);};
 demand(admitted.length===84&&executed.length===81&&recipe.length===81,'original_source_cardinality');
 demand(admitted.slice(0,3).every((p,n)=>key(p)===key(INTRINSIC[n])),'original_intrinsic_prefix');const tail=admitted.slice(3).map(key).sort();
 demand(same(tail,executed.map(key).sort())&&same(tail,recipe.map(key).sort()),'original_executed_source_multiset');return{intrinsicCount:3,executedCount:81,totalCount:84,exactMultiset:true};
}
type CoreInput={store:string;runId:string;count:number;deniedSeq:number;routes:Set<string>;denialProof:Pin;lateProofs:Pin[];expectedCny?:string;fixture:boolean};
type CashState={start:any;reservation:bigint;phase:string;amount:bigint;dispatch:boolean;finishSignature?:string};
const decimal=(n:bigint)=>(n/1000000000n).toString()+'.'+(n%1000000000n).toString().padStart(9,'0');
function json(path:string){return jsonPin(actualPin(path));}
function ordinary(path:string,owner:string){const p=resolve(path);demand(inside(owner,p),'input_outside_owned_root');let current=p;while(true){demand(!lstatSync(current).isSymbolicLink()&&realpathSync(current).toLowerCase()===current.toLowerCase(),'input_reparse');if(current===resolve(owner))break;current=dirname(current);}demand(lstatSync(p).isFile(),'input_not_regular');return p;}
function* frames(path:string,initial:Prefix,maxBytes:number){
 const before=statSync(path);demand(before.size<=maxBytes,'input_resource_bound');const fd=openSync(path,'r');let at=0,carry=Buffer.alloc(0),prefix={...initial};
 try{while(at<before.size){const buffer=Buffer.alloc(Math.min(65536,before.size-at)),n=readSync(fd,buffer,0,buffer.length,at);demand(n>0,'input_short_read');at+=n;carry=Buffer.concat([carry,buffer.subarray(0,n)]);let nl:number;
  while((nl=carry.indexOf(10))>=0){const line=carry.subarray(0,nl+1);demand(line.length<=65536,'input_line_bound');const e=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(line.subarray(0,-1)));demand(Buffer.from(JSON.stringify(e)+'\n').equals(line)&&e.eventSeq===prefix.eventCount&&e.previousEventSha256===prefix.lastSha256,'cash_chain_or_duplicate');prefix={bytes:prefix.bytes+line.length,eventCount:prefix.eventCount+1,lastSha256:hash(line)};yield{e,prefix:{...prefix}};carry=carry.subarray(nl+1);}demand(carry.length<=65536,'input_line_bound');}
  demand(carry.length===0,'truncated_cash_journal');const after=statSync(path);demand(before.size===after.size&&before.mtimeMs===after.mtimeMs,'cash_changed_during_read');
 }finally{closeSync(fd);}
}
class EvidenceWriter{
 readonly path:string;private fd:number;private batch:string[]=[];private bytes=0;private rows=0;private chain=SELF.sha256;private closed=false;
 constructor(out:string){this.path=join(out,'request-evidence.jsonl.gz');this.fd=openSync(this.path,'wx',0o600);}
 append(row:any){const payload=JSON.stringify(row),entry={previousRowSha256:this.chain,...row};this.chain=hash(JSON.stringify(entry)+'\n');this.batch.push(JSON.stringify(entry)+'\n');this.rows++;if(this.batch.length>=64)this.flush();}
 private flush(){if(!this.batch.length)return;const b=gzipSync(Buffer.from(this.batch.join('')));demand(this.bytes+b.length<=8*1024**2,'new_evidence_8MiB_bound');let n=0;while(n<b.length){const m=writeSync(this.fd,b,n,b.length-n,this.bytes+n);demand(m>0,'new_evidence_short_write');n+=m;}this.bytes+=b.length;this.batch=[];}
 close(){this.flush();fsyncSync(this.fd);closeSync(this.fd);this.closed=true;return{pin:actualPin(this.path),rows:this.rows,lastRowSha256:this.chain,concatenatedGzipMembers:true};}
 abort(){if(this.closed)return;try{fsyncSync(this.fd);}finally{closeSync(this.fd);this.closed=true;}}
}
function durable(path:string,value:unknown){const raw=Buffer.from(JSON.stringify(value,null,2)+'\n'),fd=openSync(path,'wx',0o600);try{let n=0;while(n<raw.length){const m=writeSync(fd,raw,n,raw.length-n,n);demand(m>0,'report_short_write');n+=m;}fsyncSync(fd);}finally{closeSync(fd);}demand(readFileSync(path).equals(raw),'report_readback');return actualPin(path);}

function core(input:CoreInput,out:string){
 demand(Number.isSafeInteger(input.count)&&input.count>=4&&input.deniedSeq===input.count-1&&input.lateProofs.length===3,'fixed_denial_and_three_late_proofs');
 const store=resolve(input.store);demand(realpathSync(store)===store,'physical_store_identity');const fixedPins=[actualPin(join(store,'journal-config.json')),actualPin(join(store,'api-state.json')),actualPin(join(store,'api-events.jsonl')),actualPin(join(store,'currency/cash-config.json')),actualPin(join(store,'currency/cash-events.jsonl')),input.denialProof,...input.lateProofs];
 const inspection=inspectCampaignJournal(store);demand(inspection.valid&&inspection.accountingClosed&&inspection.snapshot?.acceptedRequestCount===input.count&&inspection.snapshot.finishedRequestCount===input.count,'source_journal_not_financially_closed');
 demand(inspection.snapshot.reservedUpperBoundUsd===0&&inspection.snapshot.active.length===0&&json(fixedPins[1].path).stopReason==='provider_fault','fixed_interruption_source_state');
 const configPin=fixedPins[3],config=json(configPin.path),prices=validatePrices(config.pricesPin);
 demand(config.protocol==='cny-shadow-config-v2'&&config.runId===input.runId&&config.providerKind==='real-provider'&&config.carryNanoCny==='8392180000','cash_profile_or_old_unknown_changed');
 demand(resolve(config.journalDirectory)===store&&config.journalConfigPin.sha256===fixedPins[0].sha256,'cash_source_identity');
 for(const p of config.cashSourcePins)verifyPin(p);verifyPin(config.journalSourcePin);const admission=jsonPin(config.admissionPin);
 demand(admission.protocol==='paid-resource-admission-v2'&&admission.runId===input.runId&&admission.owned.ownerNonce===config.ownerNonce&&admission.selectedNewEnvelopeNanoCny===config.envelopeNanoCny&&admission.carryNanoCny==='8392180000','cash_admission_binding');
 const binding=new JournalBinding(store,config.journalConfigPin,config.journalSourcePin),states=new Map<number,CashState>(),apiIds=new Set<string>(),writer=new EvidenceWriter(out);let known=0n,pending=0n,usd=0,starts=0,finishes=0,forwarded=0,denied=0,wall=-Infinity,mono=-1n;
 const inputPinRows:Pin[]=[...fixedPins,config.pricesPin,config.admissionPin,...config.cashSourcePins,config.journalSourcePin],denial=jsonPin(input.denialProof),late=input.lateProofs.map(p=>({...jsonPin(p),originalReceiptPin:p})),seenLate=new Set<number>();let cashPrefix:Prefix={bytes:0,eventCount:0,lastSha256:configPin.sha256};
 demand(new Set(late.map(v=>v.requestSeq)).size===3&&late.every(v=>v.requestSeq!==input.deniedSeq),'duplicate_or_missing_late_seq');
 demand(denial.requestSeq===input.deniedSeq&&denial.providerAttempted===false&&denial.confirmedNoForward===true&&denial.journalRef&&denial.files.length===0&&denial.stage==='finish_or_post_finish_checkpoint','denial_zero_charge_not_proven');
 const forwardPins:Pin[]=[],reasons=new Set<string>();
 try{
  for(const{e,prefix}of frames(join(store,'currency/cash-events.jsonl'),cashPrefix,256*1024**2)){
   demand(e.protocol==='cny-shadow-event-v2','cash_protocol');const d=e.data;cashPrefix=prefix;
   if(e.kind==='start'){
    demand(d.requestSeq===starts&&!states.has(d.requestSeq),'duplicate_cash_start');const start=binding.start(d.requestSeq,d.startPrefix),raw=gzipProof(d.requestPin,d.rawRequestSha256,undefined,4*1024**2),v=requestValues(raw),body=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));
    demand(input.routes.has(start.route)&&start.route===d.route&&start.requestSha256===d.rawRequestSha256&&start.requestCompressedSha256===d.requestPin.sha256&&resolve(start.requestFile)===resolve(d.requestPin.path)&&start.requestBytes===raw.length&&v.inputUpper===d.inputUpper&&v.output===d.outputLimit,'cash_request_proof');
    demand(body.model==='deepseek-flash'&&body.temperature===0&&body.seed===42&&body.reasoning_effort==='none'&&body.max_tokens===8192&&body.stream!==true,'frozen_wire_parameters');ordinary(d.requestPin.path,store);forwardPins.push(actualPin(d.requestPin.path));
    demand(Number.isSafeInteger(d.hostWallUnixMs)&&d.hostWallUnixMs>=Date.parse(start.startedAt)&&d.hostWallUnixMs>=wall&&BigInt(d.hostMonotonicNs)>=mono,'clock_rollback_or_unknown');wall=d.hostWallUnixMs;mono=BigInt(d.hostMonotonicNs);
    demand(d.hostWallUnixMs>=Date.parse(prices.observedAtUtc)&&d.hostWallUnixMs-Date.parse(prices.observedAtUtc)<=24*3600000,'price_expired_at_forward');const r=v.peakNano;demand(d.peakReservationNanoCny===r.toString(),'cash_peak_quote');
    if(d.requestSeq===input.deniedSeq){demand(d.dispatchAllowed===false&&d.reason==='cash_envelope_exhausted'&&d.reservedNanoCny==='0'&&known+pending+r>BigInt(config.envelopeNanoCny),'denial_admission_or_reserve');denied++;reasons.add(d.reason);}
    else demand(d.dispatchAllowed===true&&d.reason===null&&d.reservedNanoCny===r.toString()&&known+pending+r<=BigInt(config.envelopeNanoCny),'unproven_dispatch_admission');
    const reservation=d.dispatchAllowed?r:0n;pending+=reservation;states.set(d.requestSeq,{start,reservation,phase:d.dispatchAllowed?'pending':'denied',amount:0n,dispatch:d.dispatchAllowed});starts++;
   }else if(e.kind==='finish'){
    const s=states.get(d.requestSeq);demand(s&&!s.finishSignature&&d.source.kind==='journal-finish'&&d.phase==='known','unknown_duplicate_or_unclosed_cash_finish');
    demand(Number.isSafeInteger(d.hostCaptureWallUnixMs)&&d.hostCaptureWallUnixMs>=wall&&BigInt(d.hostMonotonicNs)>=mono&&!d.clockFault,'capture_clock_rollback_or_unknown');wall=d.hostCaptureWallUnixMs;mono=BigInt(d.hostMonotonicNs);
    const c=binding.finish(d.requestSeq,d.source.journalRef);demand(c.requestSha256===s.start.requestSha256&&d.signature===d.source.journalRef.finishLineSha256,'cash_finish_membership');let amount=0n,responsePin:Pin|undefined;
    if(d.requestSeq===input.deniedSeq){demand(!s.dispatch&&c.providerAttempted===false&&c.confirmedNoForward===true&&!c.responseFile&&!c.usage&&c.usdUpperBound===0&&d.responsePin===null&&d.rawResponseSha256===null&&d.observedUsage===null&&d.amountNanoCny==='0'&&same(d.source.journalRef,denial.journalRef)&&denial.requestSha256===c.requestSha256,'denial_finish_binding');}
    else{
     demand(s.dispatch&&c.providerAttempted===true&&c.httpStatus===200&&!c.fault&&c.completionValid===true&&validTokenUsage(c.usage)&&c.servedModel==='deepseek-flash','provider_body_fault_or_unknown');
     responsePin=d.responsePin;demand(responsePin&&resolve(responsePin.path)===resolve(c.responseFile)&&responsePin.sha256===c.responseCompressedSha256&&d.rawResponseSha256===c.responseSha256,'cash_response_binding');ordinary(responsePin.path,store);forwardPins.push(actualPin(responsePin.path));
     const raw=gzipProof(responsePin,d.rawResponseSha256),data=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));demand(!completionFault(data)&&same(data.usage,c.usage)&&same(data.usage,d.observedUsage)&&data.model===c.servedModel&&typeof data.id==='string'&&data.id===c.requestId&&!apiIds.has(data.id),'raw_usage_model_completion_or_duplicate_id');apiIds.add(data.id);
     const window=peakWindow(Date.parse(s.start.startedAt),d.hostCaptureWallUnixMs);demand(!window.clockFault&&d.hostCaptureWallUnixMs>=Date.parse(prices.observedAtUtc)&&d.hostCaptureWallUnixMs-Date.parse(prices.observedAtUtc)<=24*3600000,'price_or_clock_unknown_at_capture');amount=pricedUsage(data.usage,window.peak);
     demand(d.observedEstimatedNanoCny===amount.toString()&&Math.abs(tokenCostUpperBound(data.usage)-c.usdUpperBound)<1e-9,'independent_cost_mismatch');forwarded++;
    }
    demand(d.amountNanoCny===amount.toString()&&d.peakReservationNanoCny===s.reservation.toString(),'cash_amount_mismatch');s.finishSignature=d.signature;s.phase='known';s.amount=amount;pending-=s.reservation;known+=amount;usd+=c.usdUpperBound;finishes++;
    const fallbackCopyEvidence:any[]=[];for(const f of late.filter(v=>v.requestSeq===d.requestSeq)){
     demand(f.providerAttempted===true&&f.httpStatus===200&&f.journalRef&&same(f.journalRef,d.source.journalRef)&&same(f.usage,c.usage)&&f.rawResponseSha256===c.responseSha256,'late_fallback_not_same_real_finish');
     const match=/^failure-([123])-receipt\.json$/.exec(basename(f.originalReceiptPin.path));demand(match&&resolve(f.originalReceiptPin.path)===join(store,'journal-failures',match[0])&&Array.isArray(f.files)&&f.files.length===1,'exact_late_copy_receipt');
     const copy=f.files[0] as Pin;demand(resolve(copy.path)===join(store,'journal-failures',`failure-${match[1]}-response.json.gz`),'exact_late_copy_path');ordinary(copy.path,store);verifyPin(copy);const copyRaw=gzipProof(copy,c.responseSha256),copyData=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(copyRaw));
     demand(!completionFault(copyData)&&same(copyData.usage,c.usage)&&copyData.model===c.servedModel&&copyData.id===c.requestId,'late_copy_not_same_complete_response');forwardPins.push(actualPin(copy.path));fallbackCopyEvidence.push({receiptIndex:Number(match[1]),pin:copy,rawSha256:c.responseSha256});seenLate.add(d.requestSeq);
    }
    writer.append({requestSeq:d.requestSeq,providerAttempted:c.providerAttempted,request:{bytes:statSync(c.requestFile).size,sha256:c.requestCompressedSha256,rawSha256:c.requestSha256},response:responsePin?{bytes:statSync(responsePin.path).size,sha256:c.responseCompressedSha256,rawSha256:c.responseSha256}:null,fallbackCopies:fallbackCopyEvidence,finishLineSha256:d.signature,servedModel:c.servedModel??null,usage:c.usage??null,knownEstimatedNanoCny:amount.toString(),usdUpperBound:c.usdUpperBound});
   }else if(e.kind==='poison'){demand(d.reason==='source_or_cash_post_finish_failure','unreviewed_cash_poison');reasons.add(d.reason);}
   else demand(false,'unreviewed_cash_event_kind');
  }
  demand(starts===input.count&&finishes===input.count&&forwarded===input.count-1&&denied===1&&pending===0n&&states.size===input.count&&[...states.values()].every(s=>s.phase==='known')&&seenLate.size===late.length,'full_request_set_not_closed');
  demand(input.expectedCny===undefined||known.toString()===input.expectedCny,'fixed_recorded_cny_changed');demand(Math.abs(usd-inspection.snapshot.recordedUsageUpperBoundUsd)<1e-9&&inspection.snapshot.reservedUpperBoundUsd===0,'usd_ledger_sum_mismatch');
  binding.consume(inspection.prefix!);demand(same(binding.current(),inspection.prefix),'exact_source_eof');const names=readdirSync(store);demand(names.filter(n=>/^provider-\d+-response\.json\.gz$/.test(n)).length===input.count-1&&!existsSync(join(store,`provider-${input.deniedSeq}-response.json.gz`)),'unexpected_or_missing_response_inventory');
  for(const p of [...inputPinRows,...forwardPins])verifyPin(p);const evidence=writer.close();
  return{validated:true,fixtureIntegrityValid:input.fixture,financialOnly:!input.fixture,scoreCertificate:false,plannedScoreCompletion:false,requests:starts,actualForwarded:forwarded,deniedBeforeForward:denied,knownEstimatedNanoCny:known.toString(),knownEstimatedCny:decimal(known),newUnknownCount:0,newPendingCount:0,originalUnknownCarryNanoCny:'8392180000',oldUnknownSettled:false,remainingEnvelopeNanoCny:(BigInt(config.envelopeNanoCny)-known).toString(),recordedUsageUpperBoundUsd:usd,cashPrefix,journalPrefix:inspection.prefix,inputPins:inputPinRows,rawRequestAndResponseFilesDoubleVerified:forwardPins.length,verifiedFallbackCopies:seenLate.size,fallbackCopiesChargedAgain:false,compressedRequestEvidence:evidence,reasons:[...reasons],releasePermitted:false,invoice:false,foreignExchangeConversion:false};
 }catch(e){writer.abort();throw e;}
}

/** Explicit synthetic F-only control entry. It can never issue a production financial certificate. */
export function auditFinancialFixture(input:Omit<CoreInput,'fixture'>,out:string){const parent=join(ROOT,'.scratch/scientific-financial-controls');demand(inside(parent,input.store)&&inside(parent,out)&&realpathSync(dirname(out))===resolve(dirname(out))&&!existsSync(out),'fixture_scope');mkdirSync(out);return core({...input,fixture:true},out);}

function production(out:string){
 for(const[n,s]of Object.entries(FROZEN))verifyPin({path:join(import.meta.dir,n),sha256:s});verifyPin(SELF);const first=jsonPin(FIRST),cash=jsonPin(CASH_REVIEW);
 demand(first.runId===RUN&&cash.runId===RUN&&first.originalRecordsModified===false&&cash.financiallyCertified===false,'fixed_interruption_observation');for(const p of [first.lock.pin,first.registry.pin,first.apiState.pin,first.progress.pin,first.cashConfig.pin,cash.cashEventsPin])verifyPin(p);
 const manifest=json(join(META,'manifest.json')),source=json(join(META,'source.json')),frozen=json(join(META,'frozen-source.json')),layout=json(join(META,'storage-layout.json')),admission=json(join(META,'paid-resource-admission.json'));
 demand(manifest.campaign===RUN&&manifest.profile==='full'&&manifest.providerKind==='real-provider'&&manifest.taskSchedule.length===1220&&hash(JSON.stringify(manifest.taskSchedule))===manifest.taskScheduleSha256&&manifest.taskScheduleSha256==='1ae6590140a51e9c48c656e92e482dd684843f8ae0e1dfc4e8f8ebad0e738bf8'&&manifest.capUsd===130&&manifest.priorCampaignCostUpperBoundUsd===47.531307588,'fixed_full_profile');
 demand(source.files.length+source.repairFiles.length===81&&source.executionDigest===manifest.sourceExecutionDigest&&frozen.sourceExecutionDigest===source.executionDigest&&resolve(layout.physicalStore)===resolve(STORE)&&realpathSync(layout.logicalStore)===resolve(STORE),'source_and_storage_bindings');
 demand(first.lock.record.runId===RUN&&first.lock.record.pid===104376&&same(first.lock.record,admission.owned)&&first.registry.record.closedPin===null&&first.registry.record.admissionPin.sha256===actualPin(join(META,'paid-resource-admission.json')).sha256,'unreleased_original_admission');
 const currentSourcePins=[...source.files,...source.repairFiles].map(p=>({path:resolve(ROOT,p.path),bytes:p.bytes,sha256:p.sha256})),recipe=jsonPin(manifest.paidResourceAdmission.recipePin);const sourceShape=assertOriginalAdmissionSources(admission.sourcePins,currentSourcePins,recipe.executedSourcePins);INTRINSIC.forEach(p=>verifyPin(p));
 const hostBun=actualPin(process.execPath);demand(hostBun.sha256===manifest.hostExecutors.bun.sha256&&hostBun.bytes===manifest.hostExecutors.bun.bytes&&Bun.version===manifest.hostExecutors.bun.version,'actual_audit_host_bun_version');
 const sourcePins=[...source.files,...source.repairFiles,...frozen.dependencyFiles].map(p=>({path:resolve(ROOT,p.path),sha256:p.sha256,bytes:p.bytes}));sourcePins.forEach(p=>verifyPin(p));demand(resolve(frozen.archive)===join(resolve(STORE),'frozen-source.zip'),'frozen_archive_path');const archivePin={path:frozen.archive,bytes:frozen.archiveBytes,sha256:frozen.archiveSha256};verifyPin(archivePin);verifyPin(manifest.paidResourceAdmission.recipePin);
 const metaPins=['manifest.json','source.json','frozen-source.json','storage-layout.json','progress.json','paid-resource-admission.json','paid-resource-v2-run.json','paid-process-0.json','paid-process-1.json','paid-process-2.json','paid-process-3.json'].map(n=>actualPin(join(META,n)));
 for(const n of ['summary.json','api-ledger.json','journal-export.json','paid-resource-closure.json','final-certificate.json','paid-resource-final-certificate.json'])demand(!existsSync(join(META,n)),'original_closing_state_changed');demand(!existsSync(join(STORE,'currency/cash-close.json')),'original_cash_close_appeared');
 const proofRoot=join(STORE,'journal-failures'),proofPins=[0,1,2,3].map(n=>actualPin(join(proofRoot,`failure-${n}-receipt.json`)));demand(proofPins.every(p=>first.failureFacts.some((f:any)=>f.pin.path===p.path&&f.pin.sha256===p.sha256)),'original_fallback_changed');
 const routes=new Set<string>(manifest.taskSchedule.map((t:any)=>`${RUN}/${t.benchmark}/${t.arm}/${t.replica}/${t.officialId}`));demand(routes.size===1220,'plan_route_set');
 const result=core({store:STORE,runId:RUN,count:23504,deniedSeq:23503,routes,denialProof:proofPins[0],lateProofs:proofPins.slice(1),expectedCny:'247731051080',fixture:false},out);
 for(const p of [...metaPins,...sourcePins,archivePin,first.lock.pin,first.registry.pin,first.apiState.pin,first.progress.pin])verifyPin(p);verifyPin(SELF);
 return{protocol:'financial-interruption-v1',runId:RUN,observedAtUtc:new Date().toISOString(),auditSourcePin:SELF,auditHostBun:hostBun,metadataInputPins:metaPins,observations:[FIRST,CASH_REVIEW],sourceFileCount:81,originalAdmissionSourceShape:sourceShape,currentDependencyFilesVerified:frozen.dependencyFiles.length,archivePin,sourceIdentity:'Current81 sources/dependency bytes verified against original frozen metadata; original archive whole bytes SHA bound. No source/runtime mutation.',plannedTaskRuns:1220,recordedTaskRuns:first.taskFileCount,originalClosingArtifactsFabricated:false,originalSqliteOpened:false,providerRequestsByAudit:0,originalRecordsModified:false,paidLockOperations:0,ownerClosureCertified:false,interruptionTrigger:'cash_envelope_exhausted',proxyStopLabel:'provider_fault',processExitMechanism:'unknown',...result};
}

if(import.meta.main){
 const args=process.argv.slice(2),at=args.indexOf('--output'),out=at>=0?resolve(args[at+1]??''):'',shaAt=args.indexOf('--source-sha');demand(shaAt>=0&&args[shaAt+1]===SELF.sha256,'explicit_reviewed_audit_source_required');
 demand(args.includes('--audit')&&out&&inside(join(ROOT,'docs/repair-2026-10-08/scientific-financial-interruptions'),out)&&!existsSync(out),'explicit_fresh_F_output_required');let ancestor=dirname(out);while(!existsSync(ancestor))ancestor=dirname(ancestor);demand(realpathSync(ancestor)===resolve(ancestor),'new_output_ancestor_reparse');mkdirSync(out,{recursive:true});
 try{const result=production(out),report=durable(join(out,'audit.json'),result);console.log(JSON.stringify({report,validated:true,financialOnly:true,scoreCertificate:false,knownEstimatedCny:result.knownEstimatedCny,releasePermitted:false}));}
 catch(e){const report=durable(join(out,'audit-failure.json'),{protocol:'financial-interruption-v1',runId:RUN,auditSourcePin:SELF,validated:false,financialOnly:false,scoreCertificate:false,releasePermitted:false,error:e instanceof Error?(e as any).code??e.message:'UnknownError',originalRecordsModified:false,paidLockOperations:0});console.log(JSON.stringify({report,validated:false,financialOnly:false,scoreCertificate:false,releasePermitted:false}));process.exitCode=1;}
}
