/** Prospective ten-task contract. No IO, process, model or Docker on import. */
import { lstatSync, readFileSync, readdirSync, realpathSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { actualPin, demand, hash, jsonPin, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { classifyGeneration, type ApiReceipt, type GenerationClassification } from './campaign-contract.ts';

export const SKB_ARTIFACT_FAMILY='skillsbench-artifact-journal-v1';
export const SKB_ARTIFACT_SELECTION_SHA='f4b8781fc636d67af17265bfffe41d9ff76195f4e9539d6cd37b5db6b29ee021';
export const SKB_ARTIFACT_METADATA_SHA='6cab5bd04910a9a8e1cb5285c0d6ccd905a7e5b172af9b6373c3f711d61466ee';
export const SKB_ARTIFACT_IDS=['3d-scan-calc','citation-check','court-form-filling','dapt-intrusion-detection','earthquake-plate-calculation','econ-detrending-correlation','jpg-ocr-stat','lab-unit-harmonization','offer-letter-generator','pptx-reference-formatting'] as const;
export type SkbArtifactId=typeof SKB_ARTIFACT_IDS[number];
export const SKB_ARTIFACT_MODEL={model:'deepseek-flash',temperature:0,seed:42,reasoningEffort:'none',maxTokens:8192} as const;
export const SKB_ARTIFACT_CHECKS=6;
export type ResourceBlock={agent:{timeout_sec:number};verifier:{timeout_sec:number;type:'test-script';service:string;hardening:unknown};environment:{cpus:number;memory_mb:number;gpus:number;storage_mb:number;network_mode:string;os:string;build_timeout_sec:number}};
export type SelectedTask={taskId:SkbArtifactId;promptSha256:string;taskSourceSha256:string;environmentTreeSha256:string;verifierTreeSha256:string;originalResources:ResourceBlock};
export type SkbScheduleRow={index:number;benchmark:'skillsbench';officialId:SkbArtifactId;arm:'U'|'F';replica:0;id:string;route:string;taskSeconds:number;verifierSeconds:number;promptBodySha256:string;wholeTaskSourceSha256:string;cpus:number;memoryMb:number;declaredStorageMb:number;explicitVerifyChecks:number};
const ROOT=resolve(import.meta.dir,'../..'),SELECTION_HOME=join(ROOT,'docs/repair-2026-10-08/skillsbench-ten-artifact-readonly-preflight/selection-v1');
const semanticEqual=(a:unknown,b:unknown):boolean=>{
  const sorted=(v:any):any=>Array.isArray(v)?v.map(sorted):v!==null&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,sorted(v[k])])):v;
  return JSON.stringify(sorted(a))===JSON.stringify(sorted(b));
};

