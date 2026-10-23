import {createHash} from 'node:crypto';
import {closeSync,existsSync,lstatSync,mkdirSync,openSync,readFileSync,readSync,realpathSync,statSync} from 'node:fs';
import {isAbsolute,join,relative,resolve} from 'node:path';
import {gunzipSync} from 'node:zlib';

export type Pin=Readonly<{path:string;sha256:string;bytes?:number}>;
export type Prefix=Readonly<{bytes:number;eventCount:number;lastSha256:string}>;
export type Clock=Readonly<{wallUnixMs():number;monotonicNs():bigint}>;
export const REAL_CLOCK:Clock=Object.freeze({wallUnixMs:()=>Date.now(),monotonicNs:()=>process.hrtime.bigint()});
export const JOURNAL_SOURCE_SHA=createHash('sha256').update(readFileSync(new URL('./campaign-journal.ts',import.meta.url))).digest('hex');
export class ResourceAdmissionError extends Error{constructor(readonly code:string){super(code);this.name='ResourceAdmissionError';}}
export function demand(value:unknown,code:string):asserts value{if(!value)throw new ResourceAdmissionError(code);}
export const hash=(b:Uint8Array|string)=>createHash('sha256').update(b).digest('hex');
export const same=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b);
export const inside=(parent:string,path:string)=>{const r=relative(resolve(parent),resolve(path));return r===''||(!r.startsWith('..')&&!isAbsolute(r));};
export function ordinaryDirectory(path:string){const p=resolve(path);mkdirSync(p,{recursive:true});demand(lstatSync(p).isDirectory()&&!lstatSync(p).isSymbolicLink()&&realpathSync(p)===p,'ordinary_directory_required');return p;}
export function fileHash(path:string){
 const before=statSync(path),fd=openSync(path,'r'),digest=createHash('sha256'),buffer=Buffer.alloc(65536);let at=0;
 try{while(at<before.size){const n=readSync(fd,buffer,0,Math.min(buffer.length,before.size-at),at);demand(n>0,'hash_short_read');digest.update(buffer.subarray(0,n));at+=n;}}finally{closeSync(fd);}
 const after=statSync(path);demand(before.size===after.size&&before.mtimeMs===after.mtimeMs,'file_changed_during_hash');return digest.digest('hex');
}
export function verifyPin(pin:Pin,base?:string,maxBytes=128*1024**2){
 demand(pin&&typeof pin.path==='string'&&/^[a-f0-9]{64}$/.test(pin.sha256),'invalid_pin');
 const path=isAbsolute(pin.path)?resolve(pin.path):resolve(base??'.',pin.path);demand(lstatSync(path).isFile()&&!lstatSync(path).isSymbolicLink(),'pin_not_regular');
 const size=statSync(path).size;demand(size<=maxBytes&&(pin.bytes===undefined||pin.bytes===size)&&fileHash(path)===pin.sha256,'pin_changed');return path;
}
export function actualPin(path:string):Pin{return{path:resolve(path),bytes:statSync(path).size,sha256:fileHash(path)};}
export function jsonPin(pin:Pin,base?:string){return JSON.parse(readFileSync(verifyPin(pin,base),'utf8'));}
export function nanoCny(decimal:string):bigint{demand(typeof decimal==='string'&&/^\d+(?:\.\d{1,9})?$/.test(decimal),'invalid_cny_decimal');const [i,f='']=decimal.split('.');return BigInt(i!)*1000000000n+BigInt(f.padEnd(9,'0'));}
export function cny(n:bigint){const sign=n<0n?'-':'';const a=n<0n?-n:n;return sign+(a/1000000000n).toString()+((a%1000000000n)?'.'+(a%1000000000n).toString().padStart(9,'0').replace(/0+$/,''):'');}
export function integer(n:unknown):n is number{return typeof n==='number'&&Number.isSafeInteger(n)&&n>=0;}
export function requestValues(raw:Uint8Array){
 demand(raw.byteLength>0&&raw.byteLength<=4*1024**2,'request_size');const data=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));
 demand(data.model==='deepseek-flash'&&data.stream!==true&&Array.isArray(data.messages),'request_profile');
 const a=data.max_tokens,b=data.max_completion_tokens;demand((a===undefined||integer(a))&&(b===undefined||integer(b))&&(a===undefined||b===undefined||a===b),'output_limit');const output=a??b;demand(integer(output)&&output>0&&output<=16384,'output_limit');
 const upper=raw.byteLength+2048+data.messages.length*256;demand(integer(upper),'input_bound');return{data,inputUpper:upper,output,peakNano:BigInt(upper)*2000n+BigInt(output)*8000n};
}
export function gzipProof(pin:Pin,rawSha:string,base?:string,maxRaw=64*1024**2){
 const path=verifyPin(pin,base,65*1024**2),before=statSync(path),raw=gunzipSync(readFileSync(path),{maxOutputLength:maxRaw});
 demand(hash(raw)===rawSha&&statSync(path).mtimeMs===before.mtimeMs&&statSync(path).size===before.size,'raw_digest_changed');return raw;
}
export function validatePrices(pin:Pin,base?:string){
 const p=jsonPin(pin,base);demand(p.protocol==='deepseek-cny-pricing-source-snapshot-v1'&&p.currency==='CNY'&&p.model==='deepseek-flash'&&p.modelCalls===0,'price_profile');
 demand(p.officialSource==='https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'&&same(p.peak,{uncachedInput:2,cachedInput:0.04,output:8})&&same(p.offPeak,{uncachedInput:1,cachedInput:0.02,output:4}),'price_rates');return p;
}
export function peakWindow(start:number,end:number){
 if(!Number.isFinite(start)||!Number.isFinite(end)||end<start)return{peak:true,clockFault:true};
 if(end-start>32*86400000)return{peak:true,clockFault:false};
 const shifted=start+8*3600000,last=end+8*3600000;let day=Math.floor(shifted/86400000)*86400000;
 for(;day<=last;day+=86400000){const weekday=new Date(day).getUTCDay();if(weekday===0||weekday===6)continue;for(const [s,e]of [[9,12],[14,18]])if(last>=day+s!*3600000&&shifted<=day+e!*3600000)return{peak:true,clockFault:false};}
 return{peak:false,clockFault:false};
}
export function pricedUsage(usage:any,peak:boolean){
 demand(usage&&integer(usage.prompt_tokens)&&integer(usage.completion_tokens),'usage_missing_or_invalid');
 const hit=usage.prompt_cache_hit_tokens??0;demand(integer(hit)&&hit<=usage.prompt_tokens,'cache_usage_invalid');
 if(usage.prompt_cache_miss_tokens!==undefined)demand(integer(usage.prompt_cache_miss_tokens)&&usage.prompt_cache_miss_tokens+hit===usage.prompt_tokens,'cache_usage_invalid');
 const miss=usage.prompt_tokens-hit;return BigInt(miss)*(peak?2000n:1000n)+BigInt(hit)*(peak?40n:20n)+BigInt(usage.completion_tokens)*(peak?8000n:4000n);
}

