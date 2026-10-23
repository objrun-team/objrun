"""JPG-only source, native artifact grading and independent closing audit.

This file never generates a model answer. --freeze writes only the explicitly new
store; --grade imports only the frozen host helper and the captured workbook.
Scientific auditors/certification protocols are intentionally not accepted.
"""
from __future__ import annotations
import argparse
import ctypes
import gzip
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import socket
import sqlite3
import stat
import subprocess
import sys
import time
import zipfile
import uuid

ROOT=Path(__file__).resolve().parents[2]
FAMILY='jpg-journal-v1'
TASK='jpg-ocr-stat'
PROTOCOL='skb-jpg-output-v1-preseed'
IMAGE='sha256:92892771245d31d0b1af4a0c603effbdaf02bf62c1c055081f44a462f5261ced'
GRADER_SHA='fd3a65ed2ee692daa2797a8f014ce2722dff1b66aa1db6d88870e04caa7776da'

def require(ok,message):
    if not ok:raise RuntimeError(message)

def sha(raw):return hashlib.sha256(raw).hexdigest()

def file_sha(path):
    before=path.stat();h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(65536):h.update(block)
    after=path.stat();require((before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'file_changed_during_hash')
    return h.hexdigest()

def pin(path):return {'path':str(path.absolute()),'bytes':path.stat().st_size,'sha256':file_sha(path)}

def verify(p):
    path=Path(p['path']);require(path.is_file() and not path.is_symlink(),'pin_not_regular')
    require(('bytes' not in p or path.stat().st_size==p['bytes']) and file_sha(path)==p['sha256'],'pin_changed')
    return path

def pairs(items):
    value={}
    for k,v in items:
        require(k not in value,'duplicate_json_key');value[k]=v
    return value

def read(path):return json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=pairs,parse_constant=lambda v:(_ for _ in ()).throw(RuntimeError('nonfinite_json')))

def readpin(p):return read(verify(p))

