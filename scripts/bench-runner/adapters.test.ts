import { test, expect } from 'bun:test';
import { mkdtempSync,writeFileSync,readFileSync,existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { getAdapter } from './adapters/index.ts';
import { filePin,expand,executeCommand,actualProcess } from './runtime.ts';
import type { TaskManifest,AttemptContext,StageSpec,Bench } from './types.ts';
import { generateKeyPairSync,sign } from 'node:crypto';
import { prepareContextDraft,loadPreparedContext } from './bindings.ts';

function fixture(bench:Bench='terminal-bench') {
  const root=mkdtempSync(join(tmpdir(),'bench-adapter-'));
  const contract=join(root,'contract.json');writeFileSync(contract,JSON.stringify({original:true}));
  const driver=join(root,'driver.ts');writeFileSync(driver,`import{writeFileSync}from'node:fs';const [path,attempt,task,bench,stage]=process.argv.slice(2);writeFileSync(path,JSON.stringify({protocol:'bench-driver-result-v1',attemptId:attempt,taskId:task,bench,stage,result:{status:'complete',proofPins:[],nativeClosed:false,financialClosed:false,candidateOrSubmissionPresent:false}}));await Bun.sleep(100);`);
  const manifest:TaskManifest={schemaVersion:1,taskId:'local-fake-only',bench,root,artifactRoot:root,
    original:{cpu:1,memoryMb:64,solveSeconds:3,gradeSeconds:3,toolSeconds:3,providerSeconds:600,model:'local-fake',provider:'none',reasoning:'none',taskCapUsd:1,priorKnownUsd:0,priorUnknownUsd:0},
    provenance:{sourcePins:[filePin(process.execPath),filePin(driver)],contractPins:[filePin(contract)],inventoryPin:filePin(contract)},
    history:{validResultPins:[],successfulStageProofs:{},priorRunPins:[],stateKnown:true,originalResultRecoveryRequired:false},stages:{},
    adapterConfig:{driverContract:{ownedLease:true,beforeJournal:true,beforeForward:true,originalBudget:true,pin:filePin(contract)},driverResult:{path:'{{runDir}}/result.json',protocol:'bench-driver-result-v1'}}};
  const mp=join(root,'manifest.json');writeFileSync(mp,JSON.stringify(manifest));
  const context:AttemptContext={attemptId:'local-attempt',taskId:manifest.taskId,bench,stage:'prepare',runDir:join(root,'run'),manifestPath:mp,manifestPin:filePin(mp),admissionControlPath:join(root,'closed-admission.json'),inventoryTask:{taskId:manifest.taskId,bench,state:'never-started',reason:'local fake',evidencePins:[],successfulStages:{},priorRunIds:[]}};
  const spec:StageSpec={kind:'command',effect:'read-only',timeoutSeconds:3,resourceMode:'none',evidencePins:[],command:[process.execPath,driver,'{{runDir}}/result.json','{{attemptId}}','{{taskId}}','{{bench}}','{{stage}}']};
  return {root,manifest,context,spec};
}
function syncManifest(f:ReturnType<typeof fixture>){writeFileSync(f.context.manifestPath,JSON.stringify(f.manifest));f.context.manifestPin=filePin(f.context.manifestPath);}
for(const bench of ['terminal-bench','skillsbench'] as Bench[]) test(bench+' fake driver persists exact custody, without real admission',async()=>{
  const f=fixture(bench);const result=await getAdapter(bench).execute(f.manifest,f.spec,f.context);
  expect(result.status).toBe('complete');expect(result.actualSolver).toBeUndefined();
  const custody=JSON.parse(readFileSync(join(f.context.runDir,'process.json'),'utf8'));
  expect(custody.incarnationStatus).toBe('exact-os-observed');expect(custody.argv).toEqual(f.spec.command!.map(x=>expand(x,f.context)));
  expect(existsSync(join(f.context.runDir,'exit.json'))).toBeTrue();
});
test('verified success reuse never executes driver',async()=>{
  const f=fixture();const proof=join(f.root,'qualified.json');writeFileSync(proof,JSON.stringify({complete:true,oracleCount:1}));
  const result=await getAdapter(f.manifest.bench).execute(f.manifest,{kind:'reuse',effect:'oracle',timeoutSeconds:1,evidencePins:[filePin(proof)],successEvidence:{path:proof,equals:{complete:true,oracleCount:1}}},f.context);
  expect(result.status).toBe('complete');expect(existsSync(f.context.runDir)).toBeFalse();
});
test('generation false remains invalid despite policyDerived acceptance',async()=>{
  const f=fixture('skillsbench');const task=join(f.root,'task.json'),summary=join(f.root,'summary.json');
  writeFileSync(task,JSON.stringify({taskId:f.manifest.taskId,runId:'same',protocolValid:true,generation:{valid:false},officialAcceptance:{valid:true,passed:true,policyDerived:true}}));writeFileSync(summary,JSON.stringify({runId:'same'}));
  f.manifest.history.originalResultRecoveryRequired=true;f.manifest.adapterConfig.originalResults=[{taskPin:filePin(task),summaryPin:filePin(summary)}];
  syncManifest(f);
  const result=await getAdapter('skillsbench').recover!(f.manifest,f.context);expect(result.status).toBe('unknown');expect(result.reason).toContain('original_generation');expect(existsSync(f.context.runDir)).toBeFalse();
});
test('unresolved original candidate prevents new command',async()=>{
  const f=fixture();f.manifest.history.originalResultRecoveryRequired=true;
  syncManifest(f);
  const result=await getAdapter(f.manifest.bench).execute(f.manifest,f.spec,f.context);expect(result.status).toBe('unknown');expect(existsSync(f.context.runDir)).toBeFalse();
});
test('changed source pin rejects before spawn',async()=>{
  const f=fixture();writeFileSync(f.spec.command![1],'changed');
  expect(getAdapter(f.manifest.bench).execute(f.manifest,f.spec,f.context)).rejects.toThrow('pin_changed');
});
test('unknown template and shell-shaped command cannot substitute fields',()=>{
  const f=fixture();expect(()=>expand('{{token}}',f.context)).toThrow('unknown_template');
  expect(expand('literal; $(noop)',f.context)).toBe('literal; $(noop)');
});
test('OS command line and parent identity are observed, not copied from a supplied receipt',()=>{
  const p=actualProcess(process.pid);expect(p.pid).toBe(process.pid);expect(p.parentPid).toBe(process.ppid);expect(p.argv.length).toBeGreaterThan(0);expect(p.incarnation.length).toBeGreaterThan(0);
});
test('stage timeout quarantines without killing driver',async()=>{
  const f=fixture();f.spec.timeoutSeconds=.02;
  const result=await executeCommand(f.manifest,f.spec,f.context);expect(result.timedOut).toBeTrue();expect(result.closeObserved).toBeFalse();
  expect(JSON.parse(readFileSync(join(f.context.runDir,'timeout.json'),'utf8')).processNotKilled).toBeTrue();
  await Bun.sleep(250);expect(existsSync(join(f.context.runDir,'exit.json'))).toBeTrue();
});
test('root binding data requires genuine local fixture signature and immutable old budget',()=>{
  const f=fixture(),keys=generateKeyPairSync('ed25519',{publicKeyEncoding:{type:'spki',format:'pem'},privateKeyEncoding:{type:'pkcs8',format:'pem'}});
  // Isolated test authority only; the production authority and private key are never accessed.
  const pub=join(f.root,'local-test-authority.pem');writeFileSync(pub,keys.publicKey);
  const template=join(f.root,'entry-template.json');writeFileSync(template,JSON.stringify({taskId:f.manifest.taskId,bench:f.manifest.bench,nonce:'{{bindings.NONCE}}',queueClass:'formal',coordinatorReviewed:false,argv:[process.execPath,'{{bindings.OUTPUT}}','{{bindings.RECOVERY_ENTRY}}'],recovery:{oldKnownUsd:.2,oldUnknownUsd:.1,oldNonce:'immutable-old'}}));
  f.manifest.adapterConfig.bindingSpec={protocol:'bench-root-data-binding-v1',authorityPin:filePin(pub),entryTemplatePin:filePin(template),inputs:{},output:{root:f.root,prefix:'fake-output-'},expiresAtUtc:new Date(Date.now()+60000).toISOString()};
  f.manifest.stages.prepare={kind:'command',effect:'read-only',timeoutSeconds:3,evidencePins:[],command:[process.execPath,'{{bindings.OUTPUT}}','{{bindings.RECOVERY_ENTRY}}']};
  writeFileSync(f.context.manifestPath,JSON.stringify(f.manifest));f.context.manifestPin=filePin(f.context.manifestPath);
  const request=prepareContextDraft(f.manifest,f.context);expect(request.bindings.NONCE).toBe(f.context.attemptId);
  expect(existsSync(request.bindings.RECOVERY_ENTRY)).toBeFalse();
  const entry=JSON.parse(readFileSync(request.draftPin.path,'utf8'));entry.coordinatorReviewed=true;entry.phase='ready';
  const envelope={protocol:'novaeve-root-signed-entry-v4',entry,signature:sign(null,Buffer.from(JSON.stringify(entry)),keys.privateKey).toString('base64')};
  writeFileSync(request.bindings.ENTRY_ENVELOPE,JSON.stringify(envelope));
  const loaded=loadPreparedContext(f.manifest,f.context);expect(loaded.bindings!.NONCE).toBe(f.context.attemptId);
  expect(JSON.parse(readFileSync(request.bindings.RECOVERY_ENTRY,'utf8')).recovery.oldUnknownUsd).toBe(.1);
  envelope.entry.recovery.oldUnknownUsd=0;envelope.signature=sign(null,Buffer.from(JSON.stringify(envelope.entry)),keys.privateKey).toString('base64');writeFileSync(request.bindings.ENTRY_ENVELOPE,JSON.stringify(envelope));
  expect(()=>loadPreparedContext(f.manifest,f.context)).toThrow('root_template_field_changed:recovery');
});
test('oracle first success is eligible but an already successful checkpoint is reuse only',()=>{
  const f=fixture();f.manifest.stages.qualify={kind:'command',effect:'oracle',timeoutSeconds:3,resourceMode:'driver-owned',evidencePins:[],originalSuccessKey:'reference-v1',command:[process.execPath,'never-executed']};
  expect(()=>getAdapter(f.manifest.bench).validate(f.manifest)).not.toThrow();
  f.manifest.adapterConfig.successfulCheckpoints={'reference-v1':[f.manifest.provenance.contractPins[0]]};
  expect(()=>getAdapter(f.manifest.bench).validate(f.manifest)).toThrow('successful_reference_is_reuse_only');
});
