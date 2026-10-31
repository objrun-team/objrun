"""Post-deadline independent verification/accounting, never launch a solver."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from checker import cross_check

run=Path(sys.argv[1]).resolve()
out=run/'final'; out.mkdir(exist_ok=True)
reports=[]
paths=[run/'best-verified.txt',run/'work/candidate.txt',*sorted((run/'work/candidates').glob('*.txt'))]
seen=set()
for path in paths:
    if not path.is_file(): continue
    raw=path.read_bytes(); digest=hashlib.sha256(raw).hexdigest()
    if digest in seen: continue
    seen.add(digest)
    snap=out/(digest+'.txt'); snap.write_bytes(raw)
    r=cross_check(snap)
    r.update(original_path=str(path),artifact=str(snap),raw_sha256=digest,checked_utc=datetime.now(timezone.utc).isoformat())
    (out/(digest+'.json')).write_text(json.dumps(r,indent=2))
    reports.append(r)
valid=[r for r in reports if r['valid']]
best=min(valid,key=lambda r:r['size']) if valid else None
events=[]
if (run/'calls.jsonl').exists():
    for line in (run/'calls.jsonl').read_text().splitlines():
        try: events.append(json.loads(line))
        except ValueError: pass
sent={r['id']:r for r in events if r['event']=='dispatch'}
receipts={r['id']:r for r in events if r['event']=='response'}
usage=[r.get('usage') or {} for r in receipts.values()]
unknown=[i for i in sent if i not in receipts or 'cost' not in (receipts[i].get('usage') or {})]
prep=json.loads((run/'reference/model-probe.receipt.json').read_text())
summary={'finished_review_utc':datetime.now(timezone.utc).isoformat(),
    'deadline':json.loads((run/'deadline.json').read_text()), 'parameters':{'t':3,'k':24,'v':2},
    'baseline_N':21,'final_N':best['size'] if best else None,'improved_reference':bool(best and best['size']<21),
    'best':best,'final_arrays_checked':len(reports),
    'usage':{'formal_requests':len(sent),'responses':len(receipts),
        'prompt_tokens':sum(u.get('prompt_tokens') or 0 for u in usage),
        'completion_tokens':sum(u.get('completion_tokens') or 0 for u in usage),
        'formal_receipted_usd':sum(u.get('cost') or 0 for u in usage),
        'preparation_receipted_usd':(prep.get('usage') or {}).get('cost'),
        'unconfirmed_request_ids':unknown,
        'unconfirmed_cost':'Unknown, not zero. Locally aborted requests may still incur remote charges.' if unknown else 'All dispatched requests have cost receipts.'},
    'claims':{'valid_construction':best is not None,'improved_specified_reference':bool(best and best['size']<21),
        'current_world_record':'Not established; refresh sources before any record claim.',
        'optimality_proof':False,'causal_attribution':'One uncontrolled run cannot attribute success to ObjRun. Model decisions, algorithm execution and external constructions are logged separately.'}}
(run/'final-report.json').write_text(json.dumps(summary,indent=2))
text=f'''# Covering-array search final audit

Parameters: CA(N;3,24,2). Frozen reference: 21 rows.
Final independently verified N: {summary['final_N']}.
Improved reference: {summary['improved_reference']}.

Formal API requests: {len(sent)}; prompt tokens: {summary['usage']['prompt_tokens']}; completion tokens: {summary['usage']['completion_tokens']}.
Receipted formal cost: ${summary['usage']['formal_receipted_usd']:.8f}; preparation cost: ${summary['usage']['preparation_receipted_usd'] or 0:.8f}.
Requests with unconfirmed cost: {unknown}.

Detailed immutable arrays and two independent checker reports: final/.
No global-record or optimality claim is made. Failure to improve is not a non-existence proof.
This single run does not identify the causal contribution of ObjRun; inspect model/tool/source trajectories.
'''
(run/'FINAL-REPORT.md').write_text(text)
print(json.dumps({'final_N':summary['final_N'],'improved':summary['improved_reference'],'report':str(run/'final-report.json'),'usage':summary['usage']}))