def save(path,value):
    raw=(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode();path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    require(path.read_bytes()==raw,'durable_json_readback');return pin(path)

_OWNED_FLUSH_OUTPUTS=set()

def ordinary_owned_path(path,root):
    root=root.absolute();path=path.absolute();require(root in _OWNED_FLUSH_OUTPUTS and path.is_relative_to(root),'flush_not_self_owned')
    current=path
    while True:
        s=current.lstat();require(not current.is_symlink() and not (getattr(s,'st_file_attributes',0)&0x400) and current.resolve()==current,'flush_reparse')
        if current==root:break
        current=current.parent;require(current.is_relative_to(root),'flush_root_escape')
    return path

def create_owned_flush_fixture():
    # No caller-selected existing, original experiment or source directory can be registered.
    root=ROOT/'.scratch/jpg-fsync-owned-controls'/uuid.uuid4().hex
    root.mkdir(parents=True,exist_ok=False);_OWNED_FLUSH_OUTPUTS.add(root.absolute());return root

def flush_tree(path):
    path=ordinary_owned_path(path,path)
    count=0
    for base,dirs,files in os.walk(path,followlinks=False):
        for name in dirs:ordinary_owned_path(Path(base)/name,path)
        for name in files:
            p=ordinary_owned_path(Path(base)/name,path);before=p.lstat();require(stat.S_ISREG(before.st_mode),'flush_not_regular')
            if name=='config.yaml':continue
            digest=file_sha(p)
            with p.open('r+b') as f:
                ordinary_owned_path(p,path);opened=os.fstat(f.fileno());require((opened.st_ino,opened.st_dev,opened.st_size)==(before.st_ino,before.st_dev,before.st_size),'flush_open_identity');os.fsync(f.fileno())
            after=p.lstat();require(before.st_size==after.st_size and digest==file_sha(p),'flush_content_changed');count+=1
    return count

def freeze(recipe,output,store):
    require(recipe['family']==FAMILY and recipe['protocol']=='jpg-journal-recipe-v1','freeze_family')
    require(not (store/'frozen-source.zip').exists(),'freeze_archive_exists');store.mkdir(parents=True,exist_ok=False) if not store.exists() else None
    selected=[];refs=[];before=[];base=recipe['publicDependencyArchive'];base_path=verify(base)
    with zipfile.ZipFile(base_path) as z:
        def referenced(name,path):
            p=pin(path);before.append(p);raw=z.read(name)
            require(len(raw)==p['bytes'] and sha(raw)==p['sha256'],'public_dependency_reference_changed')
            refs.append({'name':name,'sourcePath':str(path),'sha256':p['sha256'],'bytes':p['bytes']})
        for p in recipe['sourcePins']:
            path=verify(p);name=path.relative_to(ROOT).as_posix();before.append(p);selected.append((name,path,p))
        for row in recipe['artifacts']:
            name=row['name'];require(not any(x in name.lower() for x in ['secret','token','.env','.pem','.key','broker']),'private_archive_asset')
            path=verify(row['pin']);archive_name='artifacts/'+name
            if name.startswith(('runtime/','grader-dependencies/')):referenced(archive_name,path)
            else:before.append(row['pin']);selected.append((archive_name,path,row['pin']))
        for p in sorted((ROOT/'app/node_modules').rglob('*')):
            if p.is_file() and p.suffix in ['.js','.cjs','.mjs','.json','.wasm','.node','.ts'] and '.bin' not in p.parts:referenced(p.relative_to(ROOT).as_posix(),p)
    require(sum(p['bytes'] for _,_,p in selected)<=16*1024**2 and len({n for n,_,_ in selected})==len(selected),'direct_archive_limit_or_duplicate')
    archive=store/'frozen-source.zip'
    with archive.open('xb') as target:
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for name,path,p in selected:
                raw=path.read_bytes();require(sha(raw)==p['sha256'],'source_changed_during_freeze');z.writestr(name,raw)
        target.flush();os.fsync(target.fileno())
    for p in before:verify(p)
    verify(base)
    value={'protocol':'jpg-journal-source-freeze-v1','family':FAMILY,'runId':recipe['runId'],'archivePin':pin(archive),'directMembers':[{'name':n,'sourcePath':str(path),'sha256':p['sha256'],'bytes':p['bytes']} for n,path,p in selected],
           'dependencyReferences':{**base,'members':refs},'doubleSourceHashVerified':True,'archiveFsyncReturned':True,'modelCalls':0,'scope':'Host-only inputs/source; only the public task prompt reaches the solver. No private environment/configuration archived.'}
    save(output/'frozen-source.json',value);return value

def check_freeze(p):
    frozen=readpin(p);require(frozen['protocol']=='jpg-journal-source-freeze-v1' and frozen['family']==FAMILY and frozen['doubleSourceHashVerified'] and frozen['archiveFsyncReturned'],'freeze_profile')
    direct=frozen['directMembers'];refs=frozen['dependencyReferences'];require(len({r['name'] for r in direct})==len(direct),'archive_duplicate_member')
    with zipfile.ZipFile(verify(frozen['archivePin'])) as z:
        require(set(z.namelist())=={r['name'] for r in direct},'archive_extra_or_missing_member')
        for row in direct:
            raw=z.read(row['name']);require(sha(raw)==row['sha256'] and len(raw)==row['bytes'],'direct_archive_sha');verify({'path':row['sourcePath'],**{k:row[k] for k in ['bytes','sha256']}})
    with zipfile.ZipFile(verify(refs)) as z:
        require(len({r['name'] for r in refs['members']})==len(refs['members']),'reference_duplicate')
        for row in refs['members']:
            raw=z.read(row['name']);require(sha(raw)==row['sha256'] and len(raw)==row['bytes'],'reference_archive_sha');verify({'path':row['sourcePath'],**{k:row[k] for k in ['bytes','sha256']}})
    return frozen

def process_absent(pid):
    require(type(pid) is int and pid>0 and pid!=os.getpid(),'owned_pid_invalid')
    if os.name!='nt':
        try:os.kill(pid,0);return False
        except ProcessLookupError:return True
    k=ctypes.WinDLL('kernel32',use_last_error=True);k.OpenProcess.argtypes=[ctypes.c_uint,ctypes.c_bool,ctypes.c_uint];k.OpenProcess.restype=ctypes.c_void_p
    handle=k.OpenProcess(0x1000,False,pid)
    if not handle:
        require(ctypes.get_last_error()==87,'owned_pid_query_unknown');return True
    try:
        code=ctypes.c_ulong();require(k.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(code)),'owned_pid_exit_query');return code.value!=259
    finally:k.CloseHandle(ctypes.c_void_p(handle))

def port_closed(port):
    require(type(port) is int and 0<port<65536,'owned_port_invalid')
    with socket.socket() as s:
        s.settimeout(1)
        try:s.connect(('127.0.0.1',port));return False
        except ConnectionRefusedError:return True
        except OSError as error:
            require(getattr(error,'winerror',None)==10061 or error.errno==111,'owned_port_query_unknown');return True

