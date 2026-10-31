"""Final local audit after the immutable deadline. Never calls a model."""
import json,hashlib,subprocess,sys,time,shutil
from datetime import datetime,timezone
from pathlib import Path
from decimal import Decimal
from fractions import Fraction
import psutil
ROOT=Path(__file__).resolve().parents[2]
RUN=Path(sys.argv[1]) if len(sys.argv)>1 else Path((ROOT/'data/rk-search/latest-run.txt').read_text().strip())
deadline=json.loads((RUN/'deadline.json').read_text())
authorization_path=RUN/'stop-authorization.json'
authorization=json.loads(authorization_path.read_text(encoding='utf-8')) if authorization_path.exists() else None
if time.time()<deadline['deadline_epoch'] and not (authorization and authorization.get('allow_early_finalization')):
    raise SystemExit('Before original deadline, explicit completion/stop authorization is required.')
for n,h in json.loads((RUN/'frozen-g.json').read_text())['files'].items():assert hashlib.sha256((RUN/n).read_bytes()).hexdigest()==h,n
final=RUN/'final';final.mkdir(exist_ok=True)
# Stop only verified process identities of this campaign, never shared WSL.
stops=[]
for name,item in json.loads((RUN/'process.json').read_text()).items():
    if not isinstance(item,dict) or 'pid' not in item:continue
    try:
        p=psutil.Process(item['pid'])
        if abs(p.create_time()-item['created'])>.5:continue
        children=p.children(recursive=True);p.kill()
        for c in children:
            try:c.kill()
            except psutil.Error:pass
        stops.append({'name':name,'pid':item['pid']})
    except psutil.Error:pass
(final/'stop-audit.json').write_text(json.dumps({'stopped':stops,'utc':datetime.now(timezone.utc).isoformat(),'linux':'Each isolated namespace has its own original-deadline supervisor.'},indent=2))
inputs=[RUN/'reference/baseline.json',RUN/'best-verified.candidate.json',RUN/'work/candidate.json']+list((RUN/'verified').glob('*.candidate.json'))
for p in (RUN/'work').rglob('*.json'):
    try:
        d=json.loads(p.read_text());
        if isinstance(d,dict) and d.get('schema')=='williamson-2n-v1':inputs.append(p)
    except (ValueError,OSError,UnicodeError):pass
seen=set();reports=[]
for p in inputs:
    if not p.exists():continue
    h=hashlib.sha256(p.read_bytes()).hexdigest()
    if h in seen:continue
    seen.add(h);snap=final/(h+'.candidate.json');shutil.copy2(p,snap)
    r=subprocess.run([sys.executable,str(RUN/'checker.py'),str(snap)],capture_output=True,text=True,check=True)
    audit=json.loads(r.stdout);(final/(h+'.audit.json')).write_text(json.dumps(audit,indent=2));reports.append((p,snap,audit))
valid=[x for x in reports if x[2]['valid']]
if not valid:raise RuntimeError('Even baseline failed independent final verification')
primary_minimum=min(Decimal(x[2]['error_norm']) for x in valid)
criteria=json.loads((RUN/'frozen-criteria.json').read_text())
equivalence_margin=Decimal(criteria['minimum_absolute_improvement'])
equivalent=[x for x in valid if Decimal(x[2]['error_norm'])-primary_minimum<=equivalence_margin]
def coefficient_magnitude(item):
    raw=json.loads(item[1].read_text())
    return max(abs(Fraction(v)) for v in raw['alpha']+raw['beta'])
# Differences below the frozen improvement threshold are not ranked as gains.
# Only within that primary-equivalent group prefer smaller 2N coefficients;
# held-out ODE outcomes never influence selection.
source,snap,best=min(equivalent,key=coefficient_magnitude)
shutil.copy2(snap,final/'selected.candidate.json')
exact_audit=None
accepted=RUN/'accepted-isolation-certificate.json'
if accepted.exists():
    prior=json.loads((RUN/'accepted-isolation-audit.json').read_text())
    assert hashlib.sha256(accepted.read_bytes()).hexdigest()==prior['certificate_sha256']
    assert hashlib.sha256((RUN/'audit_isolation.py').read_bytes()).hexdigest()==prior['auditor_sha256']
    shutil.copy2(accepted,final/'exact-isolation-certificate.json')
    subprocess.run([sys.executable,str(RUN/'audit_isolation.py'),str(accepted),str(snap),str(RUN/'reference/baseline-audit.json'),str(final/'exact-isolation-audit.json')],capture_output=True,text=True,check=True)
    exact_audit=json.loads((final/'exact-isolation-audit.json').read_text())
    shutil.copy2(RUN/'certified.candidate.json',final/'certified.candidate.json')
