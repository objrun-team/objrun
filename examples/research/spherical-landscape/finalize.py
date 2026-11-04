import os
os.environ['OPENBLAS_NUM_THREADS']='1'
import json,sys,time,subprocess,hashlib
from pathlib import Path
from datetime import datetime,timezone
from checker import check,mp_values
run=Path(sys.argv[1]).resolve();end=json.loads((run/'deadline.json').read_text())
assert time.time()>=end['deadline_epoch'],'Cannot finalize before original deadline'
final=run/'final';final.mkdir(exist_ok=True)
subprocess.run([sys.executable,str(run/'audit_loop.py'),str(run),'--once'],check=True)
events=[]
if (run/'calls.jsonl').exists():
    for line in (run/'calls.jsonl').read_text().splitlines():
        try:events.append(json.loads(line))
        except ValueError:pass
dispatch=[e for e in events if e['event']=='dispatch'];responses=[e for e in events if e['event']=='response']
receipts=[e for e in responses if (e.get('usage') or {}).get('cost') is not None]
usage={'requests':len(dispatch),'responses':len(responses),'receipt_cost_usd':sum(e['usage']['cost'] for e in receipts),'prompt_tokens':sum((e.get('usage') or {}).get('prompt_tokens',0) for e in responses),'completion_tokens':sum((e.get('usage') or {}).get('completion_tokens',0) for e in responses),'without_cost_receipt':[e['id'] for e in dispatch if e['id'] not in {r['id'] for r in receipts}],'without_response':[e['id'] for e in dispatch if e['id'] not in {r['id'] for r in responses}],'note':'Unreceipted requests have unknown charges, not zero. Local cancellation does not establish provider-side cancellation.'}
reports=[]
for p in (run/'verified').glob('*.json'):
    if p.name.endswith('.candidate.json'):continue
    try:
        r=json.loads(p.read_text());reports.append((p,r))
    except ValueError:pass
strict=[(p,r) for p,r in reports if r.get('strict_numerical_candidate')]
interesting=[(p,r) for p,r in reports if r.get('energy',0)>1e-8]
selected=max(strict or interesting,key=lambda pr:pr[1]['quotient_spectrum'][0],default=None)
last=[]
if selected:
    p,r=selected;candidate=p.with_name(p.stem+'.candidate.json')
    if candidate.exists():
        rr=check(candidate,final/'selected-final-check.json',run/'baseline-audit.json');raw=json.loads(candidate.read_text());hp=mp_values(raw['vectors'],160)
        (final/'selected-160digit-check.json').write_text(json.dumps(hp,indent=2));(final/'selected.candidate.json').write_bytes(candidate.read_bytes());last.append({'source':str(candidate),'energy':rr['energy'],'gradient_norm':rr['gradient_norm'],'quotient_min':rr['quotient_spectrum'][0],'near_zero':rr['near_zero_count'],'evidence_level':rr['evidence_level']})
lastpath=run/'work/candidate.json'
if lastpath.exists():check(lastpath,final/'last-complete-check.json',run/'baseline-audit.json')
result={'finished_utc':datetime.now(timezone.utc).isoformat(),'deadline':end,'model':'deepseek/deepseek-v4.1-flash','independently_checked_configurations':len(reports),'strict_numerical_count':len(strict),'selected':last,'usage':usage,'proved_conclusions':['Fixed normalization c=1/16 and constant 36 follows from the paper formula.'],'numerical_evidence':last,'unresolved':['No nonexistence conclusion follows from any number of unsuccessful searches.','Formal certificates require independent mathematical review and successful rigorous verification; floating point checks alone prove no local minimum.'],'proof_artifacts':[str(p) for p in (run/'work').rglob('*certif*.json')]}
proof=run/'proof'
if (proof/'manifest.json').exists():
    manifest=json.loads((proof/'manifest.json').read_text())
    for name,digest in manifest['files'].items():assert hashlib.sha256((proof/name).read_bytes()).hexdigest()==digest,'Proof artifact changed: '+name
    subprocess.run([sys.executable,str(proof/'verify_certificate.py'),str(proof/'certificate.witness.json'),str(proof/'author-reference.json'),'--output',str(final/'certificate-final-verification.json')],check=True)
    result['certificate_final_check']=json.loads((final/'certificate-final-verification.json').read_text())
    result['proved_conclusions'].append('An exactly feasible non-global local minimum exists within the certified dyadic radius 2^-180 of the saved 183-variable KKT center. It is strict modulo common O(6) rotations; all 105 transverse directions have positive Hessian. An explicitly normalized author configuration has rigorously lower energy.')
    result['proof_artifacts']=[str(proof/'manifest.json'),str(proof/'PROOF.md'),str(proof/'certificate.witness.json'),str(final/'certificate-final-verification.json')]
    check(proof/'refined.json',final/'certified-center-check.json',run/'baseline-audit.json')
    result['unresolved']=['This experiment does not classify all local minima or all critical manifolds.','No nonexistence conclusion follows from unsuccessful searches.','No causal advantage of ObjRun is established by one experiment.']
