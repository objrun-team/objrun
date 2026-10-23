"""Freeze full official TB source and deadlines; no paid requests or Docker mutations."""
from pathlib import Path
import hashlib, json, subprocess, tomllib, urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / 'docs/repair-2026-10-10/full-f-rerun/terminal-bench'
CORPUS = ROOT / '.phase1-data/terminal-bench/vendor/terminal-bench-2-1/tasks'

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def write(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'TgEngin-full-F-source-audit'}), timeout=30).read()

def main():
    source = json.loads((ROOT/'.phase1-data/terminal-bench/source.json').read_bytes())
    catalog = tomllib.loads((CORPUS/'dataset.toml').read_text(encoding='utf-8'))
    ids = [x['name'].split('/')[-1] for x in catalog['tasks']]
    dirs = sorted(d.name for d in CORPUS.iterdir() if (d/'task.toml').is_file())
    assert len(ids) == len(set(ids)) == 89 and set(ids) == set(dirs)
    OUT.mkdir(parents=True, exist_ok=True)
    upstream = json.loads(fetch('https://api.github.com/repos/harbor-framework/terminal-bench-2-1/commits/main'))
    commit = upstream['sha']
    remote = fetch(f'https://raw.githubusercontent.com/harbor-framework/terminal-bench-2-1/{commit}/tasks/dataset.toml')
    (OUT/'current-official-dataset.toml').write_bytes(remote)
    current_ids = [x['name'].split('/')[-1] for x in tomllib.loads(remote.decode())['tasks']]
    pinned = fetch(f'https://raw.githubusercontent.com/harbor-framework/terminal-bench-2-1/{source["commit"]}/tasks/dataset.toml')
    assert pinned == (CORPUS/'dataset.toml').read_bytes(), 'Local official manifest differs from pinned upstream'
    records=[]
    for tid in ids:
        d=CORPUS/tid
        t=tomllib.loads((d/'task.toml').read_text(encoding='utf-8'))
        files = [p for p in d.rglob('*') if p.is_file() and p.relative_to(d).parts[0] != 'solution']
        records.append({'taskId':tid,'agentSeconds':t['agent']['timeout_sec'],
            'verifierSeconds':t['verifier']['timeout_sec'],'officialEnvironment':t['environment'],
            'sourceFiles':[{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)],
            'resultState':'planned'})
    manifest={'protocol':'terminal-bench-full-F-manifest-v1','createdAtUtc':datetime.now(timezone.utc).isoformat(),
        'benchmarkVersion':'2.1','source':source,'officialManifestSha256':sha(CORPUS/'dataset.toml'),
        'upstreamCurrentCommit':commit,'upstreamCurrentCount':len(current_ids),
        'currentExcludedRelativeToFrozen89':sorted(set(ids)-set(current_ids)),
        'currentAddedRelativeToFrozen89':sorted(set(current_ids)-set(ids)),
        'taskIds':ids,'plannedTaskRuns':89,'arms':['F'],'replicas':1,
        'model':'deepseek/deepseek-v4.1-flash','provider':'relace','allow_fallbacks':False,
        'reasoning':{'enabled':True,'effort':'high','exclude':False},'maxTokens':16384,'temperature':0,
        'checks':4,'reuse':'never','maxBranches':1,'maxDeadSiblings':1,'maxUnitsPerCycle':32,
        'requestConcurrency':1,'heavyContainerSlots':1,'records':records,
        'noPilotResultsReused':True,'noURequests':True,'requiresSharedBroker':True,
        'scoringReady':False,'sourceFreezeDecision':'89-task official commit frozen; current registry difference retained explicitly'}
    target=OUT/'manifest.json'
    if target.exists():
        old=json.loads(target.read_bytes())
        assert old['source']==source and old['records']==records, 'Frozen task source changed'
    else: write('manifest.json',manifest)
    write('catalog-audit.json',{'localManifestCount':89,'localDirectoryCount':len(dirs),
        'currentOfficialCommit':commit,'currentOfficialManifestCount':len(current_ids),
        'removed':sorted(set(ids)-set(current_ids)),'added':sorted(set(current_ids)-set(ids)),
        'pinnedManifestVerifiedAgainstUpstream':True,'manifestSha256':sha(target)})
    print(json.dumps({'output':str(OUT),'tasks':89,'currentCount':len(current_ids),'removed':sorted(set(ids)-set(current_ids))}))

if __name__=='__main__':main()