for label,p in [('baseline',RUN/'reference/baseline.json'),('selected',snap)]:
    r=subprocess.run([sys.executable,str(RUN/'benchmarks.py'),str(p),str(RUN/'reference/baseline-audit.json')],capture_output=True,text=True,check=True)
    (final/(label+'.held-out.json')).write_text(r.stdout)
base=json.loads((RUN/'reference/baseline-audit.json').read_text())
events=[]
for line in (RUN/'calls.jsonl').read_text().splitlines():
    try:events.append(json.loads(line))
    except ValueError:pass
dispatch=[e for e in events if e['event']=='dispatch'];responses=[e for e in events if e['event']=='response'];paid=[e for e in responses if (e.get('usage') or {}).get('cost') is not None]
usage={'requests':len(dispatch),'responses':len(responses),'recorded_cost_usd':sum(Decimal(str(e['usage']['cost'])) for e in paid),'unreceipted_request_ids':[e['id'] for e in dispatch if e['id'] not in {r['id'] for r in paid}],'prompt_tokens':sum((r.get('usage') or {}).get('prompt_tokens',0) for r in responses),'completion_tokens':sum((r.get('usage') or {}).get('completion_tokens',0) for r in responses),'note':'Missing receipt cost is unknown, not zero. Local abort cannot establish remote cancellation.'};usage['recorded_cost_usd']=str(usage['recorded_cost_usd'])
improvement=1-Decimal(best['error_norm'])/Decimal(base['principal_error_norm'])
summary={'finalized_utc':datetime.now(timezone.utc).isoformat(),'deadline':deadline,'baseline_norm':base['principal_error_norm'],'best_norm':best['error_norm'],'relative_improvement':str(improvement),'max_constraint_residual':best['max_constraint_residual'],'uncertainty_estimate':best['numerical_uncertainty_estimate'],'selected_source':str(source),'selected_sha256':best['sha256'],'checked_candidates':len(reports),'valid_candidates':len(valid),'selection':{'primary_minimum_norm':str(primary_minimum),'equivalence_margin':str(equivalence_margin),'equivalent_candidates':len(equivalent),'secondary_tiebreak':'smallest maximum absolute Williamson coefficient; no held-out feedback'},'usage':usage,'claim_boundary':'Improvement over the corrected paper example; no literature-best or framework superiority claim. Numerical construction unless separate exact certificate verified.'}
if exact_audit:
    summary['exact_certificate']={k:exact_audit[k] for k in ['valid_exact_isolation','saved_candidate_inside_isolating_box','attained_error_norm_exact','saved_coefficient_root_distance_bound_float_for_display','certificate_sha256','auditor_sha256','optimality_scope']}
    if exact_audit['valid_exact_isolation']:
        summary['claim_boundary']='The exact algebraic solution certified by the rational isolating box attains the global objective lower bound in the frozen feasible set only. No literature priority, broad method superiority, universal ODE speedup, or framework superiority claim.'
summary['early_completion_authorization']=authorization
(final/'summary.json').write_text(json.dumps(summary,indent=2))
lines=['# 本轮终检','',f"基线误差范数：{base['principal_error_norm'][:24]}",f"最终误差范数：{best['error_norm'][:24]}",f"相对下降：{float(improvement)*100:.8f}%",f"最大约束残差：{best['max_constraint_residual']}",f"已记录 API 费用（美元）：{usage['recorded_cost_usd']}",f"无费用回执的请求：{usage['unreceipted_request_ids']}",'','非线性 ODE 与内部放大结果见 baseline.held-out.json 和 selected.held-out.json。','这是对修正后论文示例的单次实验；不据此宣称新的最佳方法或 ObjRun 框架优势。']
(final/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
if exact_audit and exact_audit['valid_exact_isolation']:
    with (final/'REPORT.md').open('a',encoding='utf-8') as f:
        f.write('\n\n独立精确有理数区间审计证明，隔离盒内存在唯一满足全部冻结约束的代数解，其主误差范数恰为 639/45752，达到本轮固定稳定多项式下的全局下界。保存的小数系数与该精确解的距离上界见 exact-isolation-audit.json；这不构成更广泛的方法排名或文献优先权结论。\n')
print(json.dumps(summary,indent=2))
