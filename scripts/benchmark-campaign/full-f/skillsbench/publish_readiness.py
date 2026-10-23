"""Publish only actual current private controls; retain all87 planned tasks."""
import json
from pathlib import Path
from prepare import HOME,public,save,utc

def checked(pin):
    assert public.pin(Path(pin['path']))==pin
    return json.loads(Path(pin['path']).read_bytes())

def main():
    manifest=json.loads((HOME/'manifest.json').read_bytes());proofs={}
    for row in manifest['taskSchedule']:
        tid=row['taskId'];latest=HOME/'grader-controls'/tid/'latest.json'
        if not latest.exists():continue
        cp=json.loads(latest.read_bytes())['controlPin'];control=checked(cp)
        if not control.get('controlsPassed') or control.get('ownedContainersRemaining')!=0:continue
        bp=control['builtImagesPin'];built=checked(bp)
        if public.pin(Path(built['privateRunnerSourcePin']['path']))!=built['privateRunnerSourcePin']:continue
        if json.loads((HOME/'environment-preparation'/tid/'latest.json').read_bytes())['builtImagesPin']!=bp:continue
        assert control['decisions']==[0,1,0]
        for key in ('collectionPin','emptyPin','oraclePin','wrongPin'):checked(control[key])
        collection=checked(control['collectionPin']);assert collection['complete'] and collection['nodeIds']
        proofs[tid]={'adapter':'ordinary-data-v1','builtImagesPin':bp,'controlPin':cp}
    refresh=json.loads((HOME/'state-refresh-controls/latest.json').read_bytes())['resultPin'];r=checked(refresh)
    assert r['verified'] and all(public.pin(Path(p['path']))==p for p in r['sourcePins'])
    assert proofs
    result={'protocol':'skillsbench-full-f-task-gated-runtime-readiness-v2','denominator':87,'createdAtUtc':utc(),
        'full87Validated':len(proofs)==87,'taskReadiness':proofs,'stateRefreshControlsPin':refresh,
        'pendingPreparationTaskIds':[r['taskId'] for r in manifest['taskSchedule'] if r['taskId'] not in proofs],
        'runtimeSourcePin':public.pin(Path(__file__).with_name('runtime.ts')),'modelCalls':0,'formalScoreCertified':False}
    pin=save(HOME/'runtime-readiness.json',result)
    print(json.dumps({'readyTaskIds':list(proofs),'pendingPreparation':87-len(proofs),'readinessPin':pin}))

if __name__=='__main__':main()
