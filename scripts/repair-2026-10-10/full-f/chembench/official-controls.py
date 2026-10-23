"""Oracle-only controls: never emit reference answers to the solver or artifact."""
import hashlib, importlib.util, json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / 'docs/repair-2026-10-10/full-f-rerun/chembench'
HOME = ROOT / '.phase1-data/chembench'
os.environ['TGENGIN_CHB_HOME'] = str(HOME)
source = json.loads((HOME / 'source.json').read_text())
for row in source['files']:
    p = HOME / 'vendor/chembench' / row['path']
    assert hashlib.sha256(p.read_bytes()).hexdigest() == row['sha256'], str(p)
assert hashlib.sha256((HOME / 'chembench.jsonl').read_bytes()).hexdigest() == source['derivedDataset']['sha256']
spec = importlib.util.spec_from_file_location('chembench_oracle', ROOT / 'examples/benchmark/chembench/stand.py')
stand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stand)
rows=json.loads((OUT/'public-tasks.json').read_text())
checks=[]
for row in rows:
    uid=row['officialId'].removeprefix('chb-')
    item=stand.BOOK[uid]
    assert stand.prompt_of(item)[0] == row['row']['prompt'], uid
    good=stand.judge(stand.golden_of(item),item)
    if stand.is_mcq(item):
        _,scores=stand.prompt_of(item)
        zeros=[k for k,v in scores.items() if v!=1]
        wrong='[ANSWER]'+(zeros[0] if zeros else list(scores)[0] if len(scores)>1 else 'Z')+'[/ANSWER]'
    else:
        target=float(item['example']['target'])
        wrong=f'[ANSWER]{target+max(1.0,abs(target)*1000)}[/ANSWER]'
    bad=stand.judge(wrong,item)
    bare=stand.judge('I am not sure about this.',item)
    checks.append({'officialId':row['officialId'],'positiveParsed':bool(good['parsed']),'positiveAccepted':bool(good['correct']),
        'negativeRejected':not bool(bad['correct']),'formatRejected':not bool(bare['parsed'])})
passed=all(all(v for k,v in c.items() if k!='officialId') for c in checks)
report={'protocol':'chembench-full-f-official-controls-v1','tasks':len(checks),'allPassed':passed,'checks':checks,
    'officialCommit':source['commit'],'datasetRevision':source['datasetRevision'],'modelCalls':0,'referenceAnswersEmitted':False}
(OUT/'official-controls.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'tasks':len(checks),'allPassed':passed,'modelCalls':0}))
sys.exit(0 if passed else 1)
