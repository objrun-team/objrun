"""Independent actual cold/source/readiness replay before any provider admission."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tarfile
import io
import zipfile
import skb_artifact_task_v2 as task
import skb_artifact_transport_v2 as transport
import skb_artifact_native_identity_v2 as native
import skb_artifact_solver_plan_v2 as solver_plan
from skb_artifact_grade_audit_v2 import validate_grade_report
from skb_artifact_solver_audit_v2 import validate_solver_closed


def validate_cold_graph(r):
    index=task.read_json(r['coldControlIndexPin']);task.demand(index['actualColdControls']==30 and index['actualDistinctTaskTriplets']==10
        and len(index['controlPins'])==30 and len({x['path'] for x in index['controlPins']})==30,'ready_cold','Full actual30 unique cold controls required')
    for i,cp in enumerate(index['controlPins']):
        c=task.read_json(cp);dp=r['taskDescriptorPins'][i//3];expected=int(i%3==1)
        task.demand(c['taskDescriptorPin']==dp and c['mode']==('empty','oracle','wrong')[i%3] and c['strictG']==c['officialReward']==expected
            and c['controlMatched'] is True,'ready_cold','Exact complete original0/1/0 inventory differs')
        replay=validate_grade_report(dp,c['gradeOwnerPin'],True);e=replay['result']['evaluation']
        graph=validate_solver_closed(dp,c['solverClosurePin'],True)
        task.demand(e==c['evaluation'] and int(e['allTestsPassed'])==expected and e['officialReward']==expected
            and e['valid']==c['fullCollectionValid'] and (not expected or e['valid'])
            and replay['owner']['capturePin']==c['capturePin'] and c['capturePin'] in graph['closure']['capturePins'],
            'ready_cold','Actual raw cold result or exact solver/grade capture differs')
    return index


def validate_shell(control_pin):
    c=task.read_json(control_pin);p=c['proof'];task.demand(p is not None and c['fault'] is None and p['actualOriginalShellExecuted'] is True
        and p['aptCurlUvShimUsed'] is False,'ready_shell','Actual unmodified original shell comparison required')
    dp=p['taskDescriptorPin'];graph=validate_solver_closed(dp,c['solverClosurePin'],True,False);closure=graph['closure'];box=Path(c['solverClosurePin']['path']).parent
    d=task.read_json(dp);record=task.read_json(p['shellCommandRecordPin'])
    matches=[(a,x) for a,x in graph['commandRecords'] if a==['exec',closure['containerID'],'/bin/bash','/verifier/test.sh'] and x['exitCode']==0]
    task.demand(len(matches)==1 and matches[0][1]==record and record['stdoutPin']['bytes']>0,'ready_shell','Actual original shell native command graph differs')
    for row in [*d['verifierFilePins'],*d['privatePublicFixturePins']]:
        task.demand(any(a==['cp',row['sourcePin']['path'],closure['containerID']+':'+row['containerPath']] and x['exitCode']==0 for a,x in graph['commandRecords']),
            'ready_shell_source','Original verifier/fixture was not actually seeded')
    transfer=task.read_json(p['logTransferRecordPin'])
    transfers=[x for a,x in graph['commandRecords'] if a==['cp',closure['containerID']+':/logs/verifier/.','-'] and x['exitCode']==0]
    task.demand(len(transfers)==1 and transfers[0]==transfer,'ready_shell_transfer','Original logs must belong to the exact successful native transfer')
    task.verify_pin(transfer['stdoutPin'],16*1024**2);bodies={}
    with tarfile.open(fileobj=io.BytesIO(Path(transfer['stdoutPin']['path']).read_bytes()),mode='r:') as archive:
        for m in archive:
            if m.isdir():continue
            name=m.name.removeprefix('./');task.demand(m.isfile() and '/' not in name and name not in bodies,'ready_shell_tar','Ordinary unique original logs required')
            bodies[name]=archive.extractfile(m).read()
    for name,q in p['originalLogPins'].items():
        task.verify_pin(q);task.demand(name in bodies and hashlib.sha256(bodies[name]).hexdigest()==q['sha256'],'ready_shell_tar','Original log bytes differ from actual TAR')
    task.demand(set(bodies)==set(p['originalLogPins']),'ready_shell_tar','Complete actual original shell log inventory required')
    oracle=task.read_json(p['offlineOracleControlPin']);grade=validate_grade_report(dp,oracle['gradeOwnerPin'],True)
    offline=task.read_json(grade['owner']['resultPins']['ctrf.json']);original=task.read_json(p['originalLogPins']['ctrf.json'])
    rows=lambda x:sorted((q['name'],q['status']) for q in x['results']['tests'])
    task.demand(rows(original)==rows(offline) and all(x[1]=='passed' for x in rows(original)) and float(bodies['reward.txt'])==1,'ready_shell_result','Full original/offline oracle outcomes differ')
    return p


def validate_fractional(pin,lab_descriptor):
    f=task.read_json(pin);dp=f['taskDescriptorPin'];replay=validate_grade_report(dp,f['gradeOwnerPin'],True);e=replay['result']['evaluation']
    graph=validate_solver_closed(dp,f['solverClosurePin'],True)
    task.demand(dp==lab_descriptor and f['taskId']==task.read_json(dp)['taskId']=='lab-unit-harmonization' and e==f['evaluation']
        and e['valid'] is True and e['allTestsPassed'] is False and e['passedTests']+e['failedTests']==48
        and 0<e['officialReward']==f['numericReward']<1 and f['strictG']==0 and f['fullCollectionValidated'] is True
        and replay['owner']['capturePin']==f['capturePin'] and f['capturePin'] in graph['closure']['capturePins'],
        'ready_fractional','Actual lab fractional original reward/full collection/strict false and capture required')
    mutation=task.read_json(f['mutationPin'])
    rows=[x for a,x in graph['commandRecords'] if a[:4]==['exec',graph['closure']['containerID'],'/usr/local/bin/python3','-I'] and x['exitCode']==0]
    task.demand(len(rows)==1 and rows[0]['stdoutPin']['sha256']==f['mutationPin']['sha256']
        and rows[0]['stdoutPin']['bytes']==f['mutationPin']['bytes'] and mutation['row']==0 and mutation['old']!=mutation['new'],
        'ready_fractional_mutation','Numeric data mutation must be actual source-bound solver stdout')
    oracle=task.read_json(f['oracleControlPin']);task.demand(oracle['taskDescriptorPin']==dp and oracle['mode']=='oracle' and oracle['officialReward']==1,'ready_fractional_oracle','Actual same lab oracle required')
    return f


def validate_six_control(pin):
    s=task.read_json(pin);graph=validate_solver_closed(s['taskDescriptorPin'],s['solverClosurePin'],True)
    task.demand(s['allSixActualEffectsMatched'] is True and s['fault'] is None and len(s['toolResults'])==6
        and [x['tool'] for x in s['toolResults']]==['bash','read','write','edit','glob','grep'],'ready_six','Actual ordered six-tool effects required')
    cid=graph['closure']['containerID'];nonce=graph['closure']['instanceNonce'];box=Path(s['solverClosurePin']['path']).parent
    task.verify_pin(s['sourcePin']);task.demand(task.pin(box/'six-tool-control-source.py')['sha256']==s['sourcePin']['sha256'],'ready_six_source','Executed six-tool control bytes differ')
    for i,row in enumerate(s['toolResults'],1):
        request_pin=task.pin(box/('tool-%04d.json'%i));request=task.read_json(request_pin)
        task.demand(request=={'tool':row['tool'],'args':row['args']},'ready_six_request','Actual RPC input differs from control')
        remote='/tmp/objrun-tool-'+nonce+'-'+str(i)+'.json'
        copies=[x for a,x in graph['commandRecords'] if a==['cp',request_pin['path'],cid+':'+remote] and x['exitCode']==0]
        rpcs=[x for a,x in graph['commandRecords'] if a[:7]==['exec','--env','LD_LIBRARY_PATH=/rt-lib',cid,'/rt-node','-e',solver_plan.ONE_TOOL_WRAPPER]
            and len(a)==10 and a[7:9]==[remote,request_pin['sha256']] and a[9].isdigit() and int(a[9])>0 and x['exitCode']==0]
        task.demand(len(copies)==len(rpcs)==1,'ready_six_rpc','Exact native request transfer and frozen runtime command required')
        value=task.read_json(rpcs[0]['stdoutPin'],8*1024**2);task.demand(not value.get('isError'),'ready_six_rpc','Actual RPC returned an error')
        if 'structuredContent' in value:result=value['structuredContent']
        else:
            text=''.join(x.get('text','') for x in value.get('content',[]))
            try:result=json.loads(text)
            except ValueError:result=text
        task.demand(result==row['result'],'ready_six_result','Actual raw RPC result differs from claimed effect')
    task.demand('skb-runtime-before' in json.dumps(s['toolResults'][1]['result']) and 'skb-runtime-edited' in json.dumps(s['toolResults'][5]['result'])
        and 'objrun-skb-six-tool-control.txt' in json.dumps(s['toolResults'][4]['result']),'ready_six_effect','Native read/edit/grep/glob results did not observe the expected effect')
    return s


def audit(rp,paid):
    r=task.read_json(rp);task.demand(r['family']=='skillsbench-artifact-journal-v1' and len(r['taskDescriptorPins'])==10,'ready_scope','Exact10-task scope required')
    for p in r['sourcePins']:task.verify_pin(p,512*1024**2)
    freeze=task.read_json(r['freezePin'],16*1024**2);task.demand(freeze['sourcePins']==r['sourcePins'] and freeze['sourceBeforeAfterEqual'] is True,'ready_source','Complete executed freeze/source frontier required')
    task.verify_pin(freeze['archivePin'],1536*1024**2)
    with zipfile.ZipFile(freeze['archivePin']['path']) as archive:
        expected={str(Path(p['path']).relative_to(task.REPO)).replace('\\','/'):p for p in r['sourcePins']}
        task.demand(set(archive.namelist())==set(expected) and len(archive.namelist())==len(expected),'ready_archive','Exact unique source archive inventory required')
        for name,p in expected.items():
            h=hashlib.sha256();size=0
            with archive.open(name) as f:
                while b:=f.read(1024*1024):h.update(b);size+=len(b)
            task.demand(size==p['bytes'] and h.hexdigest()==p['sha256'],'ready_archive','Source snapshot bytes differ')
    for dp in r['taskDescriptorPins']:task.validate_descriptor(task.read_json(dp),True)
    cold=validate_cold_graph(r);shell=task.read_json(r['originalShellIndexPin'])
    task.demand(len(shell['comparisonPins'])==10,'ready_shell','All10 original shell comparisons required')
    for i,p in enumerate(shell['comparisonPins']):task.demand(validate_shell(p)['taskDescriptorPin']==r['taskDescriptorPins'][i],'ready_shell','Original shell task order differs')
    validate_fractional(r['fractionalControlPin'],r['taskDescriptorPins'][7]);validate_six_control(r['sixToolControlPin'])
    initial=task.read_json(r['initialStorePin']);task.demand(initial['storageDescriptorPin']==r['storageDescriptorPin'] and initial['setupNativeHandleClosed'] is True,'ready_store','Exact actually initialized fresh D namespace required')
    native.closed_identity(initial['creatorPid'],int(datetime.fromisoformat(initial['initializedAtUtc']).timestamp()*1000))
    if paid:
        c=task.read_json(r['runtimeGatePin']);task.demand(c['kind']=='local-mock' and c['family']==r['family'],'ready_factory','Actual shared engine runtime control required')
        mock=task.read_json(c['recipePin']);task.demand(mock['sourcePins']==r['sourcePins'] and mock['taskDescriptorPins']==r['taskDescriptorPins'],'ready_factory','Current exact source/task frontier differs from actual engine control')
        from importlib.util import spec_from_file_location,module_from_spec
        spec=spec_from_file_location('skb_final_audit',Path(__file__).with_name('audit-skb-artifact-journal-v2.py'));module=module_from_spec(spec);spec.loader.exec_module(module)
        module.audit(c['recipePin'],'local-mock')
    return {'protocol':'skillsbench-ten-independent-pre-provider-readiness-v2','recipePin':rp,'actualColdControlsReplayed':30,'actualOriginalShellComparisonsReplayed':10,
        'actualFractionalRewardReplayed':True,'actualSixToolEffectsReplayed':True,'paidRequested':paid,'modelCalls':0,'sourcePin':task.pin(__file__)}


def main():
    p=argparse.ArgumentParser();p.add_argument('--recipe',type=Path,required=True);p.add_argument('--sha256',required=True);p.add_argument('--paid',action='store_true');a=p.parse_args()
    rp=task.pin(a.recipe.resolve());task.demand(rp['sha256']==a.sha256,'ready_pin','Exact recipe bytes required')
    print(json.dumps(audit(rp,a.paid)),flush=True)


if __name__=='__main__':main()