proof2=run/'proof-basin2'
if (proof2/'manifest.json').exists():
    manifest=json.loads((proof2/'manifest.json').read_text())
    for name,digest in manifest['files'].items():assert hashlib.sha256((proof2/name).read_bytes()).hexdigest()==digest,'Second proof artifact changed: '+name
    subprocess.run([sys.executable,str(proof2/'verify_cholesky_certificate.py'),str(proof2/'certificate.witness.json'),str(proof2/'author-reference.json'),'--output',str(final/'certificate-basin2-final-verification.json')],check=True)
    result['second_certificate_final_check']=json.loads((final/'certificate-basin2-final-verification.json').read_text())
    result['proved_conclusions'].append('A second non-global local minimum exists near the second certified KKT center, with energy about 0.13725993138656847 and positive full 105-dimensional transverse Hessian. Its energy interval is disjoint from the first, proving inequivalence under all energy-preserving symmetries.')
    result['proof_artifacts'] += [str(proof2/'manifest.json'),str(proof2/'PROOF.md'),str(final/'certificate-basin2-final-verification.json')]
    check(proof2/'refined.json',final/'certified-basin2-center-check.json',run/'baseline-audit.json')
additional=[]
for package in sorted(run.glob('proof-basin*')):
    if package==proof2 or not (package/'manifest.json').exists():continue
    manifest=json.loads((package/'manifest.json').read_text())
    for name,digest in manifest['files'].items():assert hashlib.sha256((package/name).read_bytes()).hexdigest()==digest,'Additional proof artifact changed: '+name
    output=final/(package.name+'-final-verification.json')
    subprocess.run([sys.executable,str(package/'verify_cholesky_certificate.py'),str(package/'certificate.witness.json'),str(package/'author-reference.json'),'--output',str(output)],check=True)
    verified=json.loads(output.read_text());additional.append({'package':str(package),'verification':verified})
    result['proved_conclusions'].append('Another non-global local minimum is rigorously certified by '+package.name+' with energy interval '+verified['energy']+'.')
    result['proof_artifacts'] += [str(package/'manifest.json'),str(package/'PROOF.md'),str(output)]
    coordinates=package/'refined.json' if (package/'refined.json').exists() else package/'certificate.refined.json'
    check(coordinates,final/(package.name+'-center-check.json'),run/'baseline-audit.json')
result['additional_certificates']=additional
intervals=[]
for field in ['certificate_final_check','second_certificate_final_check']:
    if field in result:intervals.append(result[field]['energy'])
intervals += [item['verification']['energy'] for item in additional]
if intervals:
    from flint import arb,ctx
    ctx.dps=220;balls=[arb(value.strip('[]')) for value in intervals]
    result['certified_minima_count']=len(balls)
    result['certified_energy_intervals_pairwise_disjoint']=all(bool(balls[i]<balls[j] or balls[j]<balls[i]) for i in range(len(balls)) for j in range(i))
(final/'summary.json').write_text(json.dumps(result,indent=2));(final/'usage.json').write_text(json.dumps(usage,indent=2))
print(json.dumps(result,indent=2))
