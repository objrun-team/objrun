import {expect,test} from 'bun:test';
import {mkdtempSync,mkdirSync,readFileSync} from 'node:fs';
import {join} from 'node:path';
import {launchNativeJpgService} from '../../scripts/benchmark-repair/skb-jpg-native-python.ts';
import {TASK_ID,PROTOCOL,BASE_IMAGE_ID,REVOKED_IMAGE_IDS,PUBLIC_WORKSPACE,ENV_SHA,OFFICIAL_HASHES,CHECKS,jpgObjective,requirePaidJpgGate,jpgGeneration,artifactVerdict} from '../../scripts/benchmark-repair/skb-jpg-contract.ts';

const fixture=()=>{const id='sha256:'+'f'.repeat(64);return {graderSha:'fixture-grader',image:{imageId:id,taskId:TASK_ID,baseImageId:BASE_IMAGE_ID,environmentSha256:ENV_SHA,sourceHashes:OFFICIAL_HASHES,completeOriginalTaskImage:true},build:{imageId:id,validated:true,actualBuildCompleted:true,minimumCFreeBytes:2*1024**3,minimumFFreeBytes:2*1024**3,uniquePublicCacheBytes:1,hostDependencyCacheBytes:1,maxBuildWritableBytes:1,dockerHostGrowthBytes:1},profile:{imageId:id,protocol:PROTOCOL,uv:'0.9.7',python:'3.12.3',packages:{pytest:'8.4.1','pytest-json-ctrf':'0.3.5',openpyxl:'3.1.5'},assets:[{path:'fixture'}]},controls:{taskId:TASK_ID,protocol:PROTOCOL,denominator:87,unsupportedTaskCount:86,validated:true,imageId:id,controlValidatedTaskIds:[TASK_ID],graderSourceSha256:'fixture-grader',originalSourceHashes:OFFICIAL_HASHES,phases:Object.fromEntries([['empty',0],['oracle',1],['wrongWorkbook',0]].map(([name,reward])=>[name,{valid:true,ran:true,reward,passedTests:reward,completedTests:1,protocol:PROTOCOL,imageId:id}]))}};};
test('JPG paid gate rejects missing actual build, base substitution, partial controls and changed sources',()=>{
 const withWorkspace=()=>{const f=fixture();return {...f,image:{...f.image,publicWorkspaceVerification:PUBLIC_WORKSPACE},build:{...f.build,publicWorkspaceVerification:PUBLIC_WORKSPACE}};};
 expect(()=>requirePaidJpgGate(withWorkspace())).not.toThrow();
 const cases=[(f:any)=>f.controls.validated=false,(f:any)=>f.controls.mock=true,(f:any)=>f.build.actualBuildCompleted=false,(f:any)=>f.image.imageId=BASE_IMAGE_ID,(f:any)=>f.controls.phases.oracle.completedTests=0,(f:any)=>f.controls.phases.wrongWorkbook.reward=1,(f:any)=>f.controls.graderSourceSha256='changed',(f:any)=>f.build.dockerHostGrowthBytes=2*1024**3,(f:any)=>f.profile.uv='0.9.5',(f:any)=>f.controls.originalSourceHashes={...OFFICIAL_HASHES,'task.md':'changed'}];
 for(const change of cases){const f=withWorkspace();change(f);expect(()=>requirePaidJpgGate(f)).toThrow();}
 expect(()=>requirePaidJpgGate(fixture())).toThrow();
 const revoked=withWorkspace();revoked.image.imageId=REVOKED_IMAGE_IDS[0]!;revoked.build.imageId=revoked.profile.imageId=revoked.controls.imageId=revoked.image.imageId;for(const phase of Object.values(revoked.controls.phases))phase.imageId=revoked.image.imageId;expect(()=>requirePaidJpgGate(revoked)).toThrow();
 expect(jpgObjective('http://fixture').checks).toBe(CHECKS);expect(CHECKS).toBe(6);expect(jpgObjective('http://fixture').reuse).toBe('never');
});
test('fixed regular/absent verdicts preserve validity while missing or broken grader receipts stay invalid',()=>{
 const generation:any={valid:true,kind:'candidate'},base:any={validated:true,formalLlmClosedLoopValidated:false,candidateVerdict:{valid:true,ran:true,completedTests:1,passedTests:0,reward:0,protocol:PROTOCOL}};
 expect(artifactVerdict(base,{state:'absent'},'label',generation)).toMatchObject({valid:true,passed:false,outcome:'rejected'});
 expect(artifactVerdict({...base,candidateVerdict:{...base.candidateVerdict,artifactSha256:'regular'}},{state:'regular',artifactSha256:'regular'},'label',generation)).toMatchObject({valid:true,passed:false});
 expect(artifactVerdict(base,{state:'regular',artifactSha256:'changed'},'label',generation)).toMatchObject({valid:false,outcome:'grader_error'});
 expect(artifactVerdict({...base,validated:false},{state:'absent'},'label',generation)).toMatchObject({valid:false,outcome:'grader_error'});
 expect(artifactVerdict({...base,candidateVerdict:{...base.candidateVerdict,valid:false}},{state:'absent'},'label',generation)).toMatchObject({valid:false});
 expect(artifactVerdict(undefined,{state:'absent'},'label',{valid:true,kind:'experimental_failure',outcome:'no_candidate'}as any)).toMatchObject({valid:true,passed:false,outcome:'no_candidate'});
});
test('late tool mutation or final workbook freeze cannot earn a pass; infrastructure faults retain priority',()=>{
 const input:any={runtimeVerdict:{valid:true,outcome:'passed'},state:'done',calls:[{httpStatus:200,finishedAt:'closed',usage:{prompt_tokens:1,completion_tokens:1}}],trace:[],candidate:'label',deadline:1000,receipts:[]};
 expect(jpgGeneration({...input,capture:{stoppedAt:1001}})).toMatchObject({valid:true,kind:'experimental_failure',outcome:'budget_exhausted'});
 expect(jpgGeneration({...input,receipts:[{tool:'write',forwarded:true,finishedAt:1001}]})).toMatchObject({valid:true,outcome:'budget_exhausted'});
 expect(jpgGeneration({...input,capture:{stoppedAt:999}})).toMatchObject({valid:true,kind:'candidate'});
 expect(jpgGeneration({...input,runtimeVerdict:{valid:false,outcome:'grader_error'},capture:{stoppedAt:1001}})).toMatchObject({valid:false,kind:'infrastructure_error'});
});
test('the actual run entry fails before any paid setup when no real JPG controls exist',async()=>{
 const env={...process.env};for(const name of ['OBJRUN_SKB_JPG_CONTROLS_JSON','OBJRUN_SKB_JPG_IMAGE_JSON','OBJRUN_SKB_JPG_BUILD_JSON','OBJRUN_SKB_JPG_DEPENDENCY_JSON'])delete env[name];
 const p=Bun.spawn([process.execPath,join(import.meta.dir,'../../scripts/benchmark-repair/skb-jpg-campaign.ts'),'run'],{env,stdout:'pipe',stderr:'pipe'});
 const error=await new Response(p.stderr).text();expect(await p.exited).toBe(1);expect(error).toContain('Paid JPG is fail-closed');
},10000);
test('the actual local mock bridge protects all capture/tool routes and keeps two cold-arm captures distinct',async()=>{
 const scratch=join(import.meta.dir,'../../.scratch/jpg-native-lifecycle-v2');mkdirSync(scratch,{recursive:true});const home=mkdtempSync(join(scratch,'contract-fixture-')),probe=Bun.serve({hostname:'127.0.0.1',port:0,fetch:()=>new Response('')}),port=probe.port;await probe.stop(true);
 const service=launchNativeJpgService({script:join(import.meta.dir,'../../scripts/benchmark-repair/skb-jpg-stand.py'),argv:['--mode','mock','--port',String(port),'--home',home],home,port,env:{...process.env,TGENGIN_GRADER_TOKEN:'fixture-token'}}),child=service.child;child.stdout?.resume();child.stderr?.resume();
 const origin='http://127.0.0.1:'+port;
 const request=async(path:string,body:any,token='fixture-token')=>fetch(origin+path,{method:'POST',headers:{'X-ObjRun-Grader-Token':token,'content-type':'application/json'},body:JSON.stringify(body)});
 try{
  const health=await service.waitReady();expect(health.processIdentity.pid).toBe(child.pid);expect(health.denominator).toBe(87);expect(health.readyTaskIds).toEqual([]);expect(health.backend).toBe('mock');
  for(const path of ['/place','/capture','/stop','/grade-captured']){expect((await request(path,{},'')).status).toBe(401);expect((await request(path,{},'forged')).status).toBe(401);}
  const captures=[];
  for(const arm of ['U','F']){const place='skb:fixture/'+arm+'/'+TASK_ID;expect((await request('/place',{place,op:'ping'})).status).toBe(200);await request('/place',{place,tool:'write',args:{file_path:'/app/workspace/stat_ocr.xlsx',content:'mock-wrong-'+arm}});const verdict=await request('/verified',{input:{task:{place,result:'label'},result:{body:'label'}}});expect(verdict.status).toBe(200);expect(await verdict.json()).toMatchObject({value:false,valid:true,mock:true});const r=await request('/capture',{place,final:true});expect(r.status).toBe(200);const cap:any=await r.json();expect(cap.state).toBe('regular');expect(cap.mock).toBe(true);expect(cap.containerStopped).toBe(true);expect(readFileSync(cap.hostArtifactPath,'utf8')).toBe('mock-wrong-'+arm);captures.push(cap);await request('/stop',{place});}
  expect(captures[0].captureReceiptPath).not.toBe(captures[1].captureReceiptPath);
 }finally{const closed=await service.stop();expect(closed.closed).toBe(true);expect(closed.directChildExited&&closed.directChildClosed&&closed.portClosed).toBe(true);}
},10000);
