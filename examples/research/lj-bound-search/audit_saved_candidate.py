"""Audit one model-documented candidate, without doing parameter search.
Parameters are extracted verbatim from saved model job 13, independently
corroborated by its job 14; the host supplies no new parameter values.
"""
from pathlib import Path
import json,sys,subprocess,hashlib,datetime,time
ROOT=Path(__file__).resolve().parents[3]
run=Path((ROOT/'data/lj-bound-search/latest-run.txt').read_text().strip())
deadline=json.loads((run/'deadline.json').read_text())
assert time.time()<deadline['deadline_epoch']
assert not (run/'primary-success.json').exists()
source=run/'jobs/13.log'
row=[l.split() for l in source.read_text(encoding='utf-8').splitlines() if l.startswith('0.694 ')][0]
assert row[0]=='0.694' and row[1]=='0.750' and float(row[4])<0
obj={'method':'ball_average_v1','a':'0.684','b':row[0],'cutoff':row[1],'particle_minus_energy':0,
     'proof_path':'host-instantiated-model-candidate-proof.md','seed':'deterministic grid, no random draws',
     'provenance':{'parameter_source':'model jobs/13.log row b=0.694 and jobs/14.log b=0.694 L=0.75','search_program':'work/scan2.py and work/pmin.py','source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'host_action':'Extract and independently certify already logged candidate; no further search.','proof_author':'host frozen analytic template instantiated at model-selected parameters'}}
raw=json.dumps(obj,indent=2);sha=hashlib.sha256(raw.encode()).hexdigest()
p=run/'verified'/(sha+'.candidate.json');p.write_text(raw,encoding='utf-8')
cert=run/'verified'/(sha+'.certificate.json')
first=subprocess.run([sys.executable,str(run/'checker/check.py'),str(p),str(cert)],capture_output=True,text=True)
(run/'verified'/(sha+'.checker.stdout.log')).write_text(first.stdout)
(run/'verified'/(sha+'.checker.stderr.log')).write_text(first.stderr)
report=json.loads(first.stdout);assert report['valid'] and report['improved'],report
second=subprocess.run([sys.executable,str(run/'checker/replay.py'),str(cert)],capture_output=True,text=True)
(run/'verified'/(sha+'.replay.stdout.log')).write_text(second.stdout)
(run/'verified'/(sha+'.replay.stderr.log')).write_text(second.stderr)
replay=json.loads(second.stdout);assert replay['independent_replay_passed'],replay
for n,h in json.loads((run/'frozen-g.json').read_text())['files'].items():assert hashlib.sha256((run/n).read_bytes()).hexdigest()==h,n
assert time.time()<deadline['deadline_epoch'],'do not declare predeadline success after expiration'
proof=f'''# Verified bound from the model's saved parameter search

For every N>=2 and every global minimizer in R3 of the specified pair energy,

r_min >= (347/500)*2^(1/6) = {report['c_new_decimal']}...

This is greater than frozen c_ref~.768420525585496, including the unrounded
implication of the old proof. It is less than1. The >=1 and >1 conjectures remain
unresolved. The argument actually excludes equality at this new lower bound.

Insert a0=171/250, b=347/500, L=3/4 and q=0 into the following full frozen
proof. The exact ball-average domain certificate has {report['cover_leaves']}
leaves. The smallest Bernstein coefficient is positive. The final contradiction
2*b^6+K_upper*b^9-1 is strictly negative. All comparisons use rational arithmetic.
See the adjacent certificate JSON for complete exact coefficients, bounds,
coverage, radical enclosures and verification outputs.

Provenance: fixed DeepSeek model wrote scan2.py and pmin.py and explicitly
saved this pair in jobs13/14. Host selected this already documented successful
numeric candidate for independent verification while the model was still
refining parameters. The host authored the pre-frozen proof/checkers and this
instantiation. This is a combined host/model result, not an unaided model proof.

'''+(run/'PROOF_FAMILY.md').read_text(encoding='utf-8')
(run/'proof/PROOF.md').write_text(proof,encoding='utf-8')
(run/'verified'/(sha+'.host-proof.md')).write_text(proof,encoding='utf-8')
report.update(artifact=str(p),raw_sha256=sha,certificate=str(cert),independent_replay=replay,proof_saved=True,proof_author='host with model-discovered numerical parameters',parameter_source='model jobs13/14',checked_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
(run/'verified'/(sha+'.json')).write_text(json.dumps(report,indent=2))
(run/'best-verified.json').write_text(json.dumps(report,indent=2))
success={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'report':report,'authorization':'User explicitly requires priority immediate early stop after any independent main-goal verification','analytic_basis':'Host audited frozen full proof; exact main checker and independently reconstructed rational polynomial/tail replay both passed.','host_monitor_action':'Certified saved model candidate before its finer parameter sweep; no need to wait for15-minute monitor.'}
# Guard observes this marker and terminates only owned requests/processes.
(run/'primary-success.json.tmp').write_text(json.dumps(success,indent=2))
(run/'primary-success.json.tmp').replace(run/'primary-success.json')
print(json.dumps({'main_goal_success':True,'c_new':report['c_new_decimal'],'c_new_exact':report['c_new_expression'],'cover_leaves':report['cover_leaves'],'independent_replay':True,'success_utc':success['utc']}))
