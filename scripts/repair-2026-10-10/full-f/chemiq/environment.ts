import {execFileSync} from 'node:child_process';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {ROOT,OUT,save,prepare} from './prepare.ts';
import {actualPin,hash} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
const CONTAINER='objrun-chemiq-full-f-20261010', ORIGIN='http://127.0.0.1:17918';
export async function verifyEnvironment(){
  const plan=prepare(),inspect=JSON.parse(execFileSync('docker',['inspect',CONTAINER],{encoding:'utf8',windowsHide:true}))[0];
  if(!inspect.State.Running||!inspect.HostConfig.ReadonlyRootfs||inspect.HostConfig.Privileged||inspect.HostConfig.NetworkMode!=='bridge'||inspect.HostConfig.CapDrop?.join()!=='ALL')throw Error('Grader isolation mismatch');
  const health=await(await fetch(ORIGIN+'/health')).json();
  if(health.items!==816||health.level!==0||health.opsin.profile!=='local-2.8'||health.opsin.rest_fallback!==false||health.length_policy!=='raw-input-length')throw Error('Grader profile mismatch');
  const publicRows=await(await fetch(ORIGIN+'/problems?n=816')).json();
  const byId=new Map(publicRows.map((r:any)=>[r.id,r]));
  const {scientificPrompt}=await import('../../../repair-2026-10-08/scientific-journal-plan.ts');
  if(byId.size!==816||plan.tasks.some(t=>hash(scientificPrompt('chemiq',byId.get(t.officialId)))!==t.promptSha256))throw Error('Live public prompts mismatch');
  const worker=readFileSync(join(ROOT,'scripts/repair-2026-10-08/chemiq-grader-provenance.py'),'utf8');
  const runtime=JSON.parse(execFileSync('docker',['exec','-i',CONTAINER,'python','-','--worker'],{input:worker,encoding:'utf8',windowsHide:true,timeout:120000,maxBuffer:16*1024**2}));
  for(const name of ['parser','answer_verifier'])if(runtime.public_modules['utils.'+name].sha256!==actualPin(join(ROOT,'.phase1-data/chemiq/vendor/ChemIQ/utils',name+'.py')).sha256)throw Error('Runtime official source mismatch');
  save('grader-runtime.json',runtime);
  save('grader-provenance.json',{protocol:'chemiq-full-f-grader-provenance-v1',observedAtUtc:new Date().toISOString(),health,containerId:inspect.Id,imageId:inspect.Image,command:[inspect.Path,...inspect.Args],hostConfig:inspect.HostConfig,mounts:inspect.Mounts,runtimePin:actualPin(join(OUT,'grader-runtime.json')),standPin:actualPin(join(ROOT,'examples/benchmark/chemiq/stand.py')),bridgePin:actualPin(join(import.meta.dir,'opsin_bridge.py')),jarPin:actualPin(join(ROOT,'.phase1-data/opsin/opsin-cli-2.8.0-jar-with-dependencies.jar')),datasetPin:plan.datasetPin,modelCalls:0});
  const refs=['legacy-chemiq-616-controls-private-references-raw-length.json','legacy-chemiq-200-controls-private-references-raw-length.json'].flatMap(n=>JSON.parse(readFileSync(join(ROOT,'docs/repair-2026-10-08',n),'utf8')).records);
  const byRef=new Map(refs.map((r:any)=>[r.task,r]));
  const controls:any[]=[];const dir=join(OUT,'private-controls');mkdirSync(dir,{recursive:true});
  // Private references are only sent to the isolated grader, never to solver or provider.
  for(const task of plan.tasks){
    const ref:any=byRef.get(task.officialId),positive=task.method==='opsin'?ref?.reference_name:ref?.positive_input;
    const variants=[['positive',positive,true],['wrongValue',task.method==='opsin'?ref?.wrong_structure_name:ref?.negative_input,false],['wrongFormat',task.method==='opsin'?'Z'.repeat(301):ref?.format_input,false]];
    const row:any={officialId:task.officialId,cases:[],positiveReferenceMissing:typeof positive!=='string'};
    for(const [kind,candidate,expected]of variants){if(typeof candidate!=='string'){row.cases.push({kind,skipped:true,reason:'reference_missing'});continue;}
      const raw=JSON.stringify({node:'correct',input:{task:{id:task.taskId},result:{body:candidate}}});
      const response=await fetch(ORIGIN+'/correct',{method:'POST',headers:{'content-type':'application/json'},body:raw,signal:AbortSignal.timeout(30000)});const text=await response.text();
      const receipt={kind,httpStatus:response.status,rawResponse:text,candidateSha256:hash(candidate),expected,passed:response.ok&&JSON.parse(text).value===expected,modelCalls:0};
      row.cases.push(receipt);
    }
    controls.push(row);writeFileSync(join(dir,'control-'+task.index+'.json'),JSON.stringify(row,null,2)+'\n');
    if(controls.length%50===0)save('control-progress.json',{checked:controls.length,denominator:816,modelCalls:0});
  }
  const failures=controls.flatMap(r=>r.cases.filter((c:any)=>!c.skipped&&!c.passed).map((c:any)=>({officialId:r.officialId,kind:c.kind,httpStatus:c.httpStatus})));
  save('environment-validation.json',{protocol:'chemiq-full-f-environment-validation-v1',observedAtUtc:new Date().toISOString(),officialQuestionCount:816,checked:controls.length,positiveReferenceMissing:controls.filter(r=>r.positiveReferenceMissing).map(r=>r.officialId),failures,valid:failures.length===0,modelCalls:0,privateControlsExposedToSolver:false});
  if(failures.length)throw Error('Real grader controls failed: '+failures.length);
}
if(import.meta.main)await verifyEnvironment();