/** Incremental chain verification accepts historical prefixes after later EOF. */
export class JournalBinding{
 readonly config:any;readonly configPath:string;readonly path:string;readonly configSha:string;
 private prefix:Prefix;private checkpoints=new Map<number,Prefix>();private starts=new Map<number,any>();private finishes=new Map<number,{frame:any;offset:number;end:number;sha:string}>();
 constructor(readonly directory:string,readonly configPin:Pin,readonly sourcePin:Pin){
  demand(sourcePin.sha256===JOURNAL_SOURCE_SHA,'journal_source_version');verifyPin(sourcePin);this.configPath=verifyPin(configPin);demand(resolve(this.configPath)===join(resolve(directory),'journal-config.json'),'journal_config_path');
  this.config=JSON.parse(readFileSync(this.configPath,'utf8'));demand(this.config.protocol==='campaign-api-journal-v1'&&this.config.pendingLimit===4&&this.config.model==='deepseek-flash','journal_config_profile');
  this.configSha=configPin.sha256;this.path=join(resolve(directory),'api-events.jsonl');this.prefix={bytes:0,eventCount:0,lastSha256:this.configSha};this.checkpoints.set(0,this.prefix);
 }
 consume(target:Prefix){
  demand(integer(target.bytes)&&integer(target.eventCount)&&/^[a-f0-9]{64}$/.test(target.lastSha256),'invalid_journal_prefix');
  if(target.bytes<=this.prefix.bytes){demand(same(this.checkpoints.get(target.bytes),target),'unknown_historical_prefix');return;}
  demand(existsSync(this.path)&&statSync(this.path).size>=target.bytes,'journal_prefix_missing');
  const fd=openSync(this.path,'r');let at=this.prefix.bytes,carry=Buffer.alloc(0);
  try{while(at<target.bytes){const b=Buffer.alloc(Math.min(16384,target.bytes-at));const n=readSync(fd,b,0,b.length,at);demand(n>0,'journal_short_read');at+=n;carry=Buffer.concat([carry,b.subarray(0,n)]);let nl:number;
   while((nl=carry.indexOf(10))>=0){const line=carry.subarray(0,nl+1);demand(line.length<=65536,'journal_line_limit');const frame=JSON.parse(line.subarray(0,-1).toString('utf8'));
    demand(Buffer.from(JSON.stringify(frame)+'\n').equals(line)&&frame.protocol==='campaign-api-journal-v1'&&frame.eventSeq===this.prefix.eventCount&&frame.previousEventSha256===this.prefix.lastSha256&&integer(frame.requestSeq),'journal_chain');
    const offset=this.prefix.bytes,end=offset+line.length,sha=hash(line);
    if(frame.kind==='start'){demand(!this.starts.has(frame.requestSeq),'duplicate_start');this.starts.set(frame.requestSeq,frame);}else if(frame.kind==='finish'){demand(this.starts.has(frame.requestSeq)&&!this.finishes.has(frame.requestSeq),'duplicate_or_unknown_finish');this.finishes.set(frame.requestSeq,{frame,offset,end,sha});}else demand(false,'journal_kind');
    this.prefix={bytes:end,eventCount:this.prefix.eventCount+1,lastSha256:sha};this.checkpoints.set(end,this.prefix);carry=carry.subarray(nl+1);
   }demand(carry.length<=65536,'journal_line_limit');
  }}finally{closeSync(fd);}demand(carry.length===0&&same(this.prefix,target),'journal_prefix_mismatch');
 }
 start(seq:number,prefix:Prefix){this.consume(prefix);const frame=this.starts.get(seq);demand(frame&&frame.eventSeq===prefix.eventCount-1,'not_this_start_prefix');return frame.record;}
 finish(seq:number,ref:{finishOffset:number;finishEnd:number;finishLineSha256:string}){
  demand(integer(ref.finishOffset)&&integer(ref.finishEnd)&&ref.finishEnd>ref.finishOffset&&ref.finishEnd-ref.finishOffset<=65536,'finish_offset');
  const fd=openSync(this.path,'r'),line=Buffer.alloc(ref.finishEnd-ref.finishOffset);try{demand(readSync(fd,line,0,line.length,ref.finishOffset)===line.length,'finish_short_read');}finally{closeSync(fd);}
  demand(hash(line)===ref.finishLineSha256&&line.at(-1)===10,'finish_digest');const f=JSON.parse(line.subarray(0,-1).toString('utf8'));demand(f.kind==='finish'&&f.requestSeq===seq,'finish_sequence');
  this.consume({bytes:ref.finishEnd,eventCount:f.eventSeq+1,lastSha256:ref.finishLineSha256});const known=this.finishes.get(seq);demand(known&&known.offset===ref.finishOffset&&known.end===ref.finishEnd&&known.sha===ref.finishLineSha256,'finish_chain_membership');return known.frame.record;
 }
 current(){return{...this.prefix};}
}
