/** TB-only copy: known usage is always charged at published peak for a conservative aggregate budget upper bound. Original shared source is unchanged. */
import {closeSync,existsSync,fsyncSync,openSync,readFileSync,readSync,statSync,writeFileSync,writeSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {inspectCampaignJournal} from '../../repair-2026-10-08/campaign-journal.ts';
import { verifyBenchmarkCashClosure } from '../../repair-2026-10-08/benchmark-usd-cash.ts';
import type {AdmissionLease} from '../../repair-2026-10-08/paid-resource-admission-v2.ts';
import {Pin,Prefix,Clock,REAL_CLOCK,JournalBinding,actualPin,demand,gzipProof,hash,integer,jsonPin,ordinaryDirectory,peakWindow,pricedUsage,requestValues,same,validatePrices,verifyPin} from '../../repair-2026-10-08/paid-resource-proof-v2.ts';

const SELF=actualPin(import.meta.path),PROOF_SOURCE=actualPin(join(import.meta.dir,'../../repair-2026-10-08/paid-resource-proof-v2.ts'));
export type JournalStart={admitted:{admitted:true;requestSeq:number;reservationUsd:number;requestFile:string;requestSha256:string};startPrefix:Prefix};
export type FinishRef={callId?:string;finishOffset:number;finishEnd:number;finishLineSha256:string};
export type CashFinish={kind:'journal-finish';journalRef:FinishRef}|{kind:'failed-capture';requestSeq:number;evidence:{files:readonly Pin[];responsePin?:Pin;rawResponseSha256?:string;usage?:any;httpStatus?:number;providerAttempted:boolean;originalPrefix:Prefix;reason:string}};
export type CashTicket={id:string;requestSeq:number;route:string;dispatchAllowed:boolean;peakReservationNanoCny:string};
export type CashAdmission={admitted:boolean;ticket:CashTicket;reason?:string};
export interface CashOptions{
 directory:string;runId:string;providerKind:'real-provider'|'local-mock';admission?:AdmissionLease;prices:Pin;
 journal:{directory:string;configPin:Pin;sourcePin:Pin};clock?:Clock;
 fixtureIo?:(stage:'cash_write'|'cash_fsync'|'cash_readback')=>void;
}
type State={id:string;seq:number;route:string;start:any;reservation:bigint;phase:'pending'|'denied'|'known'|'unknown';amount:bigint;finishSignature?:string;lastResponseRawSha?:string;ticket:CashTicket;};

/** Own fsync/readback witness, rather than trusting an asynchronous sink ack. */
class CashWriter{
 readonly path:string;readonly configPin:Pin;private fd:number;private prefix:Prefix;private failed=false;private closed=false;
 constructor(readonly directory:string,config:any,readonly hook?:CashOptions['fixtureIo']){
  const path=join(directory,'cash-config.json'),raw=Buffer.from(JSON.stringify(config)+'\n'),fd=openSync(path,'wx',0o600);try{writeFileSync(fd,raw);fsyncSync(fd);}finally{closeSync(fd);}demand(readFileSync(path).equals(raw),'cash_config_readback');this.configPin=actualPin(path);
  this.path=join(directory,'cash-events.jsonl');this.fd=openSync(this.path,'wx+',0o600);fsyncSync(this.fd);this.prefix={bytes:0,eventCount:0,lastSha256:this.configPin.sha256};
 }
 append(kind:string,data:any){
  demand(!this.failed&&!this.closed,'cash_writer_unclosed_fault');const event={protocol:'cny-shadow-event-v2',eventSeq:this.prefix.eventCount,previousEventSha256:this.prefix.lastSha256,kind,data},raw=Buffer.from(JSON.stringify(event)+'\n');
  demand(raw.length<=65536&&this.prefix.bytes+raw.length<=256*1024**2,'cash_metadata_bound');const offset=this.prefix.bytes;
  try{this.hook?.('cash_write');let n=0;while(n<raw.length){const got=writeSync(this.fd,raw,n,raw.length-n,offset+n);demand(got>0,'cash_short_write');n+=got;}this.hook?.('cash_fsync');fsyncSync(this.fd);this.hook?.('cash_readback');const read=Buffer.alloc(raw.length);demand(readSync(this.fd,read,0,read.length,offset)===read.length&&read.equals(raw)&&statSync(this.path).size===offset+raw.length,'cash_event_readback');this.prefix={bytes:offset+raw.length,eventCount:this.prefix.eventCount+1,lastSha256:hash(raw)};return{...this.prefix};}
  catch(error){this.failed=true;throw error;}
 }
 snapshot(){return{...this.prefix};} fault(){return this.failed;}
 close(){if(this.closed)return;try{fsyncSync(this.fd);}finally{closeSync(this.fd);this.closed=true;}}
}

export function createCnyCashShadow(options:CashOptions){return new CnyCashShadow(options);}
class CnyCashShadow{
 readonly options:CashOptions;
 readonly directory:string;readonly writer:CashWriter;readonly binding:JournalBinding;readonly clock:Clock;
 private states=new Map<number,State>();private ticketStates=new WeakMap<CashTicket,State>();private poisonReason?:string;private clockWall?:number;private clockMono?:bigint;private closedPin?:Pin;private nextSeq=0;
 readonly prices:any;readonly config:any;readonly configPin:Pin;
 constructor(given:CashOptions){
  const options:CashOptions=Object.freeze({...given,prices:Object.freeze({...given.prices}),journal:Object.freeze({...given.journal,configPin:Object.freeze({...given.journal.configPin}),sourcePin:Object.freeze({...given.journal.sourcePin})})});this.options=options;
  demand(options.providerKind==='local-mock'||options.admission,'real_provider_admission_required');
  demand(options.providerKind!=='local-mock'||!options.admission||options.admission.scope==='f-fixture','production_admission_cannot_zero_mock');
  if(options.fixtureIo)demand(options.admission?.scope==='f-fixture','cash_fault_hooks_fixture_only');
  this.directory=ordinaryDirectory(options.directory);this.clock=options.admission?.clock??options.clock??REAL_CLOCK;this.prices=validatePrices(options.prices);
  this.binding=new JournalBinding(resolve(options.journal.directory),options.journal.configPin,options.journal.sourcePin);demand(this.binding.config.campaign===options.runId,'cash_journal_run_binding');
  this.config={protocol:'cny-shadow-config-v2',pricingMode:'published-peak-conservative-upper-bound',runId:options.runId,providerKind:options.providerKind,scope:options.admission?.scope??'local-mock',ownerNonce:options.admission?.owned.ownerNonce??null,admissionPin:options.admission?.proofPin??null,envelopeNanoCny:(options.admission?.envelopeNanoCny??0n).toString(),carryNanoCny:(options.admission?.carryNanoCny??0n).toString(),pricesPin:options.prices,journalDirectory:resolve(options.journal.directory),journalConfigPin:options.journal.configPin,journalSourcePin:options.journal.sourcePin,cashSourcePins:[SELF,PROOF_SOURCE],createdAt:new Date(this.clock.wallUnixMs()).toISOString(),priceTTL:'real-beforeForward24h',moneyUnit:'nanoCNY',invoice:false,foreignExchangeConversion:false};
  this.writer=new CashWriter(this.directory,this.config,options.fixtureIo);this.configPin=this.writer.configPin;try{options.admission?.registerCash(this.configPin);}catch(error){this.writer.close();throw error;}
 }
 private clockNow(){const wall=this.clock.wallUnixMs(),mono=this.clock.monotonicNs();const fault=!Number.isFinite(wall)||(this.clockWall!==undefined&&wall<this.clockWall)||(this.clockMono!==undefined&&mono<this.clockMono);if(fault)this.poisonReason??='clock_rollback_or_unknown';this.clockWall=wall;this.clockMono=mono;return{wall,mono,fault};}
 private count(){let known=0n,pending=0n,unknown=0n,pendingCount=0,unknownCount=0;for(const s of this.states.values()){if(s.phase==='known')known+=s.amount;else if(s.phase==='unknown'){unknown+=s.amount;unknownCount++;}else if(s.phase==='pending'||s.phase==='denied'){pending+=s.reservation;pendingCount++;}}return{known,pending,unknown,pendingCount,unknownCount};}
 snapshot(){const t=this.count(),envelope=this.options.admission?.envelopeNanoCny??0n;return{protocol:'cny-shadow-cash-v2',runId:this.options.runId,currency:'CNY',providerKind:this.options.providerKind,carriedOriginalUnknownNanoCny:this.config.carryNanoCny,newKnownEstimatedNanoCny:t.known.toString(),newPendingPeakNanoCny:t.pending.toString(),newUnknownPeakNanoCny:t.unknown.toString(),newExposureNanoCny:(t.known+t.pending+t.unknown).toString(),remainingNewEnvelopeNanoCny:(envelope-t.known-t.pending-t.unknown).toString(),pendingCount:t.pendingCount,newUnknownCount:t.unknownCount,poisoned:!!this.poisonReason,poisonReason:this.poisonReason??null,invoice:false,foreignExchangeConversion:false};}
 beforeForward(input:{id:string;route:string;rawRequest:Uint8Array;capturedRequest:Pin;journal:JournalStart}):CashAdmission{
  demand(!this.closedPin&&!this.writer.fault(),'cash_closed_or_faulted');const j=input.journal.admitted;demand(j.admitted===true&&integer(j.requestSeq)&&j.requestSeq===this.nextSeq&&!this.states.has(j.requestSeq),'cash_request_sequence');
  const start=this.binding.start(j.requestSeq,input.journal.startPrefix),raw=gzipProof(input.capturedRequest,j.requestSha256,undefined,4*1024**2),v=requestValues(raw);
  demand(Buffer.from(input.rawRequest).equals(raw)&&resolve(input.capturedRequest.path)===resolve(j.requestFile)&&start.requestFile===j.requestFile&&start.requestSha256===j.requestSha256&&start.requestCompressedSha256===input.capturedRequest.sha256&&start.requestBytes===raw.length&&start.route===input.route&&start.providerAttempted===false&&Math.abs(start.reservationUsd-j.reservationUsd)<1e-9,'cash_actual_admission_binding');
  demand(Math.abs(j.reservationUsd-(v.inputUpper*0.3+v.output*1.2)/1e6)<1e-9,'legacy_usd_reservation_binding'); // Separate old USD formula, never a currency conversion.
  const checkpoint=jsonPin(actualPin(join(this.binding.directory,'api-state.json')));demand(checkpoint.configSha256===this.binding.configSha&&!existsSync(join(this.binding.directory,'journal-error.json')),'journal_checkpoint_unacknowledged');this.binding.consume(checkpoint.durablePrefix);
  // Independently flush the current owned request/prefix/checkpoint as well;
  // a caller's admitted/fsync boolean alone cannot mint a forward ticket.
  for(const path of [j.requestFile,this.binding.path,join(this.binding.directory,'api-state.json')]){const fd=openSync(path,'r+');try{fsyncSync(fd);}finally{closeSync(fd);}}
  const now=this.clockNow();let reason=this.poisonReason;
  try{verifyPin(SELF);verifyPin(PROOF_SOURCE);verifyPin(this.options.prices);this.options.admission?.validateForwardSource();}catch{reason??='cash_owner_or_source_or_price_expired';}
  if(now.fault)reason??='cash_clock_fault';
  if(!Number.isFinite(Date.parse(start.startedAt))||now.wall<Date.parse(start.startedAt))reason??='cash_start_clock_invalid';
  if(this.options.providerKind==='real-provider'&&(!Number.isFinite(Date.parse(this.prices.observedAtUtc))||now.wall-Date.parse(this.prices.observedAtUtc)>24*3600000||now.wall<Date.parse(this.prices.observedAtUtc)))reason??='price_expired_or_clock_invalid';
  const r=this.options.providerKind==='local-mock'?0n:v.peakNano,t=this.count();if(t.known+t.pending+t.unknown+r>(this.options.admission?.envelopeNanoCny??0n))reason??='cash_envelope_exhausted';
  const ticket:CashTicket=Object.freeze({id:input.id,requestSeq:j.requestSeq,route:input.route,dispatchAllowed:!reason,peakReservationNanoCny:r.toString()});
  const state:State={id:input.id,seq:j.requestSeq,route:input.route,start,reservation:reason?0n:r,phase:reason?'denied':'pending',amount:0n,ticket};
  try{this.writer.append('start',{id:input.id,requestSeq:j.requestSeq,route:input.route,requestPin:input.capturedRequest,rawRequestSha256:j.requestSha256,startPrefix:input.journal.startPrefix,inputUpper:v.inputUpper,outputLimit:v.output,peakReservationNanoCny:r.toString(),reservedNanoCny:state.reservation.toString(),dispatchAllowed:!reason,reason:reason??null,hostWallUnixMs:now.wall,hostMonotonicNs:now.mono.toString()});}catch(error){this.poisonReason??='cash_admission_persistence_failed';throw error;}
  this.nextSeq++;this.states.set(j.requestSeq,state);this.ticketStates.set(ticket,state);if(reason)this.poisonReason??=reason;return{admitted:!reason,ticket,...(reason?{reason}:{})};
 }
 poison(reason:string){demand(reason.length>0&&reason.length<=1024,'poison_reason');this.poisonReason??=reason;if(!this.writer.fault())this.writer.append('poison',{reason});return this.snapshot();}
 finish(ticket:CashTicket,input:CashFinish){try{return this.finishInternal(ticket,input);}catch(error){this.poisonReason??='cash_finish_validation_failed';if(!this.writer.fault()&&!this.closedPin)this.writer.append('poison',{reason:this.poisonReason,requestSeq:ticket.requestSeq});throw error;}}
 private finishInternal(ticket:CashTicket,input:CashFinish){
  demand(!this.closedPin,'cash_already_closed');const s=this.ticketStates.get(ticket);demand(s&&s.seq===ticket.requestSeq&&s.ticket===ticket,'cash_ticket_identity');const now=this.clockNow();let record:any,signature:string,source:any,unknown=false;
  if(input.kind==='journal-finish'){
   record=this.binding.finish(s.seq,input.journalRef);demand(record.requestSha256===s.start.requestSha256&&record.requestFile===s.start.requestFile&&record.route===s.route,'cash_finish_start_binding');signature=input.journalRef.finishLineSha256;source={kind:'journal-finish',journalRef:input.journalRef};
  }else{
   demand(input.requestSeq===s.seq&&input.evidence.files.length>0,'failed_capture_binding');for(const p of input.evidence.files)verifyPin(p);this.binding.consume(input.evidence.originalPrefix);record={...s.start,...input.evidence};signature=hash(JSON.stringify(input.evidence));source={kind:'failed-capture',evidence:input.evidence};unknown=true;this.poisonReason??='source_journal_poisoned_capture';
  }
  if(s.finishSignature===signature)return this.snapshot();
  try{this.options.admission?.assertOwned();}catch{this.poisonReason??='cash_owner_lost';}
  let amount=s.reservation,observedUsage:any,estimate:bigint|undefined,responsePin:Pin|undefined,rawResponseSha:string|undefined;
  if(record.providerAttempted===false&&record.confirmedNoForward===true&&input.kind==='journal-finish')amount=0n;
  else{
   if(!ticket.dispatchAllowed)this.poisonReason??='provider_forward_after_cash_denial';
   try{
    responsePin=input.kind==='journal-finish'&&record.responseFile?{path:record.responseFile,sha256:record.responseCompressedSha256}:input.kind==='failed-capture'?input.evidence.responsePin:undefined;rawResponseSha=input.kind==='journal-finish'?record.responseSha256:input.evidence.rawResponseSha256;
    demand(responsePin&&rawResponseSha,'complete_response_missing');const raw=gzipProof(responsePin,rawResponseSha),data=JSON.parse(raw.toString('utf8'));observedUsage=data.usage;demand(same(data.usage,record.usage)&&data.model===record.servedModel||input.kind==='failed-capture'&&same(data.usage,input.evidence.usage),'response_usage_binding');
    const window=peakWindow(Date.parse(s.start.startedAt),now.wall),expired=now.wall-Date.parse(this.prices.observedAtUtc)>24*3600000||now.wall<Date.parse(this.prices.observedAtUtc);const peak=window.peak||window.clockFault||now.fault||expired;
    estimate=this.options.providerKind==='local-mock'?0n:pricedUsage(observedUsage,true);amount=estimate;
    if(input.kind==='journal-finish'&&(record.httpStatus!==200||record.fault||record.completionValid!==true)){unknown=true;this.poisonReason??='provider_body_or_completion_not_complete';}
    if(window.clockFault||now.fault||expired){unknown=true;this.poisonReason??='clock_or_price_unknown_at_capture';}
   }catch{unknown=true;this.poisonReason??='missing_or_invalid_complete_usage';}
  }
  if(input.kind==='failed-capture'&&s.phase==='known'&&responsePin&&observedUsage&&estimate===s.amount&&rawResponseSha&&rawResponseSha===s.lastResponseRawSha){this.writer.append('late-evidence',{id:s.id,requestSeq:s.seq,source,responsePin,rawResponseSha256:rawResponseSha,observedUsage,amountNanoCny:s.amount.toString(),reason:'overlapping_known_finish_retained_once'});return this.snapshot();}
  if(input.kind==='failed-capture')unknown=true;
  if(s.phase==='unknown'||s.phase==='known'&&s.finishSignature){unknown=true;this.poisonReason??='conflicting_or_late_cash_finish';}
  if(unknown)amount=[s.reservation,s.amount,estimate??0n].reduce((a,b)=>a>b?a:b);
  const phase=unknown?'unknown':'known';
  const data={id:s.id,requestSeq:s.seq,phase,amountNanoCny:amount.toString(),peakReservationNanoCny:s.reservation.toString(),source,signature,responsePin:responsePin??null,rawResponseSha256:rawResponseSha??null,observedUsage:observedUsage??null,observedEstimatedNanoCny:estimate?.toString()??null,hostCaptureWallUnixMs:now.wall,hostMonotonicNs:now.mono.toString(),clockFault:now.fault,poisonReason:this.poisonReason??null};
  try{this.writer.append('finish',data);}catch(error){this.poisonReason??='cash_finish_persistence_failed';throw error;}
  s.phase=phase;s.amount=amount;s.finishSignature=signature;s.lastResponseRawSha=rawResponseSha;
  if(amount>s.reservation&&record.providerAttempted!==false)this.poisonReason??='actual_estimate_exceeds_reservation';
  if(BigInt(this.snapshot().newExposureNanoCny)>(this.options.admission?.envelopeNanoCny??0n))this.poisonReason??='actual_estimate_exceeds_envelope';return this.snapshot();
 }
 close():Pin{
  if(this.closedPin)return this.closedPin;const inspection=inspectCampaignJournal(this.options.journal.directory),snapshot=this.snapshot();const cashPrefix=this.writer.snapshot();let good=!this.writer.fault()&&inspection.valid&&inspection.accountingClosed&&snapshot.pendingCount===0&&snapshot.newUnknownCount===0;
  try{this.options.admission?.assertOwned();}catch{good=false;}
  this.writer.close();const cashEvents=actualPin(this.writer.path);const value={protocol:'cny-shadow-close-v2',runId:this.options.runId,ownerNonce:this.config.ownerNonce,configPin:this.configPin,cashEventsPin:cashEvents,cashPrefix,journalConfigPin:this.options.journal.configPin,journalSourcePin:this.options.journal.sourcePin,journalDirectory:resolve(this.options.journal.directory),journalPrefix:inspection.prefix??this.binding.current(),journalValid:inspection.valid,journalAccountingClosed:inspection.accountingClosed,snapshot,releasePermitted:good,poisonReason:this.poisonReason??null,invoice:false,foreignExchangeConversion:false};
  const path=join(this.directory,'cash-close.json'),fd=openSync(path,'wx',0o600);try{writeFileSync(fd,JSON.stringify(value,null,2)+'\n');fsyncSync(fd);}finally{closeSync(fd);}this.closedPin=actualPin(path);if(good)verifyCashClosure(this.closedPin);return this.closedPin;
 }
}

/** Replay current exact witnesses; a caller-created closed:true is insufficient. */
export function verifyCashClosure(pin:Pin){
 if(jsonPin(pin).protocol==='openrouter-usd-cash-close-v1')return verifyBenchmarkCashClosure(pin);
 const proof=jsonPin(pin),config=jsonPin(proof.configPin);demand(proof.protocol==='cny-shadow-close-v2'&&config.protocol==='cny-shadow-config-v2'&&proof.runId===config.runId&&proof.ownerNonce===config.ownerNonce,'cash_close_config');
 demand(config.providerKind==='real-provider'||config.providerKind==='local-mock','cash_provider_kind');demand(config.pricingMode==='published-peak-conservative-upper-bound','tb12_peak_upper_pricing_required');for(const p of config.cashSourcePins)verifyPin(p);const prices=validatePrices(config.pricesPin);verifyPin(proof.cashEventsPin);verifyPin(config.journalSourcePin);
 if(config.admissionPin){const admission=jsonPin(config.admissionPin);demand(admission.protocol==='paid-resource-admission-v2'&&admission.runId===config.runId&&admission.owned.ownerNonce===config.ownerNonce&&admission.selectedNewEnvelopeNanoCny===config.envelopeNanoCny&&admission.carryNanoCny===config.carryNanoCny,'cash_admission_config_binding');}
 const binding=new JournalBinding(config.journalDirectory,config.journalConfigPin,config.journalSourcePin),raw=readFileSync(proof.cashEventsPin.path);let at=0,seq=0,last=proof.configPin.sha256;const states=new Map<number,{phase:string;amount:bigint;reservation:bigint;start:any;signature?:string;rawSha?:string}>();
 for(const lineText of raw.toString('utf8').split('\n')){if(!lineText)continue;const line=Buffer.from(lineText+'\n'),e=JSON.parse(lineText);demand(Buffer.from(JSON.stringify(e)+'\n').equals(line)&&e.protocol==='cny-shadow-event-v2'&&e.eventSeq===seq&&e.previousEventSha256===last,'cash_event_chain');const d=e.data;
  if(e.kind==='start'){
   demand(!states.has(d.requestSeq)&&d.requestSeq===states.size,'cash_start_sequence');const start=binding.start(d.requestSeq,d.startPrefix),body=gzipProof(d.requestPin,d.rawRequestSha256,undefined,4*1024**2),v=requestValues(body);
   demand(start.requestSha256===d.rawRequestSha256&&start.requestCompressedSha256===d.requestPin.sha256&&resolve(start.requestFile)===resolve(d.requestPin.path)&&start.requestBytes===body.length&&start.route===d.route&&v.inputUpper===d.inputUpper&&v.output===d.outputLimit,'cash_start_proof');const r=config.providerKind==='local-mock'?0n:v.peakNano;demand(typeof d.dispatchAllowed==='boolean'&&r.toString()===d.peakReservationNanoCny&&d.reservedNanoCny===(d.dispatchAllowed?r:0n).toString(),'cash_peak_reservation');states.set(d.requestSeq,{phase:d.dispatchAllowed?'pending':'denied',amount:0n,reservation:BigInt(d.reservedNanoCny),start});
  }else if(e.kind==='finish'){
   const s=states.get(d.requestSeq);demand(s,'cash_finish_unknown');let min=0n;
   if(d.source.kind==='journal-finish'){
    const receipt=binding.finish(d.requestSeq,d.source.journalRef);demand(d.signature===d.source.journalRef.finishLineSha256&&receipt.requestSha256===s.start.requestSha256,'cash_finish_member');
    if(!(receipt.providerAttempted===false&&receipt.confirmedNoForward===true)){
     if(receipt.httpStatus!==200||receipt.fault||receipt.completionValid!==true)demand(d.phase==='unknown','incomplete_provider_receipt_settled');
     demand(d.responsePin&&d.rawResponseSha256&&resolve(d.responsePin.path)===resolve(receipt.responseFile)&&d.responsePin.sha256===receipt.responseCompressedSha256&&d.rawResponseSha256===receipt.responseSha256,'cash_known_response_missing');const body=gzipProof(d.responsePin,d.rawResponseSha256),data=JSON.parse(body.toString('utf8'));demand(same(data.usage,d.observedUsage)&&same(data.usage,receipt.usage)&&data.model===receipt.servedModel,'cash_usage_proof');const window=peakWindow(Date.parse(s.start.startedAt),d.hostCaptureWallUnixMs),expired=!Number.isFinite(Date.parse(prices.observedAtUtc))||d.hostCaptureWallUnixMs-Date.parse(prices.observedAtUtc)>24*3600000||d.hostCaptureWallUnixMs<Date.parse(prices.observedAtUtc);if(window.clockFault||d.clockFault||expired)demand(d.phase==='unknown','cash_clock_unknown_settled');try{min=config.providerKind==='local-mock'?0n:pricedUsage(data.usage,true);}catch{demand(d.phase==='unknown','invalid_usage_settled');min=s.reservation;}
    }
   }else{
    demand(d.source.kind==='failed-capture'&&d.phase==='unknown','failed_capture_settled');for(const p of d.source.evidence.files)verifyPin(p);min=s.reservation;if(d.responsePin&&d.rawResponseSha256){const body=gzipProof(d.responsePin,d.rawResponseSha256),data=JSON.parse(body.toString('utf8'));demand(same(data.usage,d.observedUsage),'late_usage_proof');try{const w=peakWindow(Date.parse(s.start.startedAt),d.hostCaptureWallUnixMs);min=config.providerKind==='local-mock'?0n:pricedUsage(data.usage,true);}catch{}}
   }
   if(s.phase==='unknown')demand(d.phase==='unknown','sealed_unknown_reopened');if(d.phase==='unknown')min=[min,s.reservation,s.amount].reduce((a,b)=>a>b?a:b);demand((d.phase==='known'||d.phase==='unknown')&&BigInt(d.amountNanoCny)>=min&&(d.phase!=='known'||BigInt(d.amountNanoCny)===min),'cash_cost_replay');s.phase=d.phase;s.amount=BigInt(d.amountNanoCny);s.signature=d.signature;s.rawSha=d.rawResponseSha256;
  }else if(e.kind==='late-evidence'){const s=states.get(d.requestSeq);demand(s&&s.phase==='known'&&s.rawSha===d.rawResponseSha256&&d.source.kind==='failed-capture'&&BigInt(d.amountNanoCny)===s.amount,'late_overlap_binding');for(const p of d.source.evidence.files)verifyPin(p);const body=gzipProof(d.responsePin,d.rawResponseSha256),data=JSON.parse(body.toString('utf8'));demand(same(data.usage,d.observedUsage),'late_overlap_usage');}
  else demand(e.kind==='poison','cash_event_kind');at+=line.length;seq++;last=hash(line);
 }
 demand(at===raw.length&&same(proof.cashPrefix,{bytes:at,eventCount:seq,lastSha256:last}),'cash_exact_prefix');let known=0n,pending=0n,unknown=0n,pendingCount=0,unknownCount=0;for(const s of states.values()){if(s.phase==='known')known+=s.amount;else if(s.phase==='unknown'){unknown+=s.amount;unknownCount++;}else{pending+=s.reservation;pendingCount++;}}
 const exposure=known+pending+unknown;demand(proof.snapshot.protocol==='cny-shadow-cash-v2'&&proof.snapshot.runId===config.runId&&proof.snapshot.currency==='CNY'&&proof.snapshot.providerKind===config.providerKind&&proof.snapshot.carriedOriginalUnknownNanoCny===config.carryNanoCny&&proof.snapshot.newKnownEstimatedNanoCny===known.toString()&&proof.snapshot.newPendingPeakNanoCny===pending.toString()&&proof.snapshot.newUnknownPeakNanoCny===unknown.toString()&&proof.snapshot.newExposureNanoCny===exposure.toString()&&proof.snapshot.remainingNewEnvelopeNanoCny===(BigInt(config.envelopeNanoCny)-exposure).toString()&&proof.snapshot.pendingCount===pendingCount&&proof.snapshot.newUnknownCount===unknownCount&&proof.snapshot.invoice===false&&proof.snapshot.foreignExchangeConversion===false,'cash_snapshot_replay');
 const journal=inspectCampaignJournal(config.journalDirectory);demand(journal.valid&&journal.accountingClosed&&journal.snapshot?.acceptedRequestCount===states.size&&same(journal.prefix,proof.journalPrefix)&&pendingCount===0&&unknownCount===0&&proof.releasePermitted===true,'cash_or_peer_not_closed');return{proof,config,states};
}
