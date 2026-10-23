import { classifyGeneration, type ApiReceipt, type GenerationClassification } from './campaign-contract.ts';
export const TASK_ID = 'jpg-ocr-stat';
export const PROTOCOL = 'skb-jpg-output-v1-preseed';
export const BASE_IMAGE_ID = 'sha256:6232b38791000e3818b58d8847b5a8f5612d606929e01156dd8febc423e0f2ef';
export const ENV_SHA = '3f8c727f88febafc7e4849c40dbbfe438b5e3ff13813731faf5b2b681e055d00';
export const REVOKED_IMAGE_IDS = ['sha256:a1886ce02bdbee6996a9804098717fb148a7a9a6851631ac2524e58117f0bc7c'];
export const PUBLIC_WORKSPACE={path:'/app/workspace',verified:true,fileCount:22,filesSha256:'8c24971cb259b208ab5c2db96cc3f51948c1a7f2be66a97eb2658b4dcb81cef9'};
export const ARTIFACT = '/app/workspace/stat_ocr.xlsx';
export const SECONDS = 1800, VERIFY_SECONDS = 600, CHECKS = 6;
export const OFFICIAL_HASHES:Record<string,string> = {
  'task.md':'909d9ec531112404b5be041b24ba30b2b05df17ec5c0bd39a771c4b8da6fce47',
  'environment/Dockerfile':'8eac22e4261d1d8b4bba9e1f2010e77a6eeeafd489ada9a3b38fb456f971b61a',
  'oracle/solve.sh':'a32e364bcd8b0b214e3510c4855ee17be8e75b4490f7be19d0cf24ddd3677ce3',
  'verifier/test.sh':'013e2ee5d258c992c360d5b0d48a39e3efece51d49fad9c84c66fd211905df77',
  'verifier/test_outputs.py':'5956de9cf2d3f26d9b77ba17ae74b3987d6a802b6c6cfffc27fe307649d353a6',
  'verifier/stat_oracle.xlsx':'6e49264c150733702db04181c8c805a7a84555da8b2661063f2c4d46aa1c0c0d',
};
export function jpgObjective(stand:string) { return {nodes:[{name:'verified',domain:'bool',moment:'done',handle:stand+'/verified'},{name:'passed',domain:'bool',moment:'done',handle:stand+'/passed'}],edges:[{src:'verified',out:0,dst:'passed'}],sink:'passed',checks:CHECKS,reuse:'never'}; }
export function requirePaidJpgGate(input:{controls:any;image:any;build:any;profile:any;graderSha:string}) {
  const {controls:c,image:m,build:b,profile:p}=input;
  if(c?.validated!==true || c.taskId!==TASK_ID || c.protocol!==PROTOCOL || c.denominator!==87 || c.unsupportedTaskCount!==86 || c.controlValidatedTaskIds?.length!==1 || c.controlValidatedTaskIds[0]!==TASK_ID || c.mock===true)throw new Error('Paid JPG requires latest three real official controls');
  const id=m?.imageId;
  if(!/^sha256:[0-9a-f]{64}$/.test(id??'') || id===BASE_IMAGE_ID || REVOKED_IMAGE_IDS.includes(id) || m.completeOriginalTaskImage!==true || m.taskId!==TASK_ID || m.baseImageId!==BASE_IMAGE_ID || m.environmentSha256!==ENV_SHA || c.imageId!==id || b?.imageId!==id || p?.imageId!==id)throw new Error('Paid JPG requires the complete immutable original task image');
  for(const [path,sha]of Object.entries(OFFICIAL_HASHES))if(c.originalSourceHashes?.[path]!==sha || m.sourceHashes?.[path]!==sha)throw new Error('JPG official source gate mismatch: '+path);
  for(const record of [m,b])for(const [key,value]of Object.entries(PUBLIC_WORKSPACE))if(record.publicWorkspaceVerification?.[key]!==value)throw new Error('JPG actual public workspace path/file SHA certificate is incomplete');
  if(c.graderSourceSha256!==input.graderSha)throw new Error('JPG controls must freeze the actual private grader source');
  const limits:Record<string,number>={uniquePublicCacheBytes:160*1024**2,hostDependencyCacheBytes:224*1024**2,maxBuildWritableBytes:375*1024**2,dockerHostGrowthBytes:1024**3};
  if(b?.validated!==true || b.actualBuildCompleted!==true || b.minimumCFreeBytes<1536*1024**2 || b.minimumFFreeBytes<1024**3)throw new Error('JPG actual resource/source/image build gate is incomplete');
  for(const [key,max]of Object.entries(limits))if(!Number.isSafeInteger(b[key])||b[key]<0||b[key]>max)throw new Error('JPG actual build resource limit mismatch: '+key);
  if(p.protocol!==PROTOCOL || p.uv!=='0.9.7' || p.python!=='3.12.3' || p.packages?.pytest!=='8.4.1' || p.packages?.['pytest-json-ctrf']!=='0.3.5' || p.packages?.openpyxl!=='3.1.5' || !Array.isArray(p.assets)||p.assets.length===0)throw new Error('JPG private dependency profile is incomplete');
  for(const [phase,expected]of [['empty',0],['oracle',1],['wrongWorkbook',0]]as const){const v=c.phases?.[phase];if(v?.valid!==true||v.ran!==true||v.reward!==expected||v.completedTests!==1||v.passedTests!==expected||v.imageId!==id||v.protocol!==PROTOCOL)throw new Error('JPG real official control incomplete: '+phase);}
}
export function artifactVerdict(raw:any, capture:any, candidateSha256:string, generation:GenerationClassification) {
  const base={candidateSha256,artifactSha256:capture?.artifactSha256??null,artifactCapture:capture,nodes:{}};
  if(!generation.valid)return {...base,valid:false,passed:false,outcome:generation.outcome,why:generation.why};
  if(generation.kind==='experimental_failure')return {...base,valid:true,passed:false,outcome:generation.outcome,why:generation.why};
  if(raw?.validated!==true || raw.mock===true || raw.formalLlmClosedLoopValidated!==false || raw.candidateVerdict?.valid!==true || raw.candidateVerdict?.ran!==true || raw.candidateVerdict?.completedTests!==1 || ![0,1].includes(raw.candidateVerdict?.reward) || raw.candidateVerdict?.passedTests!==raw.candidateVerdict?.reward || raw.candidateVerdict?.protocol!==PROTOCOL || (capture?.state==='regular' && raw.candidateVerdict.artifactSha256!==capture.artifactSha256))return {...base,valid:false,passed:false,outcome:'grader_error',why:'private artifact-only verdict is missing, incomplete or changed'};
  const v=raw.candidateVerdict;
  return {...base,valid:true,passed:v.reward===1,outcome:v.reward===1?'passed':['budget_exhausted','invalid_artifact'].includes(v.outcome)?v.outcome:'rejected',why:v.reward===1?'':'official output-only verifier rejected the fixed captured workbook',nodes:{verified:{valid:true,value:true},passed:{valid:true,value:v.reward===1}},verdict:v};
}
export function jpgGeneration(input:{runtimeVerdict:unknown;state:string;calls:ApiReceipt[];trace:{role?:unknown;kind?:unknown;body?:unknown;at?:unknown}[];candidate?:string;deadline:number;receipts:{tool:string;forwarded:boolean;finishedAt?:number}[];capture?:any}) {
  const classified=classifyGeneration(input);
  if(!classified.valid)return classified;
  if(input.receipts.some(r=>r.forwarded&&['bash','write','edit'].includes(r.tool)&&Number(r.finishedAt)>input.deadline) || (input.capture?.stoppedAt && input.capture.stoppedAt>input.deadline))return {...classified,kind:'experimental_failure' as const,outcome:'budget_exhausted',why:'a live mutation or workbook freeze completed after the declared deadline'};
  return classified;
}
export function mockCall(index:number,arm:string,live=false){
 const path=live?'/app/workspace/local-mock.txt':ARTIFACT;
 const command=live?"python3 - <<'PY'\nfrom openpyxl import Workbook\nw=Workbook();s=w.active;s.append(['filename','date','total_amount']);s.append(['007.jpg','2001-01-01',0]);w.save('/app/workspace/stat_ocr.xlsx')\nopen('/app/workspace/local-mock.txt','w').write('local-mock-wrong-workbook')\nPY":'printf local-mock';
 const actions=[{name:'bash',args:{command,timeout_ms:10000}},{name:'read',args:{file_path:path}},{name:'write',args:{file_path:path,content:'local-mock-wrong-workbook'}},{name:'edit',args:{file_path:path,old_string:'wrong',new_string:'rejected'}},{name:'glob',args:{pattern:'*.xlsx',path:'/app/workspace'}},{name:'grep',args:{pattern:'mock',path}},...(arm==='F'?[{name:'verify',args:{answer:'mock-workbook'}}]:[]),{name:'submit',args:{answer:'mock-workbook'}}];
 return actions[Math.min(index,actions.length-1)]!;
}
