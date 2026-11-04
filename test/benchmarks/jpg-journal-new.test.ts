import { expect, test } from 'bun:test';
import { randomBytes } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join, resolve } from 'node:path';
import { Database } from 'bun:sqlite';
import { createCampaignJournal, inspectCampaignJournal } from '../../scripts/benchmark-repair/campaign-journal.ts';
import { ScientificJournalProxy } from '../../scripts/benchmark-repair/scientific-journal-proxy.ts';
import { createCnyCashShadow, verifyCashClosure, type CashTicket } from '../../scripts/benchmark-repair/cny-cash-shadow-v2.ts';
import { actualPin, hash } from '../../scripts/benchmark-repair/paid-resource-proof-v2.ts';
import { durableJpgJson, jpgCrossFamilyPreflight, scanJpgPaidRuns, verifyJpgCertificate } from '../../scripts/benchmark-repair/jpg-paid-resource-admission-v1.ts';
import { JPG_FAMILY, JPG_FROZEN, assertJpgClosureShape, validateJpgRecipe } from '../../scripts/benchmark-repair/jpg-journal-contract.ts';
import { loadNativePython } from '../../scripts/benchmark-repair/skb-jpg-native-python.ts';
import { stoppedJpgSnapshot, prepareJpgJournal } from '../../scripts/benchmark-repair/skb-jpg-journal-campaign.ts';
const ROOT=resolve(import.meta.dir,'../..'),BASE=join(ROOT,'.scratch/jpg-journal-new-controls');
function home(){const p=join(BASE,randomBytes(8).toString('hex'));mkdirSync(p,{recursive:true});return p;}
const request=JSON.stringify({model:'deepseek-flash',temperature:0,seed:42,reasoning_effort:'none',max_tokens:8192,messages:[{role:'user',content:'public harmless fixture'}]});
function prices(p:string){return durableJpgJson(join(p,'prices.json'),{protocol:'deepseek-cny-pricing-source-snapshot-v1',currency:'CNY',model:'deepseek-flash',modelCalls:0,officialSource:'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/',observedAtUtc:new Date().toISOString(),peak:{uncachedInput:2,cachedInput:.04,output:8},offPeak:{uncachedInput:1,cachedInput:.02,output:4}});}
function fixture(){const p=home(),runId='repair-2026-10-09T00-00-00-000Z',journal=createCampaignJournal({directory:join(p,'journal'),campaign:runId,capUsd:1,priorCampaignCostUpperBoundUsd:0,outputDirectory:p}),cash=createCnyCashShadow({directory:join(p,'cash'),runId,providerKind:'local-mock',prices:prices(p),journal:{directory:join(p,'journal'),configPin:actualPin(join(p,'journal/journal-config.json')),sourcePin:{path:join(ROOT,'scripts/benchmark-repair/campaign-journal.ts'),sha256:JPG_FROZEN['campaign-journal.ts']}}});return{p,journal,cash,runId};}
test('four admitted local requests finish out of order with actual gzip/fsync and one compatible export',async()=>{
  const f=fixture(),tickets=new Map<number,CashTicket>(),gates:Map<number,()=>void>=new Map(),observed:number[]=[];
  const proxy=new ScientificJournalProxy(f.journal,{routes:new Set(['U','F']),failureDirectory:join(f.p,'failures'),beforeForward:(a,prefix,raw,route)=>{const v=f.cash.beforeForward({id:'id-'+a.requestSeq,route,rawRequest:Buffer.from(raw),capturedRequest:actualPin(a.requestFile),journal:{admitted:a,startPrefix:prefix}});expect(v.admitted).toBe(true);tickets.set(a.requestSeq,v.ticket);},afterDurableFinish:r=>{observed.push(r.requestSeq);f.cash.finish(tickets.get(r.requestSeq)!,{kind:'journal-finish',journalRef:{...r.journalRef,callId:String(r.requestSeq)}});},transport:async()=>{const n=gates.size;await new Promise<void>(ok=>gates.set(n,ok));return{httpStatus:200,rawResponse:JSON.stringify({id:'toy-'+n,model:'local-mock',choices:[{message:{role:'assistant',content:'public fixture'}}],usage:{prompt_tokens:10,completion_tokens:4,prompt_cache_hit_tokens:9}})};}});
  const jobs=Array.from({length:4},(_,i)=>proxy.handle(i%2?'F':'U',request));for(let i=0;i<100&&gates.size<4;i++)await Bun.sleep(1);expect(gates.size).toBe(4);expect(f.cash.snapshot().pendingCount).toBe(4);
  for(const n of [3,1,0,2]){gates.get(n)!();for(let i=0;i<100&&!observed.includes(n);i++)await Bun.sleep(1);}await Promise.all(jobs);await proxy.drain();expect(observed).toEqual([3,1,0,2]);
  const exported=f.journal.exportLegacyLedger();expect(exported.accountingClosed).toBe(true);const close=f.cash.close();expect(verifyCashClosure(close).proof.snapshot.newExposureNanoCny).toBe('0');expect(inspectCampaignJournal(join(f.p,'journal')).accountingClosed).toBe(true);
  const ledger=JSON.parse(readFileSync(exported.path,'utf8'));expect(ledger.calls.length).toBe(4);expect(ledger.recordedUsageUpperBoundUsd).toBeCloseTo(.000005154*4,14);expect(f.journal.snapshot().acceptedRequestCount).toBe(4);
  const harness=join(f.p,'audit-harness.py');writeFileSync(harness,"import importlib.util,json,sys\ns=importlib.util.spec_from_file_location('audit',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\nf=m.journal_audit(*map(json.loads,sys.argv[2:5]),sys.argv[5]);print(json.dumps({'valid':True,'calls':len(f['calls'])}))\n");
  const python=loadNativePython();const out=execFileSync(python.executable,['-B','-X','utf8',harness,join(ROOT,'scripts/benchmark-repair/audit-jpg-journal-campaign.py'),JSON.stringify(actualPin(join(f.p,'journal/journal-config.json'))),JSON.stringify(actualPin(join(f.p,'journal/api-events.jsonl'))),JSON.stringify(actualPin(exported.path)),process.execPath],{windowsHide:true,encoding:'utf8',timeout:20000});expect(JSON.parse(out).calls).toBe(4);
  durableJpgJson(join(f.p,'control-result.json'),{protocol:'jpg-journal-local-control-v1',passed:true,actualFsyncCounts:f.journal.snapshot().metrics,providerKind:'local-mock',realProviderRequests:0,DockerOperations:0,productionLockAcquired:false});f.journal.close();
});
test('a live scientific scope rejects a new JPG paid scope in the read-only cross-family scanner',()=>{
  const p=home(),dir=join(p,'docs/repair-2026-10-08/campaigns/science-active');mkdirSync(dir,{recursive:true});durableJpgJson(join(dir,'api-ledger.json'),{reservedUpperBoundUsd:0,pending:{},calls:[]});durableJpgJson(join(dir,'summary.json'),{completed:false});expect(()=>jpgCrossFamilyPreflight(p,'jpg-new')).toThrow('unfinished_other_campaign');
});
test('an unclosed or scientific-shaped JPG registry cannot pass by a released boolean',()=>{
  const p=home(),dir=join(p,'docs/repair-2026-10-08/jpg-journal-campaigns/jpg-old');mkdirSync(dir,{recursive:true});durableJpgJson(join(dir,'jpg-paid-resource-run.json'),{protocol:'paid-resource-v2-run',family:JPG_FAMILY,runId:'jpg-old',released:true,certificationPin:null});expect(()=>scanJpgPaidRuns(p,'jpg-new')).toThrow('jpg_other_unclosed');
});
test('a science certificate or score boolean cannot certify the JPG family',()=>{
  expect(()=>assertJpgClosureShape({protocol:'paid-resource-final-certificate-v2',completed:true},'jpg-new','real-provider')).toThrow('jpg_certificate_family');const p=home(),pin=durableJpgJson(join(p,'fake.json'),{protocol:'jpg-journal-final-certificate-v1',family:JPG_FAMILY,runId:'jpg-new',providerKind:'local-mock',completed:false,mockWorkflowCompleted:true,formalScoreCertified:false});expect(()=>verifyJpgCertificate(pin,'jpg-new','local-mock')).toThrow('jpg_certificate_graph_missing');
});
test('an interrupted in-flight proxy is not a zero-fee score closure',async()=>{
  const f=fixture();let ticket:CashTicket|undefined,release!:()=>void;const proxy=new ScientificJournalProxy(f.journal,{routes:new Set(['U']),failureDirectory:join(f.p,'failures'),beforeForward:(a,prefix,raw,route)=>{ticket=f.cash.beforeForward({id:'q',route,rawRequest:Buffer.from(raw),capturedRequest:actualPin(a.requestFile),journal:{admitted:a,startPrefix:prefix}}).ticket;},afterDurableFinish:r=>f.cash.finish(ticket!,{kind:'journal-finish',journalRef:{...r.journalRef,callId:String(r.requestSeq)}}),transport:async()=>{await new Promise<void>(ok=>release=ok);throw new Error('LocalTransportFailure');}});
  const job=proxy.handle('U',request);for(let i=0;i<100&&!release;i++)await Bun.sleep(1);proxy.stop('fixture_shutdown');release();await job;await proxy.drain();expect(f.cash.snapshot().newUnknownCount).toBe(1);expect(f.journal.exportLegacyLedger().eligibleForScoreCertification).toBe(false);expect(f.cash.close()).toBeDefined();expect(f.cash.snapshot().poisoned).toBe(true);f.journal.close();
});
test('stopped SQLite snapshot uses complete readonly materialized rows, with no HTTP default row limit',()=>{
  const p=home(),file=join(p,'h2h.sqlite'),db=new Database(file);db.exec('create table task(id text,mode text,created_at integer,solve_seconds integer,state text,result text);create table task_fixture(task text,agent text,instance text,unit integer);create table agent_bot_msg(instance text,unit integer,seq integer,kind text,body text,at integer);create table agent_bot_ctx(instance text,unit integer,done integer);create table cycle(mode text,cycle text);');
  db.exec("insert into task values('toy','fixture',0,1800,'done',NULL);insert into task_fixture values('toy','bot','toy#0',0);insert into agent_bot_ctx values('toy#0',0,1);insert into cycle values('fixture','submit');");
  const insert=db.query('insert into agent_bot_msg values(?,?,?,?,?,?)');try{for(let i=0;i<601;i++)insert.run('toy#0',0,i,'prompt','public toy line',1);insert.run('toy#0',0,601,'call',JSON.stringify({calls:[{name:'submit',input:{answer:'timely'}}]}),1800000);insert.run('toy#0',0,602,'call',JSON.stringify({calls:[{name:'submit',input:{answer:'too late'}}]}),1800001);}finally{insert.finalize();db.close();}
  const snapshot=stoppedJpgSnapshot(file,'toy');expect(snapshot.trace.length).toBe(603);expect(snapshot.units.length).toBe(1);expect(snapshot.candidate?.body).toBe('timely');
  const task={databasePins:[actualPin(file)],taskId:'toy',arm:'U',actualCreatedAt:0,state:'done',deadlineUnixMs:1800000,runtimeVerdict:{valid:true,outcome:'unaided_generated'},trace:snapshot.trace,units:snapshot.units,candidate:'timely',candidateHow:'submitted',candidateSha256:hash('timely'),explicitVerifyCalls:0};
  const taskPath=join(p,'task.json');durableJpgJson(taskPath,task);const harness=join(p,'database-harness.py');writeFileSync(harness,"import importlib.util,json,sys\ns=importlib.util.spec_from_file_location('audit',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\nv=m.database_task(m.read(m.Path(sys.argv[2])));print(json.dumps({'candidate':v,'parentPresent':not m.process_absent(int(sys.argv[3]))}))\n");
  const out=execFileSync(loadNativePython().executable,['-B','-X','utf8',harness,join(ROOT,'scripts/benchmark-repair/audit-jpg-journal-campaign.py'),taskPath,String(process.pid)],{windowsHide:true,encoding:'utf8',timeout:15000});expect(JSON.parse(out)).toEqual({candidate:'timely',parentPresent:true});
});
test('the actual prepare branch is F-only and pins every new execution source without entering paid registry',()=>{
  const p=home(),value=prepareJpgJournal({providerKind:'local-mock',storeRoot:join(p,'unused-store'),capUsd:1,priorUsd:0,prices:prices(p)}),r=JSON.parse(readFileSync(value.recipePath,'utf8'));
  expect(value.modelCalls).toBe(0);expect(value.DockerOperations).toBe(0);expect(value.formalPaidReady).toBe(false);expect(r.sourcePins.filter((s:any)=>/jpg-journal|jpg-paid-resource/.test(s.path)).length).toBe(4);
  expect(()=>validateJpgRecipe({...r,sourcePins:r.sourcePins.filter((s:any)=>!s.path.endsWith('jpg-paid-resource-admission-v1.ts'))})).toThrow('jpg_complete_execution_source_set');
});