/** Whole task.md and exact untrimmed body have independent identities. */
export function rawFrontmatterBody(raw:Uint8Array){
  const text=new TextDecoder('utf-8',{fatal:true}).decode(raw),delimiter=/^---[ \t]*\r?\n/gm;
  const first=delimiter.exec(text),second=delimiter.exec(text);
  demand(first?.index===0&&second!==null,'skb_raw_frontmatter_delimiters');
  return text.slice(second!.index+second![0].length);
}
function verifyMetadataTree(tree:any,expectedRoot:string){
  demand(resolve(tree.root)===resolve(expectedRoot)&&tree.protocol==='ordered-ordinary-source-tree-v1'&&tree.fileCount===tree.files.length,'skb_source_tree_role');
  const files:string[]=[],dirs:string[]=[];
  const walk=(directory:string)=>{demand(lstatSync(directory).isDirectory()&&!lstatSync(directory).isSymbolicLink()&&realpathSync(directory).toLowerCase()===resolve(directory).toLowerCase(),'skb_source_tree_reparse');for(const name of readdirSync(directory)){const path=join(directory,name),relative=path.slice(resolve(expectedRoot).length+1).replaceAll('\\','/'),stat=lstatSync(path);demand(!stat.isSymbolicLink()&&realpathSync(path).toLowerCase()===resolve(path).toLowerCase(),'skb_source_entry_reparse');if(stat.isDirectory()){dirs.push(relative);walk(path);}else{demand(stat.isFile()&&stat.nlink===1,'skb_source_regular');files.push(relative);}}};
  walk(resolve(expectedRoot));demand(same(files.sort(),tree.files.map((p:any)=>p.path).sort())&&same(dirs.sort(),tree.directories.slice().sort()),'skb_source_tree_inventory');
  for(const p of tree.files){demand(typeof p.path==='string'&&p.path.split('/').every((x:string)=>x!==''&&x!=='.'&&x!=='..')&&!p.path.includes('\\'),'skb_source_relative_path');verifyPin({path:join(expectedRoot,p.path),bytes:p.bytes,sha256:p.sha256});}
}
export function loadSkbArtifactSelection(selectionPin=actualPin(join(SELECTION_HOME,'ten-task-list.json')),metadataPin=actualPin(join(SELECTION_HOME,'public-metadata.json'))){
  demand(resolve(selectionPin.path)===join(SELECTION_HOME,'ten-task-list.json')&&selectionPin.sha256===SKB_ARTIFACT_SELECTION_SHA&&selectionPin.bytes===6835,'skb_fixed_ten_selection');
  demand(resolve(metadataPin.path)===join(SELECTION_HOME,'public-metadata.json')&&metadataPin.sha256===SKB_ARTIFACT_METADATA_SHA&&metadataPin.bytes===126355,'skb_fixed_public_metadata');
  const selection=jsonPin(selectionPin),metadata=jsonPin(metadataPin);
  demand(selection.protocol==='skillsbench-ten-public-task-list-v1'&&selection.taskCount===10&&same(selection.methods,['U','F'])&&selection.sameOrderedListRequired===true&&same(selection.tasks.map((t:SelectedTask)=>t.taskId),SKB_ARTIFACT_IDS),'skb_ten_order_identity');
  demand(metadata.protocol==='skillsbench-ten-artifact-readonly-preflight-v1'&&metadata.sourceBeforeAfterEqual===true&&same(metadata.selectionManifestPin,selectionPin)&&metadata.tasks.length===10&&metadata.scope.taskCount===10&&metadata.scope.modelCalls===0&&metadata.scope.scoresIssued===0,'skb_public_metadata_scope');
  verifyPin(metadata.sourcePin);verifyPin(metadata.readerSourcePin);verifyPin(metadata.inventory87Pin);
  const tasks:SelectedTask[]=selection.tasks;
  for(const task of tasks){
    const row=metadata.tasks.find((r:any)=>r.taskId===task.taskId);demand(row,'skb_public_task_missing');verifyPin(row.taskSourcePin);
    demand(resolve(row.taskSourcePin.path)===join(ROOT,'.phase1-data/skillsbench/vendor/skillsbench/tasks',task.taskId,'task.md')&&row.taskSourcePin.sha256===task.taskSourceSha256&&semanticEqual(task.originalResources,row.originalResources),'skb_original_task_resource_identity');
    demand(row.environmentSource.treeSha256===task.environmentTreeSha256&&row.verifierSource.treeSha256===task.verifierTreeSha256,'skb_original_source_tree_identity');
    verifyMetadataTree(row.environmentSource,join(ROOT,'.phase1-data/skillsbench/vendor/skillsbench/tasks',task.taskId,'environment'));
    verifyMetadataTree(row.verifierSource,join(ROOT,'.phase1-data/skillsbench/vendor/skillsbench/tasks',task.taskId,'verifier'));
    const body=rawFrontmatterBody(readFileSync(row.taskSourcePin.path));demand(hash(body)===row.promptSha256&&hash(body)===task.promptSha256&&Buffer.byteLength(body)===row.promptBytes,'skb_exact_public_prompt_body');
    const r=task.originalResources;demand([600,900,1800].includes(r.agent.timeout_sec)&&[240,600,900,1800].includes(r.verifier.timeout_sec)&&[1,2,4].includes(r.environment.cpus)&&[2048,4096].includes(r.environment.memory_mb)&&r.environment.storage_mb===10240&&r.environment.gpus===0,'skb_per_task_original_resources');
    demand(row.outputArtifacts.length===1&&row.outputArtifacts[0].acceptedKind==='regular-only'&&row.readiness.paidReady===false,'skb_static_output_only_metadata_not_readiness');
  }
  return{tasks,selectionPin,metadataPin,metadata,sourceTaskCount:87 as const,selectedTaskCount:10 as const,unselectedTaskCount:77 as const};
}
export function fixedSkbArtifactSchedule(runId:string,tasks:SelectedTask[]):SkbScheduleRow[]{
  demand(/^repair-[0-9TZ-]+$/.test(runId)&&same(tasks.map(t=>t.taskId),SKB_ARTIFACT_IDS),'skb_prospective_schedule_identity');
  return tasks.flatMap((task,i)=>['U','F'].map((arm,j)=>{
    const id=runId+'/skillsbench/'+arm+'/0/'+task.taskId;
    return{index:i*2+j,benchmark:'skillsbench' as const,officialId:task.taskId,arm:arm as 'U'|'F',replica:0 as const,id,route:id,taskSeconds:task.originalResources.agent.timeout_sec,verifierSeconds:task.originalResources.verifier.timeout_sec,promptBodySha256:task.promptSha256,wholeTaskSourceSha256:task.taskSourceSha256,cpus:task.originalResources.environment.cpus,memoryMb:task.originalResources.environment.memory_mb,declaredStorageMb:task.originalResources.environment.storage_mb,explicitVerifyChecks:arm==='F'?SKB_ARTIFACT_CHECKS:0};
  }));
}
export function assertSkbArtifactSchedule(runId:string,rows:SkbScheduleRow[],tasks:SelectedTask[],scheduleSha256:string){
  const expected=fixedSkbArtifactSchedule(runId,tasks);demand(rows.length===20&&same(rows,expected)&&hash(JSON.stringify(rows))===scheduleSha256,'skb_frozen_twenty_task_runs');
}