def owned_graph(spec):
    """Reconstruct actual owned IDs. Legitimate failures need no private grader."""
    require(spec['family']==FAMILY and spec['protocol'] in ['jpg-journal-owned-scope-v1','jpg-journal-owned-close-v1'],'owned_scope_family')
    store=Path(spec['store']).absolute();require(store.resolve()==store,'owned_store_physical')
    bridge_pin=spec['bridgeOwnerPin'];require(Path(bridge_pin['path']).absolute()==store/'stand/operation-owner.json','owned_bridge_receipt_path')
    bridge=readpin(bridge_pin)
    def owner(record,role):
        prefix=record.get('ownerLabelValue','');require(record.get('schemaVersion')==1 and record.get('taskId')==TASK and record.get('protocol')==PROTOCOL and record.get('ownerLabelKey')=='objrun.jpg-owner' and re.fullmatch('objrun-jpg-[a-f0-9]{12}',prefix) and type(record.get('processId')) is int and record['processId']>0,'owned_receipt_identity')
        require(record.get('lease',{}).get('released') is True and re.fullmatch('[a-f0-9]{32}',record['lease'].get('nonce','')),'owned_receipt_lease_unclosed')
        ids=[]
        for row in record.get('containers',[]):
            require(row.get('role')==role and row.get('expectedImageId')==IMAGE and row.get('state')=='removed' and re.fullmatch(re.escape(prefix)+'-'+role+'-[a-f0-9]{8}',row.get('name','')) and re.fullmatch('[a-f0-9]{64}',row.get('containerId','')),'owned_container_receipt_invalid')
            ids.append(row['containerId'])
        require(len(ids)==len(set(ids)),'owned_duplicate_receipt_id');return ids
    candidate_ids=owner(bridge,'candidate');require(bridge['processId']==spec['bridgePid'] and len(candidate_ids)==2,'owned_bridge_candidates')
    candidates=spec['candidateRecords'];require(len(candidates)==2 and {r['arm'] for r in candidates}=={'U','F'},'owned_two_cold_candidates')
    bound_candidates=[];inputs=[bridge_pin]
    for r in candidates:
        arm=r['arm'];cold=readpin(r['coldPin']);capture=readpin(r['capturePin']);removed=readpin(r['removalPin']);inputs.extend([r['coldPin'],r['capturePin'],r['removalPin']])
        require(Path(r['coldPin']['path']).name=='cold-candidate-'+arm+'.json' and Path(r['removalPin']['path']).name=='candidate-removed-'+arm+'.json','owned_candidate_receipt_roles')
        cid=cold.get('ownedContainerID');require(cid==capture.get('ownedContainerID') and capture.get('taskId')==TASK and capture.get('protocol')==PROTOCOL and capture.get('containerStopped') is True and capture.get('artifactPath')=='/app/workspace/stat_ocr.xlsx' and capture.get('daemonEvidence',{}).get('containerId')==cid and removed.get('ok') is True and removed.get('ownedContainersRemaining')==0,'owned_candidate_capture_removed')
        bound_candidates.append(cid)
    require(len(set(bound_candidates))==2 and set(bound_candidates)==set(candidate_ids),'owned_cold_candidate_set')
    records=spec['graderRecords'];declared=set();grader_ids=[]
    for r in records:
        op=Path(r['ownerPin']['path']).absolute();require(op.name=='operation-owner.json' and op.is_relative_to(store),'owned_grader_receipt_scope');relative=op.parent.relative_to(store).as_posix()
        require(re.fullmatch('stand/grade-[a-f0-9]{8}|final-grade-[UF]',relative),'owned_grader_role_directory');require(str(op) not in declared,'owned_duplicate_grader_receipt');declared.add(str(op))
        require(Path(r['reportPin']['path']).absolute()==op.parent/'report.json' and Path(r['cliPin']['path']).absolute()==op.parent.parent/('cli-'+op.parent.name+'.json'),'owned_grader_input_paths')
        record=readpin(r['ownerPin']);ids=owner(record,'grader');require(len(ids)==1,'owned_one_created_grader_per_cli')
        report=readpin(r['reportPin']);cli=readpin(r['cliPin']);v=report.get('candidateVerdict',{})
        require(report.get('validated') is True and report.get('officialGradingValid') is True and report.get('protocol')==PROTOCOL and report.get('taskId')==TASK and report.get('graderSourceSha256')==GRADER_SHA and report.get('imageId')==IMAGE and v.get('valid') is True and v.get('ran') is True and v.get('completedTests')==1 and v.get('imageId')==IMAGE and v.get('candidateSnapshotUsed') is False and v.get('candidateExecutablesUsed') is False and v.get('hostBinds') is False and v.get('graderNetwork')=='none','owned_private_grader_report')
        require(cli.get('processId')==record['processId'] and Path(cli.get('operationOutput','')).absolute()==op.parent,'owned_cli_pid_receipt')
        grader_ids.extend(ids);inputs.extend([r['ownerPin'],r['reportPin'],r['cliPin']])
    actual={str(p.absolute()) for p in (store/'stand').glob('grade-*/operation-owner.json')}
    actual.update(str(p.absolute()) for p in store.glob('final-grade-*/operation-owner.json'))
    require(actual==declared,'owned_grader_receipt_inventory')
    # A grade directory with a missing owner cannot disappear from the inventory.
    for p in list((store/'stand').glob('grade-*'))+list(store.glob('final-grade-*')):
        if p.is_dir():require(str((p/'operation-owner.json').absolute()) in declared,'owned_grade_directory_missing_receipt')
    expected=sorted(bound_candidates+grader_ids);require(len(set(expected))==len(expected),'owned_cross_role_duplicate_id')
    require(spec['containerIds']==expected,'owned_exact_container_set');return {'candidateIds':sorted(bound_candidates),'graderIds':sorted(grader_ids),'containerIds':expected,'inputPins':inputs}

