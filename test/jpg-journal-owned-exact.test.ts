import {expect,test} from 'bun:test';
import {execFileSync} from 'node:child_process';
import {randomBytes} from 'node:crypto';
import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {loadNativePython} from '../scripts/repair-2026-10-08/skb-jpg-native-python.ts';
import {jpgGeneration,artifactVerdict} from '../scripts/repair-2026-10-08/skb-jpg-contract.ts';
const ROOT=resolve(import.meta.dir,'..'),BASE=join(ROOT,'.scratch/jpg-owned-exact-controls'),AUDIT=join(ROOT,'scripts/repair-2026-10-08/audit-jpg-journal-campaign.py');
const program=String.raw`import importlib.util,importlib.machinery,json,sys,hashlib
from pathlib import Path
def module(path,name):
 loader=importlib.machinery.SourceFileLoader(name,path);spec=importlib.util.spec_from_loader(name,loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m);return m
m=module(sys.argv[1],'current_owned');root=Path(sys.argv[2]);scenario=sys.argv[3];root.mkdir(parents=True,exist_ok=True);store=root/'store';(store/'stand').mkdir(parents=True)
def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value)+'\n');return m.pin(path)
def owner(role,ids,pid,prefix):
 return {'schemaVersion':1,'taskId':m.TASK,'protocol':m.PROTOCOL,'processId':pid,'ownerLabelKey':'objrun.jpg-owner','ownerLabelValue':prefix,'lease':{'path':str(root/'never-created-lease'),'nonce':'d'*32,'released':True},'containers':[{'name':prefix+'-'+role+'-'+str(i+1)*8,'role':role,'expectedImageId':m.IMAGE,'state':'removed','containerId':cid} for i,cid in enumerate(ids)]}
cid=['a'*64,'b'*64];bp=save(store/'stand/operation-owner.json',owner('candidate',cid,131000,'objrun-jpg-'+'a'*12));candidates=[]
for arm,container in zip(['U','F'],cid):
 cold=save(root/('cold-candidate-'+arm+'.json'),{'ownedContainerID':container})
 capture=save(root/('capture-'+arm+'.json'),{'taskId':m.TASK,'protocol':m.PROTOCOL,'ownedContainerID':container,'containerStopped':True,'artifactPath':'/app/workspace/stat_ocr.xlsx','daemonEvidence':{'containerId':container}})
 removal=save(root/('candidate-removed-'+arm+'.json'),{'ok':True,'ownedContainersRemaining':0});candidates.append({'arm':arm,'coldPin':cold,'capturePin':capture,'removalPin':removal})
grades=[];count=0 if scenario in ['zero','missing-bridge','fake-candidate'] else 1
if count:
 folder=store/'final-grade-F';op=owner('grader',['c'*64],131004,'objrun-jpg-'+'c'*12)
 if scenario=='oracle-role':op['containers'][0]['role']='official-oracle';op['containers'][0]['name']=op['ownerLabelValue']+'-official-oracle-11111111'
 gp=save(folder/'operation-owner.json',op);rp=save(folder/'report.json',{'validated':True,'officialGradingValid':True,'protocol':m.PROTOCOL,'taskId':m.TASK,'graderSourceSha256':m.GRADER_SHA,'imageId':m.IMAGE,'candidateVerdict':{'valid':True,'ran':True,'completedTests':1,'imageId':m.IMAGE,'candidateSnapshotUsed':False,'candidateExecutablesUsed':False,'hostBinds':False,'graderNetwork':'none'}})
 cp=save(store/'cli-final-grade-F.json',{'processId':131004,'operationOutput':str(folder)});grades.append({'ownerPin':gp,'reportPin':rp,'cliPin':cp})
spec={'protocol':'jpg-journal-owned-scope-v1','family':m.FAMILY,'runId':'repair-2026-10-09T00-00-00-000Z','store':str(store),'bridgePid':131000,'enginePids':[131008,131012],'ports':[31001,31002,31003,31004,31005],'bridgeOwnerPin':bp,'candidateRecords':candidates,'graderRecords':grades,'containerIds':sorted(cid+(['c'*64] if count else []))}
if scenario=='missing-bridge':Path(bp['path']).unlink()
if scenario=='undeclared-grader':spec['graderRecords']=[]
if scenario=='extra-cid':spec['containerIds'].append('f'*64)
if scenario=='fake-candidate':changed=json.loads(Path(candidates[0]['capturePin']['path']).read_text());changed['ownedContainerID']='e'*64;candidates[0]['capturePin']=save(Path(candidates[0]['capturePin']['path']),changed)
save(root/'input-spec.json',spec)
legacy=None
if scenario in ['zero','one']:
 old=module(sys.argv[4],'old_owned');old.process_absent=lambda pid:True;old.port_closed=lambda port:True
 def forbidden(*args,**kwargs):raise RuntimeError('fixture must not query Docker')
 old.subprocess.run=forbidden
 try:old.owned_probe(spec,root/'never-published-legacy-close.json');legacy='incorrectly_accepted'
 except Exception as e:legacy=str(e)
try:
 graph=m.owned_graph(spec);result={'accepted':True,'candidateCount':len(graph['candidateIds']),'graderCount':len(graph['graderIds']),'containerCount':len(graph['containerIds']),'legacyError':legacy}
except Exception as e:result={'accepted':False,'error':str(e),'legacyError':legacy}
result.update(nativePureFixture=True,actualDockerOperations=0,actualPidOrPortProbes=0,modelCalls=0,productionLockAcquired=False,sourcePin=m.pin(Path(sys.argv[1])))
save(root/'result.json',result);print(json.dumps(result))
`;
function exercise(scenario:string){const path=join(BASE,randomBytes(8).toString('hex')),script=join(path,'fixture.py');mkdirSync(path,{recursive:true});writeFileSync(script,program);const old=join(ROOT,'docs/repair-2026-10-08/jpg-journal-owned-revision/pre-exact-owned-v1/scripts/repair-2026-10-08/audit-jpg-journal-campaign.py');return JSON.parse(execFileSync(loadNativePython().executable,['-B','-X','utf8',script,AUDIT,join(path,'evidence'),scenario,old],{windowsHide:true,encoding:'utf8',timeout:15000}));}
test('budget and no-candidate failures can close exact two cold IDs with zero graders; frozen >=4 control is red',()=>{
  for(const outcome of ['task_timeout','no_candidate']){const generation=jpgGeneration({runtimeVerdict:{valid:outcome==='no_candidate',outcome},state:'failed',calls:[{httpStatus:200,usage:{prompt_tokens:1,completion_tokens:1},finishedAt:new Date().toISOString(),completionValid:true}],trace:[],deadline:Date.now(),receipts:[]}),acceptance=artifactVerdict(undefined,{},'a'.repeat(64),generation);expect(generation.valid).toBe(true);expect(acceptance.valid).toBe(true);expect(acceptance.passed).toBe(false);}
  const r=exercise('zero');expect(r.accepted).toBe(true);expect(r.containerCount).toBe(2);expect(r.graderCount).toBe(0);expect(r.legacyError).toBe('owned_container_identity');
});
test('one actual private grader yields exactly three IDs and the old count gate is red',()=>{const r=exercise('one');expect(r.accepted).toBe(true);expect(r.containerCount).toBe(3);expect(r.graderCount).toBe(1);expect(r.legacyError).toBe('owned_container_identity');});
test('missing bridge owner cannot certify a cold CID',()=>expect(exercise('missing-bridge').accepted).toBe(false));
test('undeclared actual grader receipt cannot disappear from the owned set',()=>expect(exercise('undeclared-grader').error).toBe('owned_grader_receipt_inventory'));
test('oracle control role is rejected in a candidate grader receipt',()=>expect(exercise('oracle-role').error).toBe('owned_container_receipt_invalid'));
test('a guessed extra daemon ID cannot replace exact receipt evidence',()=>expect(exercise('extra-cid').error).toBe('owned_exact_container_set'));
test('a forged capture CID cannot bind two real cold receipts',()=>expect(exercise('fake-candidate').error).toBe('owned_candidate_capture_removed'));