/** Post-generation model/capture status stays separate from official reward. */
export function skbArtifactGeneration(input:{runtimeVerdict:unknown;state:string;calls:ApiReceipt[];trace:{role?:unknown;kind?:unknown;body?:unknown;at?:unknown}[];candidate?:string;deadline:number;receipts:{tool:string;forwarded:boolean;finishedAt?:number}[];capture?:{stoppedAt?:number}}):GenerationClassification{
  const value=classifyGeneration(input);if(!value.valid)return value;
  if(input.receipts.some(r=>r.forwarded&&['bash','write','edit'].includes(r.tool)&&Number(r.finishedAt)>input.deadline)||(input.capture?.stoppedAt&&input.capture.stoppedAt>input.deadline))return{...value,kind:'experimental_failure',outcome:'budget_exhausted',why:'an admitted mutation or final artifact freeze completed after the predeclared deadline'};
  return value;
}

export type CollectionVerdict={valid:true;ran:true;reward:number;completedTests:number;passedTests:number;failedTests:number;collectionComplete:true;collectionPin:Pin;taskDescriptorPin:Pin;artifactSha256:string|null;candidateExecutablesUsed:false;candidateSnapshotUsed:false;hostBinds:false;graderNetwork:'none'};
/** Native backend supplies the original collection and reward protocol, not JPG. */
export function artifactCollectionAcceptance(input:{generation:GenerationClassification;candidateSha256:string;capturePin:Pin;taskDescriptorPin:Pin;officialVerdict?:CollectionVerdict;rewardKind:'binary'|'fractional'}):Record<string,unknown>{
  const {generation:g}=input,base={candidateSha256:input.candidateSha256,capturePin:input.capturePin,taskDescriptorPin:input.taskDescriptorPin};
  if(!g.valid)return{...base,valid:false,passed:false,reward:null,outcome:g.outcome,why:g.why};
  if(g.kind==='experimental_failure')return{...base,valid:true,passed:false,reward:0,outcome:g.outcome,why:g.why};
  const v=input.officialVerdict;
  const complete=v?.valid===true&&v.ran===true&&v.collectionComplete===true&&Number.isSafeInteger(v.completedTests)&&v.completedTests>0&&Number.isSafeInteger(v.passedTests)&&Number.isSafeInteger(v.failedTests)&&v.passedTests>=0&&v.failedTests>=0&&v.completedTests===v.passedTests+v.failedTests&&Number.isFinite(v.reward)&&v.reward>=0&&v.reward<=1&&same(v.taskDescriptorPin,input.taskDescriptorPin)&&v.candidateExecutablesUsed===false&&v.candidateSnapshotUsed===false&&v.hostBinds===false&&v.graderNetwork==='none';
  if(!complete)return{...base,valid:false,passed:false,reward:null,outcome:'grader_error',why:'full actual private collection/source/artifact verdict is absent or inconsistent'};
  verifyPin(v!.collectionPin);verifyPin(input.taskDescriptorPin);verifyPin(input.capturePin);
  if(input.rewardKind==='binary'&&![0,1].includes(v!.reward))return{...base,valid:false,passed:false,reward:null,outcome:'grader_error',why:'a binary reward protocol returned a fractional value'};
  return{...base,valid:true,passed:v!.reward===1,reward:v!.reward,outcome:v!.reward===1?'passed':'rejected',why:v!.reward===1?'':'original complete artifact-only evaluator rejected all or part of the fixed output',officialVerdict:v};
}

/** ObjRun's G is bool; partial official reward is retained separately and in note. */
export function skbArtifactObjective(stand:string,taskId:SkbArtifactId){
  demand(SKB_ARTIFACT_IDS.includes(taskId),'skb_selected_G_task');const suffix='/'+encodeURIComponent(taskId);
  return{nodes:[{name:'verified',domain:'bool',moment:'done',handle:stand+suffix+'/verified'},{name:'passed',domain:'bool',moment:'done',handle:stand+suffix+'/passed'}],edges:[{src:'verified',out:0,dst:'passed'}],sink:'passed',checks:SKB_ARTIFACT_CHECKS,reuse:'never'};
}