def owned_probe(spec,output):
    require(spec['family']==FAMILY and spec['protocol']=='jpg-journal-owned-scope-v1','owned_scope_family')
    graph=owned_graph(spec)
    pids=spec['enginePids']+[spec['bridgePid']];require(len(pids)==3 and len(set(pids))==3,'owned_three_processes')
    processes=[{'pid':p,'present':not process_absent(p)} for p in pids];ports=[{'port':p,'closed':port_closed(p)} for p in spec['ports']]
    require(len(ports)==5 and len(set(spec['ports']))==5,'owned_five_listeners')
    ids=graph['containerIds']
    containers=[]
    for cid in ids:
        r=subprocess.run(['docker','inspect',cid],stdin=subprocess.DEVNULL,capture_output=True,timeout=10)
        absent=r.returncode!=0 and re.fullmatch(r'\s*error: no such object: '+re.escape(cid)+r'\s*',r.stderr.decode('utf-8','replace').casefold()) is not None
        require(r.returncode==0 or absent,'owned_daemon_unknown')
        containers.append({'id':cid,'present':not absent,'stderrSha256':sha(r.stderr),'status':r.returncode})
    value={**spec,'protocol':'jpg-journal-owned-close-v1','actualOwnedGraph':graph,'processes':processes,'ports':ports,'containers':containers,'closed':all(not p['present'] for p in processes) and all(p['closed'] for p in ports) and all(not c['present'] for c in containers),'observedAtUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'nativeAuditorSourcePin':pin(Path(__file__))}
    require(value['closed'],'owned_resource_still_present');save(output,value);return value

def private_grade(recipe,capture,output):
    store=Path(recipe['store']).absolute();output=output.absolute();require(recipe['family']==FAMILY and store.name==recipe['runId'] and store.resolve()==store and output.parent==store and re.fullmatch('final-grade-[UF]',output.name) and not output.exists(),'private_grade_new_owned_output')
    require(store.is_relative_to(ROOT) or store.is_relative_to(Path('C:/Users/y1252/.codex/visualizations/2026/10/08/01a119ed-fdf7-7c32-b323-de9bab1290b6')),'private_grade_owned_store_scope')
    _OWNED_FLUSH_OUTPUTS.add(output)
    receipt=readpin(capture);require(receipt['taskId']==TASK and receipt['protocol']==PROTOCOL and receipt['containerStopped'] is True and receipt['artifactPath']=='/app/workspace/stat_ocr.xlsx','final_capture_profile')
    grader=ROOT/'scripts/repair-2026-10-08/software-jpg-private-grader.py';require(file_sha(grader)==GRADER_SHA,'grader_source_changed')
    spec=importlib.util.spec_from_file_location('frozen_jpg_host',ROOT/'scripts/repair-2026-10-08/skb-jpg-host-ops.py');host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
    native=readpin(recipe['approvedNativeProfile']);exe=Path(native['executable']);require(file_sha(exe)==native['sha256'],'native_grade_interpreter_changed')
    argv=[str(exe),'-B','-X','utf8',str(grader),'--grade','--capture-receipt',str(verify(capture)),'--image-manifest',str(verify(recipe['gates']['image'])),'--build-proof',str(verify(recipe['gates']['build'])),'--dependency-profile',str(verify(recipe['gates']['profile'])),'--output',str(output)]
    if receipt['state']=='regular':
        artifact=Path(receipt['hostArtifactPath']);require(artifact.is_file() and not artifact.is_symlink() and artifact.stat().st_size<=8*1024**2 and file_sha(artifact)==receipt['artifactSha256'],'fixed_artifact_changed');argv+=['--candidate-output',str(artifact),'--candidate-sha256',receipt['artifactSha256']]
    elif receipt['state']=='absent':argv+=['--captured-absent']
    else:require(receipt['state'] in ['directory','symlink','too_large'],'capture_state');argv+=['--captured-format-failure',receipt['state']]
    result=host.run_private_grader(argv,output,IMAGE,650);require(result.returncode==0,'private_cli_failed');report=read(output/'report.json')
    require(report.get('validated') is True and report['candidateVerdict'].get('valid') is True,'private_grade_invalid');flush_tree(output);return report

def number(v):return type(v) in [int,float] and math.isfinite(v) and v>=0

def raw_json(p,expected,compressed,max_bytes):
    path=Path(p);require(path.is_file() and not path.is_symlink() and path.stat().st_size<=65*1024**2 and file_sha(path)==compressed,'wire_compressed_sha')
    with gzip.open(path,'rb') as f:raw=f.read(max_bytes+1)
    require(len(raw)<=max_bytes and sha(raw)==expected,'wire_raw_sha');return raw,json.loads(raw.decode('utf-8'),object_pairs_hook=pairs)

def journal_audit(config_pin,journal_pin,ledger_pin,bun):
    config=readpin(config_pin);require(config['protocol']=='campaign-api-journal-v1' and config['pendingLimit']==4 and config['model']=='deepseek-flash','journal_config_scope')
    checker=ROOT/'scripts/repair-2026-10-08/audit-journal-canonical.ts';r=subprocess.run([bun,str(checker),str(verify(journal_pin))],cwd=ROOT,stdin=subprocess.DEVNULL,capture_output=True,timeout=90)
    require(r.returncode==0,'actual_ecmascript_canonical_failed');canonical=json.loads(r.stdout);require(canonical['valid'] is True and canonical['fileSha256']==journal_pin['sha256'],'canonical_pin')
    at=0;last=config_pin['sha256'];starts={};finishes={};refs={};event_seq=0
    with verify(journal_pin).open('rb') as f:
        for line in f:
            require(line.endswith(b'\n') and len(line)<=65536,'journal_incomplete_line');frame=json.loads(line,object_pairs_hook=pairs)
            require(frame['protocol']=='campaign-api-journal-v1' and frame['eventSeq']==event_seq and frame['previousEventSha256']==last and type(frame['requestSeq']) is int,'journal_chain')
            n=frame['requestSeq'];rec=frame['record']
            if frame['kind']=='start':require(n not in starts,'duplicate_start');starts[n]=rec
            else:require(frame['kind']=='finish' and n in starts and n not in finishes,'duplicate_or_unknown_finish');finishes[n]=rec;refs[n]={'callId':n,'finishOffset':at,'finishEnd':at+len(line),'finishLineSha256':sha(line)}
            at+=len(line);last=sha(line);event_seq+=1
    require(set(starts)==set(finishes) and sorted(starts)==list(range(len(starts))) and canonical['bytes']==at and canonical['eventCount']==event_seq,'journal_not_closed')
    spent=0
    for n,start in starts.items():
        rec=finishes[n];raw,request=raw_json(start['requestFile'],start['requestSha256'],start['requestCompressedSha256'],4*1024**2)
        require(request['model']=='deepseek-flash' and request['temperature']==0 and request['seed']==42 and request['reasoning_effort']=='none' and request.get('max_tokens',request.get('max_completion_tokens'))==8192 and not request.get('stream'),'wire_protocol')
        reservation=((len(raw)+2048+len(request['messages'])*256)*.3+8192*1.2)/1e6;require(abs(start['reservationUsd']-reservation)<1e-9,'reservation_actual_wire')
        for key in ['route','startedAt','requestSha256','requestedModel','requestFile','wireParameters','requestCompressedSha256','requestBytes']:require(start[key]==rec[key],'finish_start_disagrees')
        require(rec.get('providerAttempted') is True and rec.get('httpStatus')==200 and rec.get('completionValid') is True and not rec.get('fault'),'invalid_completion_receipt')
        _,response=raw_json(rec['responseFile'],rec['responseSha256'],rec['responseCompressedSha256'],64*1024**2);u=response['usage'];require(u==rec['usage'] and response['model']==rec['servedModel'] and response['choices'][0]['message']['role']=='assistant','raw_usage_or_completion')
        prompt=u['prompt_tokens'];out=u['completion_tokens'];hit=u.get('prompt_cache_hit_tokens',0)
        require(all(type(v) is int and v>=0 for v in [prompt,out,hit]) and hit<=prompt and u.get('prompt_cache_miss_tokens',prompt-hit)==prompt-hit,'usage_counts')
        cost=((prompt-hit)*.3+hit*.006+out*1.2)/1e6
        require(rec['costBasis']=='reported_usage' and abs(rec['usdUpperBound']-cost)<1e-9 and abs(rec['accountedUpperBoundUsd']-cost)<1e-9,'raw_cost_reconciliation');spent+=cost
    ledger=readpin(ledger_pin);require(ledger['campaign']==config['campaign'] and ledger['capUsd']==config['capUsd'] and ledger['priorCampaignCostUpperBoundUsd']==config['priorCampaignCostUpperBoundUsd'] and ledger['reservedUpperBoundUsd']==0 and all(v==0 for v in ledger['pending'].values()) and ledger['calls']==[finishes[n] for n in sorted(finishes)] and abs(ledger['recordedUsageUpperBoundUsd']-spent)<1e-9,'legacy_export_mismatch')
    return {'prefix':{'bytes':at,'eventCount':event_seq,'lastSha256':last},'calls':finishes,'refs':refs,'spent':spent}

def database_task(task):
    pins=task['databasePins'];require(len(pins) in [1,2] and Path(pins[0]['path']).name=='h2h.sqlite','task_sqlite_identity')
    for p in pins:verify(p)
    path=Path(pins[0]['path']);db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    try:
        row=dict(db.execute('select * from task where id=?',(task['taskId'],)).fetchone());require(row['solve_seconds']==1800 and row['created_at']==task['actualCreatedAt'] and row['state']==task['state'] and row['created_at']+1800000==task['deadlineUnixMs'],'actual_task_runtime_or_deadline')
        if 'promptSha256' in task:require(sha(row['description'].encode())==task['promptSha256'],'actual_public_task_description')
        actual_result=json.loads(row['result']) if row['result'] else {'valid':True,'outcome':'unaided_generated'};require(actual_result==task['runtimeVerdict'],'runtime_verdict_changed')
        trace=[dict(r) for r in db.execute('select * from agent_bot_msg where instance like ? order by unit,seq',(task['taskId']+'#%',))];units=[dict(r) for r in db.execute('select * from agent_bot_ctx where instance like ? order by unit',(task['taskId']+'#%',))]
        require(trace==task['trace'] and units==task['units'] and all(r['done']==1 for r in units),'actual_trace_truncated_or_unfinished')
        mode=row['mode'];require(re.fullmatch('[A-Za-z0-9_]+',mode),'task_mode_identifier')
        attempts=db.execute('select agent,instance,unit from "task_'+mode+'" where task=? order by unit desc',(task['taskId'],)).fetchall();candidate=None;how='none'
        for unit in attempts:
            require(re.fullmatch('[A-Za-z0-9_]+',unit['agent']),'agent_identifier')
            calls=db.execute('select body from "agent_'+unit['agent']+'_msg" where instance=? and unit=? and kind=\'call\' and at<=? order by seq desc',(unit['instance'],unit['unit'],task['deadlineUnixMs'])).fetchall()
            for call in calls:
                try:
                    for c in reversed(json.loads(call['body']).get('calls',[])):
                        if c.get('name')=='submit':candidate=c.get('input',{}).get('answer','');candidate=candidate if isinstance(candidate,str) else '';how='submitted';break
                except (ValueError,AttributeError,TypeError):pass
                if candidate is not None:break
            if candidate is not None:break
        if candidate is None and not db.execute('select 1 from cycle where mode=? and cycle=\'submit\' limit 1',(mode,)).fetchone():
            for unit in attempts:
                for message in db.execute('select body from "agent_'+unit['agent']+'_msg" where instance=? and unit=? and kind=\'prompt\' and at<=? order by seq desc',(unit['instance'],unit['unit'],task['deadlineUnixMs'])):
                    if str(message['body'] or '').strip():candidate=str(message['body']);how='last words';break
                if candidate is not None:break
        require((candidate or '')==task['candidate'] and how==task['candidateHow'] and sha((candidate or '').encode())==task['candidateSha256'],'actual_final_candidate_changed')
        explicit=0
        for r in trace:
            try:explicit+=int(r['kind']=='tool' and json.loads(r['body']).get('name')=='verify')
            except (ValueError,AttributeError,TypeError):pass
        require(explicit==task['explicitVerifyCalls'] and (task['arm']=='F' or explicit==0),'explicit_verify_scope')
        return candidate
    finally:
        db.close()
        for p in pins:verify(p)

def tool_receipts(task,store,ledger):
    receipts=task['toolQuiescence']['receipts'];indices=[r['index'] for r in receipts];require(len(indices)==len(set(indices)),'duplicate_tool_receipt')
    for r in receipts:
        require(r in ledger['receipts'] and r['place']=='skb:'+task['taskId'] and r['tool'] in ['ping','bash','read','write','edit','glob','grep'] and r['finishedAt']>=r['admittedAt'],'tool_ledger_scope')
        if not r['forwarded']:require(r.get('denial') and not r.get('responseSha256'),'unproved_tool_denial');continue
        require(not r.get('fault') and type(r.get('httpStatus')) is int,'tool_forward_incomplete')
        for side,field in [('request','requestSha256'),('response','responseSha256')]:
            path=store/'tool-receipts'/('tool-'+str(r['index'])+'-'+side+'.json.gz')
            with gzip.open(path,'rb') as f:raw=f.read(64*1024**2+1)
            require(len(raw)<=64*1024**2 and sha(raw)==r[field],'actual_tool_raw_sha')
            if side=='request':body=json.loads(raw,object_pairs_hook=pairs);require(body['place']==r['place'] and (body.get('tool')==r['tool'] or body.get('op')=='ping' and r['tool']=='ping'),'actual_tool_request_scope')

def audit(output,bun):
    errors=[];inputs=[]
    def load(name):
        p=pin(output/name);inputs.append(p);return readpin(p)
    try:
        summary=load('summary.json');run=summary['runId'];require(summary['protocol']=='jpg-journal-operational-summary-v1' and summary['family']==FAMILY and summary['operationalComplete'] is True and summary['formalScoreCertified'] is False and not summary.get('fatal'),'jpg_summary_scope')
        manifest=load('manifest.json');require(manifest['family']==FAMILY and manifest['campaign']==run and manifest['sourceTaskCount']==87 and manifest['supportedTaskIds']==[TASK] and manifest['unsupportedTaskCount']==86 and manifest['taskSeconds']==1800 and manifest['verifierSeconds']==600 and manifest['arms']==['U','F'] and manifest['concurrency']==1 and manifest['reuse']=='never','jpg_manifest_denominator')
        recipe=load('recipe.json');require(recipe['runId']==run and recipe['family']==FAMILY and recipe['mode']==summary['providerKind'],'recipe_run');store=Path(recipe['store'])
        catalog=readpin(next(r['pin'] for r in recipe['artifacts'] if r['name']=='official/task-catalog.json'));require(catalog['protocol']=='jpg-source-catalog-v1' and catalog['sourceTaskCount']==87 and catalog['supportedTaskIds']==[TASK] and catalog['unsupportedTaskCount']==86 and len(catalog['catalog'])==87 and len({r['id'] for r in catalog['catalog']})==87,'actual_source_catalog')
        source=load('source-close.json');require(source['protocol']=='jpg-journal-source-close-v1' and source['family']==FAMILY and source['runId']==run and source['pins']==recipe['sourcePins'],'source_graph')
        require(source['hostRuntime']==recipe['hostRuntime']==manifest['hostRuntime'] and Path(bun).resolve()==Path(recipe['hostRuntime']['bun']['path']).resolve(),'host_runtime_graph');verify(recipe['hostRuntime']['bun']);verify(recipe['hostRuntime']['python'])
        for p in source['pins']:verify(p)
        require(any(p['sha256']==file_sha(Path(__file__)) and Path(p['path']).resolve()==Path(__file__).resolve() for p in source['pins']),'auditor_executed_source_missing')
        freeze_pin=pin(output/'frozen-source.json');inputs.append(freeze_pin);check_freeze(freeze_pin)
        raw=load('raw-close.json');cash=readpin(summary['cashPin']);inputs.append(summary['cashPin']);require(cash['protocol']=='cny-shadow-close-v2' and cash['runId']==run and cash['releasePermitted'] is True and cash['snapshot']['pendingCount']==0 and cash['snapshot']['newUnknownCount']==0 and cash['snapshot']['poisoned'] is False,'cash_unclosed')
        tool_ledger=readpin(raw['toolLedgerPin']);inputs.append(raw['toolLedgerPin']);require(tool_ledger['family']==FAMILY and tool_ledger['runId']==run and raw['failureReceipts']==[],'tool_or_provider_anomaly')
        config_pin=cash['journalConfigPin'];inputs.append(config_pin);journal_pin=raw['journalFilePin'];inputs.append(journal_pin);ledger_pin=pin(output/'api-ledger.json');inputs.append(ledger_pin)
        facts=journal_audit(config_pin,journal_pin,ledger_pin,bun);require(raw['protocol']=='jpg-journal-raw-close-v1' and raw['family']==FAMILY and raw['runId']==run and raw['journalPrefix']==cash['journalPrefix']==facts['prefix'],'raw_cash_prefix')
        owned=load('owned-close.json');require(owned['family']==FAMILY and owned['runId']==run and owned['closed'] is True and len(owned['enginePids'])==2 and all(not p['present'] for p in owned['processes']) and all(p['closed'] for p in owned['ports']) and all(not p['present'] for p in owned['containers']),'owned_unclosed')
        graph=owned_graph(owned);require(graph==owned['actualOwnedGraph'],'owned_graph_changed');inputs.extend(graph['inputPins'])
        require(all(process_absent(p['pid']) for p in owned['processes']) and all(port_closed(p['port']) for p in owned['ports']),'owned_process_or_listener_reappeared')
        grading=load('grading-close.json');require(grading['family']==FAMILY and grading['runId']==run and grading['generationClosedBeforeAllFinalGrading'] is True and len(grading['finalGrades'])==2,'grading_scope')
        secrets=load('evidence-secret-audit.json');require(secrets['passed'] is True and secrets['secretValuesChecked']==6 and secrets['findings']==[],'secret_audit_failed')
        require(len(summary['taskPins'])==2,'planned_keyset');seen=set();seqs=[]
        for tp in summary['taskPins']:
            inputs.append(tp);task=readpin(tp);arm=task['arm'];require(arm in ['U','F'] and arm not in seen and task['family']==FAMILY and task['runId']==run and task['officialId']==TASK and task['generationValid'] is True and task['acceptance']['valid'] is True,'task_scope_or_invalid');seen.add(arm)
            require(task['engineStoppedBeforeAcceptance'] is True and task['toolQuiescence']['sealed'] is True and task['toolQuiescence']['outstanding']==0,'task_not_sealed');require(task['promptSha256']==next(r['publicTaskSha256'] for r in catalog['catalog'] if r['id']==TASK),'official_prompt_sha');database_task(task);tool_receipts(task,store,tool_ledger)
            for p in task['databasePins']:inputs.append(p);require(p in raw['databasePins'],'raw_sqlite_pin_missing')
            auth=load('host-auth-'+arm+'.json');require(len(auth)==6 and all(r['status']==401 for r in auth),'host_engine_auth_probe')
            direct=load('tool-auth-'+arm+'.json');require(len(direct['probes'])==4 and all(r['status']==401 for r in direct['probes']) and direct['forwardBefore']==direct['forwardAfter'],'unauthorized_tool_forward')
            candidate_auth=load('candidate-host-auth-'+arm+'.json');candidate_rows=json.loads(candidate_auth if isinstance(candidate_auth,str) else candidate_auth['stdout']);require(len(candidate_rows)==6 and all(r['status']==401 for r in candidate_rows),'candidate_host_auth_probe')
            cold=load('cold-candidate-'+arm+'.json');require(cold['ownedContainerID']==task['artifactCapture']['ownedContainerID'] and cold['environmentAudit']['forbiddenHostKeysPresent'] is False and cold['environmentAudit']['standTokenPresent'] is False,'cold_candidate_environment')
            for receipt in task['apiCalls']:
                n=receipt['requestSeq'];seqs.append(n);require(receipt['journalRef']==facts['refs'][n] and all(v==receipt[k] for k,v in facts['calls'][n].items()),'task_local_call_offsets')
            capture=task['artifactCapture'];cp=pin(Path(capture['captureReceiptPath']));inputs.append(cp);actual=readpin(cp)
            require(all(capture[k]==v for k,v in actual.items()) and capture['containerStopped'] is True and capture['artifactPath']=='/app/workspace/stat_ocr.xlsx' and capture['protocol']==PROTOCOL and re.fullmatch('[a-f0-9]{64}',capture['ownedContainerID']),'fixed_capture_graph')
            if capture['state']=='regular':require(file_sha(Path(capture['hostArtifactPath']))==capture['artifactSha256'],'workbook_sha_changed')
            elif capture['state']=='absent':require(capture['daemonEvidence'].get('missingFileDiagnosticMatched') is True,'missing_artifact_unproved')
            else:require(capture['state'] in ['directory','symlink','too_large'],'unsupported_artifact')
            late=any(r['forwarded'] and r['tool'] in ['bash','write','edit'] and r.get('finishedAt',float('inf'))>task['deadlineUnixMs'] for r in task['toolQuiescence']['receipts']) or capture.get('stoppedAt',0)>task['deadlineUnixMs']
            if late:require(task['acceptance']['passed'] is False and task['acceptance']['outcome']=='budget_exhausted','late_mutation_credited')
            grade=next(r for r in grading['finalGrades'] if r['arm']==arm);require(grade['captureReceiptPin']==cp and grade['gradingStartedAtUnixMs']>=grading['allGenerationClosedAtUnixMs'],'posterior_grading_not_isolated')
            if grade.get('reportPin'):
                inputs.append(grade['reportPin']);report=readpin(grade['reportPin']);v=report['candidateVerdict'];require(report['validated'] is True and report.get('mock') is not True and v['valid'] is True and v['ran'] is True and v['completedTests']==1 and v['imageId']==IMAGE and v['protocol']==PROTOCOL and v['passedTests']==v['reward'] and v['reward'] in [0,1],'official_final_grade')
                if capture['state']=='regular':require(v['artifactSha256']==capture['artifactSha256'],'grade_workbook_sha')
                require(task['acceptance']['passed']==(v['reward']==1) and task['acceptance']['artifactSha256']==capture.get('artifactSha256') and task['acceptance']['candidateSha256']==task['candidateSha256'],'final_acceptance_disagrees')
            else:require(task['generationClassification']['kind']=='experimental_failure' and task['acceptance']['passed'] is False,'grade_missing')
        require(sorted(seqs)==list(range(len(facts['calls']))) and len(seqs)==len(set(seqs)),'calls_not_exact_task_partition')
        require(summary['recordedUsageUpperBoundUsd']==readpin(ledger_pin)['recordedUsageUpperBoundUsd'] and abs(facts['spent']-summary['recordedUsageUpperBoundUsd'])<1e-9,'summary_cost')
        require(summary['providerKind'] in ['local-mock','real-provider'],'provider_kind')
        if summary['providerKind']=='local-mock':require(cash['snapshot']['newExposureNanoCny']=='0' and all(v['servedModel']=='local-mock' for v in facts['calls'].values()) and summary['realProviderRequests']==0,'mock_masquerading_as_paid')
        result={'protocol':'jpg-journal-independent-audit-v1','family':FAMILY,'runId':run,'integrityValid':True,'scoreCertificateValid':True,'formalScoreCertified':summary['providerKind']=='real-provider','modelCalls':0,'auditorSourcePin':pin(Path(__file__)),'inputArtifacts':inputs,'journalPrefix':facts['prefix'],'actualCalls':len(facts['calls']),'errors':[]}
    except Exception as error:
        errors.append(str(error));result={'protocol':'jpg-journal-independent-audit-v1','family':FAMILY,'runId':locals().get('run'),'integrityValid':False,'scoreCertificateValid':False,'formalScoreCertified':False,'modelCalls':0,'auditorSourcePin':pin(Path(__file__)),'inputArtifacts':inputs,'errors':errors}
    save(output/'jpg-independent-audit.json',result);return result

def main():
    p=argparse.ArgumentParser();m=p.add_mutually_exclusive_group(required=True)
    for name in ['freeze','grade','audit','owned','verify-owned']:m.add_argument('--'+name,action='store_true')
    p.add_argument('--recipe',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--store',type=Path);p.add_argument('--capture-pin',type=Path);p.add_argument('--owned-scope',type=Path);p.add_argument('--bun')
    a=p.parse_args()
    if a.freeze:result=freeze(read(a.recipe),a.output,a.store)
    elif a.grade:result=private_grade(read(a.recipe),read(a.capture_pin),a.output)
    elif a.owned:result=owned_probe(read(a.owned_scope),a.output)
    elif a.verify_owned:
        v=read(a.owned_scope);require(v['family']==FAMILY and v['closed'] is True and all(process_absent(x['pid']) for x in v['processes']) and all(port_closed(x['port']) for x in v['ports']),'fresh_owned_not_closed');require(owned_graph(v)==v['actualOwnedGraph'],'fresh_owned_graph_changed');result={'freshOwnedClosed':True,'family':FAMILY,'runId':v['runId'],'modelCalls':0};save(a.output,result)
    else:result=audit(a.output,a.bun)
    print(json.dumps({'validated':result.get('integrityValid',True),'family':FAMILY,'modelCalls':0}));return 1 if result.get('integrityValid') is False else 0

if __name__=='__main__':sys.exit(main())
