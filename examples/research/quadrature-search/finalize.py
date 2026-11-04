"""Post-deadline audit, snapshot, fee accounting. Does not launch model or search."""
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path
import mpmath as mp

ROOT=Path(__file__).resolve().parents[3]
RUN=Path(sys.argv[1]) if len(sys.argv)>1 else Path((ROOT/'data/quadrature-search/latest-run.txt').read_text().strip())
deadline=json.loads((RUN/'deadline.json').read_text())
if time.time()<deadline['deadline_epoch']:
    raise SystemExit('Refusing to finalize an ongoing five-hour window.')
frozen=json.loads((RUN/'frozen-g.json').read_text())
for name,expected in frozen['files'].items():
    assert hashlib.sha256((RUN/name).read_bytes()).hexdigest()==expected,('frozen G changed',name)
final=RUN/'final';final.mkdir(exist_ok=True)
inputs=[('baseline',RUN/'reference/diallo-prism-q7-n36.json'),('best',RUN/'best-verified.candidate.json'),('last-checkpoint',RUN/'work/candidate.json')]
seen_paths={p.resolve() for _,p in inputs}
for saved in sorted((RUN/'work').rglob('*.json')):
    if saved.resolve() in seen_paths: continue
    try:
        content=json.loads(saved.read_text(encoding='utf-8-sig'))
        if isinstance(content,dict) and content.get('domain')=='prism' and isinstance(content.get('nodes'),list):
            tag=hashlib.sha256(saved.read_bytes()).hexdigest()[:16]
            inputs.append(('saved-'+saved.stem+'-'+tag,saved))
    except (ValueError,UnicodeError,OSError): pass
reports=[]
for label,path in inputs:
    if not path.exists():continue
    snapshot=final/(label+'.candidate.json');snapshot.write_bytes(path.read_bytes())
    proc=subprocess.run([sys.executable,str(RUN/'checker.py'),str(snapshot),'--threshold','36','--independent'],capture_output=True,text=True,check=True)
    report=json.loads(proc.stdout)
    (final/(label+'.audit.json')).write_text(json.dumps(report,indent=2))
    reports.append((label,snapshot,report))
valid=[r for r in reports if r[2]['valid']]
if not valid:raise RuntimeError('No valid final artifact, including baseline')
label,path,best=min(valid,key=lambda x:x[2]['size'])
# Additional high-precision audit of the whole barycentric polynomial basis,
# including redundant third barycentric coordinate powers; 330 moments through 7.
mp.mp.dps=160
raw=json.loads(path.read_text())
nodes=[tuple(mp.mpf(s) for s in r) for r in raw['nodes']]
redundant=[]
for a in range(8):
    for b in range(8-a):
        for d in range(8-a-b):
            for c in range(8-a-b-d):
                exact=mp.mpf(0) if c%2 else 8*mp.factorial(a)*mp.factorial(b)*mp.factorial(d)/(mp.factorial(a+b+d+2)*(c+1))
                value=mp.fsum(w*((x+1)/2)**a*((y+1)/2)**b*(-(x+y)/2)**d*z**c for x,y,z,w in nodes)
                redundant.append({'powers_u_v_t_z':[a,b,d,c],'absolute_error':mp.nstr(abs(value-exact),50)})
max_error=max(mp.mpf(r['absolute_error']) for r in redundant)
assert max_error<=mp.mpf('1e-40')
(final/'redundant-160digit-audit.json').write_text(json.dumps({'precision_digits':160,'moment_count':len(redundant),'max_error':mp.nstr(max_error,50),'moments':redundant},indent=2))
prior=json.loads((RUN/'comparison/prior-prism-q7-n35.json').read_text())
prior_nodes=[tuple(mp.mpf(s) for s in r) for r in prior['nodes']]
same=None
if len(nodes)==len(prior_nodes):
    match_error=max(min(max(abs(x-y) for x,y in zip(a,b)) for b in prior_nodes) for a in nodes)
    same={'same_rule_to_1e-30':bool(match_error<mp.mpf('1e-30')),'max_weighted_node_matching_error':mp.nstr(match_error,50),'note':'Both rules already invariant under full prescribed group. Direct weighted matching is sufficient to identify equality in this fixed frame; nonmatch alone is not proof of distinctness under all conceivable affine automorphisms.'}
events=[]
if (RUN/'calls.jsonl').exists():
    for line in (RUN/'calls.jsonl').read_text().splitlines():
        try:events.append(json.loads(line))
        except ValueError:pass
dispatch=[e for e in events if e['event']=='dispatch']
responses=[e for e in events if e['event']=='response']
paid=[e for e in responses if (e.get('usage') or {}).get('cost') is not None]
unknown=[e['id'] for e in dispatch if e['id'] not in {x['id'] for x in paid}]
probe=json.loads((RUN/'reference/probe.response.json').read_text())
usage={'formal_requests':len(dispatch),'formal_responses':len(responses),
       'formal_receipt_cost_usd':sum(e['usage']['cost'] for e in paid),
       'preflight_receipt_cost_usd':probe.get('usage',{}).get('cost'),
       'prompt_tokens':sum((e.get('usage') or {}).get('prompt_tokens',0) for e in responses),
       'completion_tokens':sum((e.get('usage') or {}).get('completion_tokens',0) for e in responses),
       'reasoning_tokens':sum((e.get('usage') or {}).get('completion_tokens_details',{}).get('reasoning_tokens',0) for e in responses),
       'unconfirmed_fee_request_ids':unknown,
       'fee_note':'Missing or interrupted receipt cost is unknown, not zero. Local cancellation does not prove provider-side cancellation. Costs here use completion receipts; generation reconciliation, if present, is a separate nonadditive audit.'}
summary={'finalized_utc':datetime.now(timezone.utc).isoformat(),'deadline':deadline,
         'baseline_nodes':36,'checked_prior_nodes':35,'best_nodes':best['size'],
         'saved_vs_specified_paper':36-best['size'],'saved_vs_checked_prior':35-best['size'],
         'chosen_snapshot':str(path),'candidate_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
         'cartesian_max_error':best['max_moment_error'],'independent_max_error':best['independent']['max_moment_error'],
         'redundant_160digit_max_error':mp.nstr(max_error,50),'evidence':'Numerical construction only; no rigorous exactness certificate or record claim; single-run outcome does not establish causal ObjRun benefit.',
         'comparison_to_prior35':same,'usage':usage}
(final/'summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
