"""Read historical run stores without applying the current grader or backfilling provenance."""
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
ROOT=Path(__file__).resolve().parents[2]
GROUPS={
'cmt':['cmt-u-0731','cmt-f-0731','cmt-f-c5kinf-0929'],
'gpqa':['gpqa-u-0731','gpqa-u-ns','gpqa-f-ns','gpqa-f-c5kinf-0928'],
'aime':['aime-u-0731','aime-u-ns','aime-f-ns'],
'chembench':['chembench-u-0731','chembench-u-0731b','chembench-u-hold-control','chembench-u-distill-hold-pooled','chembench-f-500','chembench-f-c5kinf-0929'],
'chemiq':['chemiq-u-0731','chemiq-f-0731','chemiq-f-c5kinf-0929'],
'minif2f':['minif2f-u-0731','minif2f-f-0731','minif2f-f-0731b'],
'deepswe':['dsw-u-0930'],
'skillsbench':['skb-f-c5kinf-0929'],
 'terminal-bench':['tb-f-c5kinf-0928','tb-f-c5kinf-0929b','tb-f-c5kinf-stitched']}
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def truth(value):return str(value).strip().lower() in ['1','1.0','true']
def csv_score(path):
    with path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    if not rows:return {'rows':0}
    keys=set(rows[0]);sink=next((s for s in ['correct','equiv','sound','reward','pass','solved'] if s in keys),None)
    required=[sink] if sink else []
    if 'submitted' in keys:required.append('submitted')
    if sink=='reward' and 'ran' in keys:required.append('ran')
    return {'rows':len(rows),'reportedPass':sum(all(truth(r[k]) for k in required) for r in rows) if sink else None,'sink':sink,'sha256':sha(path),'validityFieldPresent':'valid' in keys,'taskIds':[r.get('task_id') or r.get('id') or r.get('task') for r in rows]}
def run(name):
    home=ROOT/'runs'/name;out={'run':name,'sourceVersion':'Unknown: historical run lacks a verified launch source snapshot.','independentlyRegraded':False}
    db=home/'h2h.sqlite'
    if db.exists():
        wal=db.with_name(db.name+'-wal');params='?mode=ro' if wal.exists() and wal.stat().st_size else '?mode=ro&immutable=1'
        with sqlite3.connect(db.resolve().as_uri()+params,uri=True) as c:
            c.execute('pragma query_only=on')
            out['states']=dict(c.execute('select state,count(*) from task group by state'))
            out['tasks']=sum(out['states'].values());out['unfinished']=sum(n for s,n in out['states'].items() if s not in ['done','failed'])
            out['storedPass']=c.execute("select count(*) from task where json_valid(result) and json_extract(result,'$.pass')=1").fetchone()[0]
            out['storedPassWithTerminalState']=c.execute("select count(*) from task where state in ('done','failed') and json_valid(result) and json_extract(result,'$.pass')=1").fetchone()[0]
            out['resultWithExplicitValidity']=c.execute("select count(*) from task where json_valid(result) and json_type(result,'$.valid') is not null").fetchone()[0]
            out['taskIds']=[x[0] for x in c.execute('select id from task order by id')]
            out['declaredModels']=[{'agent':n,'apis':json.loads(a)} for n,a in c.execute('select name,apis from agent')]
            out['declaredLimits']=[list(x) for x in c.execute('select distinct max_dead_siblings,solve_seconds,max_searches,readable from task')]
            out['databaseSha256']=sha(db)
            if wal.exists() and wal.stat().st_size:out['walSha256']=sha(wal)
    else:out['databasePresent']=False
    for name in ['unaided.csv','ng.csv']:
        if (home/name).exists():out[name]=csv_score(home/name)
    return out
output={'createdAt':datetime.now(timezone.utc).isoformat(),'interpretation':'Stored task results and historical CSV counts, not newly certified benchmark scores. No old source version is inferred from the current HEAD. No selection, deletion or passing-outcome merge is performed.','benchmarks':{}}
for slug,names in GROUPS.items():
    records=[run(n) for n in names];output['benchmarks'][slug]=records
    print(json.dumps({'benchmark':slug,'runs':[{'run':r['run'],'tasks':r.get('tasks'),'storedPass':r.get('storedPass'),'unfinished':r.get('unfinished'),'csv':{k:r[k]['reportedPass'] for k in ['unaided.csv','ng.csv'] if k in r and 'reportedPass' in r[k]}} for r in records]}),flush=True)
(ROOT/'docs/phase1/legacy-inventory.json').write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8')
