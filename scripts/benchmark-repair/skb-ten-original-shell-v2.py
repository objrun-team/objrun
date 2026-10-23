"""Actual unmodified original shell in an isolated cold container, no models."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import tarfile
import io
import uuid
import skb_artifact_task_v2 as task
import skb_artifact_capture_v2 as capture
from skb_artifact_solver_v2 import Solver
from skb_artifact_ram_executor_v2 import fresh

ORIGINAL_SHELL_CAPS=['CHOWN','DAC_OVERRIDE','FOWNER','SETGID','SETUID']


class OriginalShellSolver(Solver):
    def __init__(self,dp,lp):
        super().__init__(dp,lp)
        argv=self.plan['createArgv'].copy();at=argv.index(self.plan['imageId'])
        argv[at:at]=[part for cap in ORIGINAL_SHELL_CAPS for part in ('--cap-add',cap)]
        self.plan={**self.plan,'createArgv':argv,'coldOriginalShellCapabilities':ORIGINAL_SHELL_CAPS}
        self.plan_pin=fresh(self.box/'original-shell-solver-plan.json',task.canonical(self.plan),self.root)
        p=task.pin(__file__);self.sources.append(p)
        q=fresh(self.box/'executed-source/original-shell-producer.py',Path(__file__).read_bytes(),self.root)
        self.snapshots.append({'originalPin':p,'snapshotPin':q})


def main():
    p=argparse.ArgumentParser()
    for k in ('control','storage'):
        p.add_argument('--'+k,type=Path,required=True);p.add_argument('--'+k+'-sha256',required=True)
    a=p.parse_args();pins=[]
    for k in ('control','storage'):
        q=task.pin(getattr(a,k).resolve());task.demand(q['sha256']==getattr(a,k+'_sha256'),'shell_pin','Exact cold evidence required');pins.append(q)
    cp,lp=pins;c=task.read_json(cp);dp=c['taskDescriptorPin'];d=task.read_json(dp)
    task.demand(c['mode']=='oracle' and c['strictG']==1 and c['fullCollectionValid'] is True,'shell_oracle','Actual complete offline oracle control required')
    cap=capture.validate_capture_receipt(dp,c['capturePin']);task.demand(cap['state']=='regular','shell_artifact','Exact source-pinned oracle artifact required')
    solver=OriginalShellSolver(dp,lp);proof=None;fault=None;box=solver.box;log_pins={}
    allowed_logs={'ctrf.json','reward.txt','test_output.log'}|{Path(x['containerPath']).name for x in [*d['privatePublicFixturePins'],*d['outputArtifacts']]}
    fresh(box/'original-shell-control-source.py',Path(__file__).read_bytes(),solver.root)
    try:
        solver.create(False)
        # This separate cold operation measures the original verifier deadline;
        # it is neither agent time nor a model trial.
        solver.timer.cancel();solver.timer=None
        solver.command('exec',solver.cid,'mkdir','-p','/verifier','/logs/verifier')
        for row in [*d['verifierFilePins'],*d['privatePublicFixturePins']]:
            q=row['sourcePin'];task.verify_pin(q,64*1024**2)
            solver.command('cp',q['path'],solver.cid+':'+row['containerPath']);task.verify_pin(q,64*1024**2)
        q=cap['artifactPin'];task.verify_pin(q,task.MAX_ARTIFACT)
        solver.command('cp',q['path'],solver.cid+':'+d['outputArtifacts'][0]['containerPath'])
        row,out,err=solver.command('exec',solver.cid,'/bin/bash','/verifier/test.sh',timeout=d['originalResources']['verifier']['timeout_sec'],cap=16*1024**2,checked=False)
        shell_record=solver.records[-1]['recordPin']
        task.demand(row['exitCode']==0,'shell_execution','Original shell failed; actual raw retained')
        row,raw,err=solver.command('cp',solver.cid+':/logs/verifier/.','-',cap=16*1024**2)
        transfer=solver.records[-1]['recordPin']
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
            for member in archive:
                name=member.name.removeprefix('./')
                if member.isdir():continue
                task.demand(member.isfile() and '/' not in name and name in allowed_logs and name not in log_pins
                            and 0<=member.size<=8*1024**2,'shell_logs','Exact ordinary original shell log inventory required')
                body=archive.extractfile(member).read();log_pins[name]=fresh(box/('original-'+name),body,solver.root)
        task.demand({'ctrf.json','reward.txt'}<=set(log_pins),'shell_logs','Actual original CTRF/reward absent')
        ctrf=task.read_json(log_pins['ctrf.json']);reward=float(Path(log_pins['reward.txt']['path']).read_text().strip())
        offline=task.read_json(task.read_json(c['gradeOwnerPin'])['resultPins']['ctrf.json'])
        a_tests=ctrf['results']['tests'];b_tests=offline['results']['tests']
        canonical=lambda rows:sorted([(x['name'],x['status']) for x in rows])
        task.demand(canonical(a_tests)==canonical(b_tests) and len(a_tests)==c['evaluation']['collectedTests'] and all(x['status']=='passed' for x in a_tests)
                    and reward==c['officialReward']==1,'shell_equivalence','Original shell and fixed offline oracle outcomes differ')
        py='/usr/local/bin/python3' if d['taskId'] in ('earthquake-plate-calculation','econ-detrending-correlation','lab-unit-harmonization') else '/usr/bin/python3'
        code="import hashlib,importlib.metadata as m,json,os,sys; names=['pytest','pytest-json-ctrf','numpy','pandas','pypdf','openpyxl','python-docx','lxml','defusedxml','six','rapidfuzz']; packages={};\nfor n in names:\n try:packages[n]=m.version(n)\n except m.PackageNotFoundError:pass\nprint(json.dumps({'python':sys.version,'pythonPath':sys.executable,'pythonSha256':hashlib.sha256(open(sys.executable,'rb').read()).hexdigest(),'installedInMainPython':packages,'uvSha256':hashlib.sha256(open('/root/.local/bin/uv','rb').read()).hexdigest() if os.path.isfile('/root/.local/bin/uv') else None}))"
        _,versions,_=solver.command('exec',solver.cid,py,'-I','-B','-c',code)
        versions_pin=fresh(box/'original-shell-versions.json',versions,solver.root)
        proof={'protocol':'skillsbench-real-original-shell-comparison-v2','taskId':d['taskId'],'taskDescriptorPin':dp,'offlineOracleControlPin':cp,
            'originalShellSourcePin':next(x['sourcePin'] for x in d['verifierFilePins'] if x['containerPath']=='/verifier/test.sh'),
            'actualOriginalShellExecuted':True,'aptCurlUvShimUsed':False,'shellCommandRecordPin':shell_record,'logTransferRecordPin':transfer,
            'originalLogPins':log_pins,'originalRuntimeVersionsPin':versions_pin,'wholeOriginalCollectionMatched':True,'officialReward':reward,
            'separateColdVerifierOperation':True,'verifierTimeoutSeconds':d['originalResources']['verifier']['timeout_sec'],'modelCalls':0,
            'differences':['Original shell may install current packages and network tools; the offline runner uses the fixed21-wheel depot and sealed Python3.12.3','Cold original shell has rootfs writable/public network and five explicit installer capabilities; paid solver/private grader retain cap-drop ALL and no added capabilities'],
            'coldOriginalShellCapabilities':ORIGINAL_SHELL_CAPS,
            'sourcePin':task.pin(__file__),'observedAtUtc':datetime.now(timezone.utc).isoformat()}
    except BaseException as e:fault={'type':type(e).__name__,'kind':getattr(e,'kind',None),'detail':str(e)[:512]}
    finally:closed=solver.close()
    result=fresh(box/'original-shell-comparison.json',task.canonical({'proof':proof,'fault':fault,'solverClosurePin':closed,'sourcePin':task.pin(__file__),'modelCalls':0}),solver.root)
    print(json.dumps({'originalShellComparisonPin':result,'taskId':d['taskId'],'matched':proof is not None,'fault':fault,'ownedClosed':solver.closed,'modelCalls':0}),flush=True)
    raise SystemExit(0 if proof and solver.closed else 1)


if __name__=='__main__':main()
