"""Build an isolated source package and privately freeze one permutation per item."""
from pathlib import Path
import ast
import json
import random
import secrets
import shutil
from protocol import NAME,REVISION,PARAMETERS,PROTOCOL_SHA,RULES,TOOLS,REFUSE,digest

REPO=Path(__file__).resolve().parents[4]
ROOT=REPO.parent/'tmp'/NAME
RESEARCH=REPO.parent/'tmp/labbench-design-20261019'
ORIGIN=REPO/'docs/frontierscience/frontierscience-formal-20261016-v1-deepseek-c32/frozen-source/package/engine'


def main():
    if ROOT.exists():raise RuntimeError('ExistingStageInspectNoOverwrite')
    package=ROOT/'package';package.mkdir(parents=True)
    for p in Path(__file__).parent.iterdir():
        if p.suffix in {'.py','.ts'}:shutil.copy2(p,package/p.name)
    engine=package/'engine'
    shutil.copytree(ORIGIN,engine,ignore=shutil.ignore_patterns('node_modules','__pycache__','.env'))
    # Use the already verified bounded-readiness/logging harness, changing only its placeholder key.
    previous=REPO.parent/'tmp/olympiadbench-formal-20261017-v1-deepseek-c16/package/engine/test/_lib.ts'
    if not previous.exists():raise RuntimeError('VerifiedHarnessMissing')
    text=previous.read_text(encoding='utf-8').replace('DEEPSEEK_API_KEY: "local-bridge-placeholder"','OPENROUTER_API_KEY: "local-bridge-placeholder"')
    assert '"--no-install"' in text and 'readyDeadline' in text
    (engine/'test/_lib.ts').write_text(text,encoding='utf-8')
    vendor=package/'vendor';vendor.mkdir()
    for name in ['labbench/utils.py','labbench/evaluator.py','ProtocolQA/task.py','SeqQA/task.py']:
        dest=vendor/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(RESEARCH/'upstream'/name,dest)
    data=ROOT/'data';data.mkdir();raw=data/'original';raw.mkdir()
    sourcefiles=json.loads((RESEARCH/'source-files.json').read_text())
    assert sourcefiles['revision']==REVISION
    pins={x['path']:x['sha256'] for x in sourcefiles['files']}
    public=[];private=[];manifest=[]
    for category in ['ProtocolQA','SeqQA']:
        for path in sorted((RESEARCH/'upstream'/category).glob('*-public.jsonl')):
            rel=path.relative_to(RESEARCH/'upstream').as_posix();assert digest(path.read_bytes())==pins[rel]
            dest=raw/rel;dest.parent.mkdir(exist_ok=True);shutil.copy2(path,dest)
            for index,line in enumerate(path.read_text(encoding='utf-8').splitlines()):
                if not line.strip():continue
                r=json.loads(line);seed=secrets.token_hex(32);perm=list(range(len(r['distractors'])+2));random.Random(seed).shuffle(perm)
                choices=[r['ideal'],REFUSE,*r['distractors']]
                displayed=[f'({chr(65+i)}) {choices[j]}' for i,j in enumerate(perm)]
                question=r.get('protocol','')+r['question']
                prompt=('The following is a multiple choice question about biology.\nQuestion: '+question+'\n\nOptions:\n'+'\n'.join(displayed)+
                        '\n\nYou MUST return your final choice as [ANSWER]L[/ANSWER], where L is exactly one of the displayed option letters. You may reason before this single final answer tag. Do not output multiple answer tags.')
                p={'id':r['id'],'category':category,'subtask':path.stem,'prompt':prompt,'choiceCount':len(choices)}
                secret={'id':r['id'],'target':chr(65+perm.index(0)),'unsure':chr(65+perm.index(1)),
                        'seed':seed,'permutation':perm,'permutationSha256':digest(perm),'choiceCount':len(choices),
                        'source':rel,'sourceRow':index,'promptSha256':digest(prompt)}
                public.append(p);private.append(secret);manifest.append({'id':r['id'],'source':rel,'sourceRow':index,'promptSha256':digest(prompt)})
    assert len(public)==len({p['id'] for p in public})==708
    proto=[p for p in public if p['category']=='ProtocolQA'];canary=[]
    for n in [5,6,7,8]:canary.append(next(p['id'] for p in proto if p['choiceCount']==n))
    canary.append(max((p for p in proto if p['id'] not in canary),key=lambda p:len(p['prompt']))['id'])
    for sub in sorted({p['subtask'] for p in public if p['category']=='SeqQA'}):canary.append(next(p['id'] for p in public if p['subtask']==sub))
    assert len(set(canary))==20
    # Interleave the sixteen strata rather than running the entire 600-question subset consecutively.
    buckets={sub:[p for p in public if p['subtask']==sub] for sub in sorted({p['subtask'] for p in public})};ordered=[]
    while any(buckets.values()):
        for bucket in buckets.values():
            if bucket:ordered.append(bucket.pop(0))
    for name,value in [('public-tasks.json',ordered),('private-tasks.json',private),('manifest.json',manifest),
                       ('source.json',{'revision':REVISION,'count':708,'canaryIds':canary,'sourceFiles':{k:v for k,v in pins.items() if k.endswith('-public.jsonl') and k.startswith(('ProtocolQA/','SeqQA/'))},
                                       'canarySelection':'ProtocolQA first 5/6/7/8-choice and longest unused; SeqQA first row of each subtask; same protocol included in formal'})]:
        (data/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    cfg={'run':NAME,'benchmark':'LAB-Bench ProtocolQA108 SeqQA600 public MCQ','dataRevision':REVISION,'taskCount':708,'arms':['baseline','objrun'],
         'parameters':PARAMETERS,'canonicalModel':'deepseek/deepseek-v4.1-flash-20260910','rules':RULES,'protocolSha256':PROTOCOL_SHA,
         'solveSeconds':600,'engineStartupSeconds':60,'checksPerAttempt':5,'maxBranches':4,'cyclesMaxUnits':12,
         'taskConcurrency':16,'modelConcurrency':16,'graderConcurrency':4,'toolPolicy':TOOLS,'logicalCallMaxAttempts':3,
         'perQuestionDollarCap':None,'batchBudgetUsd':None,'statistics':{'seed':20261019,'replicates':20000,'stratify':'category/subtask'},
         'authorization':'User authorized zero-model acceptance, 20x2 pilot then automatic full708x2 on novaeve; OpenRouter pinned DigitalOcean; 15-minute follow-up and complete verified local delivery.'}
    (package/'experiment.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    prov=ROOT/'provenance';prov.mkdir()
    (prov/'engine-origin.json').write_text(json.dumps({'origin':str(ORIGIN),'harnessOrigin':str(previous),'changes':['bounded readiness/log capture harness; OpenRouter bridge placeholder credential only'],
        'files':{p.relative_to(engine).as_posix():digest(p.read_bytes()) for p in engine.rglob('*') if p.is_file()}},indent=2)+'\n')
    print(json.dumps({'stage':str(ROOT),'count':len(public),'canaryIds':canary}))


if __name__=='__main__':main()
