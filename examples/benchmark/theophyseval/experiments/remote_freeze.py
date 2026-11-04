"""Freeze precisely the independent run, without scanning shared project trees."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
from remote_entry import runtime_env

ROOT=(Path(__file__).resolve().parents[4] / 'scripts')
PROJECT=ROOT.parents[1]

def main():
    target=ROOT/'control/freeze.json'
    if target.exists():raise RuntimeError('ExistingFreezeMustNotBeReplaced')
    for name in ['pilot-acceptance','remote-acceptance']:
        assert json.loads((ROOT/'control'/(name+'.json')).read_text())['passed']
    env=runtime_env()
    paths=[]
    for group in ['package','data','source']:
        for p in sorted((ROOT/group).rglob('*')):
            if p.is_file() and not any(x in {'node_modules','__pycache__','.cache'} for x in p.parts):paths.append(p)
    paths += [ROOT/'control'/name for name in ['remote-runtime.json','remote-acceptance.json','pilot-acceptance.json','environment.json',
        'grading-controls.json','special-grading-controls.json','container-controls.json','engine-controls.json','timeout-controls.json',
        'auth-controls.json','control-plane-controls.json','resource-controls.json','scheduling-controls.json','network-quota-controls.json',
        'image-inventory-controls.json','seiberg-environment-equivalence.json','seiberg-frozen-base.Dockerfile']]
    files=[{'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]
    relative=ROOT.relative_to(PROJECT).as_posix()
    subprocess.run(['git','add','--',*[str(p.relative_to(PROJECT)) for p in paths]],cwd=PROJECT,env=env,check=True)
    subprocess.run(['git','-c','user.name=objrun','-c','user.email=objrun@local','commit','-qm','Freeze TheoPhysEval automatic49 novaeve four-arm protocol and independent runtime'],cwd=PROJECT,env=env,check=True)
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT,env=env,text=True).strip()
    record={'gitCommit':commit,'files':files,'modelsUnchanged':True,'provider':'DigitalOcean only','scientificBudgetUnchanged':True}
    target.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'gitCommit':commit,'frozenFiles':len(files)}))

if __name__=='__main__':main()
