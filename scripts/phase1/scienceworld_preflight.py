"""Small Java/Python simulator preflight; no new container or toolchain download."""
import hashlib
import json
import os
from pathlib import Path
import sys
import types
ROOT=Path(__file__).resolve().parents[2]
HOME=ROOT/'.phase1-data/scienceworld'
VENDOR=HOME/'vendor/ScienceWorld'
sys.path[:0]=[str(ROOT/'.phase1-data/host-extras'),str(VENDOR)]
version=types.ModuleType('scienceworld.version')
version.__version__='source-e8216d60'
sys.modules['scienceworld.version']=version
tmp=HOME/'tmp'
tmp.mkdir(exist_ok=True)
os.environ['TMP']=os.environ['TEMP']=str(tmp)
os.environ['JAVA_TOOL_OPTIONS']='-Xmx512m -Djava.io.tmpdir='+str(tmp).replace('\\','/')
from scienceworld import ScienceWorldEnv
world=ScienceWorldEnv(envStepLimit=100)
records=[]
try:
    names=world.get_task_names()[:10]
    for task in names:
        world.load(task,0,'',generateGoldPath=False)
        variation=world.get_variations_test()[0]
        world.load(task,variation,'',generateGoldPath=True)
        actions=world.get_gold_action_sequence()
        world.reset()
        initial=world.get_task_description()
        for action in actions:
            _,_,done,info=world.step(action)
            if done: break
        ok=info['score']==100
        record={'task':task,'variation':variation,'goldActions':len(actions),'score':info['score'],'passed':ok,'descriptionSha256':hashlib.sha256(initial.encode()).hexdigest()}
        records.append(record)
        print(json.dumps(record),flush=True)
    result={'allPassed':all(r['passed'] for r in records),'records':records,'sourceCommit':'e8216d6044e8e39be9fcb185e3b2dfb602584b52','jarSha256':hashlib.sha256((VENDOR/'scienceworld/scienceworld.jar').read_bytes()).hexdigest(),'java':'1.8.0_341','py4j':'0.10.9.7','taskUnit':'full action episode','simplification':'none','stepLimit':100}
    (ROOT/'docs/phase1/scienceworld-selfcheck.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    record=json.loads((HOME/'source.json').read_text(encoding='utf-8'))
    record['selectedEpisodes']=[{'task':r['task'],'variation':r['variation']} for r in records]
    record['jarSha256']=result['jarSha256']
    (HOME/'source.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
finally: world.close()
