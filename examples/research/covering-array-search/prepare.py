import csv
import difflib
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from checker import check_text, cross_check

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).resolve().parent
BASE = ROOT/'data/covering-array-search'
PREP = BASE/'preparation'
RUN = BASE/('run-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
RUN.mkdir(parents=True)
for name in ['work/history', 'work/candidates', 'reference', 'verified', 'jobs', 'requests', 'engine', 'runtime', 'tests']:
    (RUN/name).mkdir(parents=True)
for name in ['checker.py', 'ca_verify.py', 'guard.py', 'GOAL.md', 'run.ts', 'supervise.py', 'monitor.py', 'finalize.py']:
    shutil.copy2(SCRIPTS/name, RUN/name)
for name in ['openrouter-model.json', 'model-probe.request.json', 'model-probe.response.json', 'model-probe.receipt.json']:
    shutil.copy2(PREP/name, RUN/'reference'/name)
catools = PREP/'ca-tools'
for name in ['CA_21_3_25_2.txt', 'CA_20_3_23_2.txt']:
    shutil.copy2(catools/'table/arrays'/name, RUN/'reference'/name)
full_text = (RUN/'reference/CA_21_3_25_2.txt').read_text()
assert hashlib.sha256(full_text.encode()).hexdigest() == '145ef3e7aeb8e01917224e4c0a1bf95ef4c16256b276ef039b9f5805e9e10670'
baseline = '\n'.join(' '.join(line.split()[:24]) for line in full_text.splitlines())+'\n'
for name in ['reference/baseline.txt', 'work/candidate.txt', 'best-verified.txt']:
    (RUN/name).write_text(baseline, encoding='utf-8')
shutil.copy2(SCRIPTS/'GOAL.md', RUN/'reference/GOAL.md')
report = cross_check(RUN/'reference/baseline.txt')
assert report['valid'] and report['implementations_agree'] and report['size'] == 21
report.update(source='First 24 columns of public CA_21_3_25_2.txt', artifact=str(RUN/'reference/baseline.txt'))
(RUN/'baseline-audit.json').write_text(json.dumps(report, indent=2))
(RUN/'best-verified.json').write_text(json.dumps(report, indent=2))
tests = []
variants = {'deleted_row': '\n'.join(baseline.splitlines()[1:])+'\n',
            'destroyed_column': '\n'.join('0 '+' '.join(l.split()[1:]) for l in baseline.splitlines())+'\n',
            'wrong_width': '\n'.join(' '.join(l.split()[:-1]) for l in baseline.splitlines())+'\n',
            'wildcard': baseline.replace('0', '*', 1),
            'bad_symbol': baseline.replace('0', '2', 1),
            'empty': ''}
for name, text in variants.items():
    p = RUN/'tests'/(name+'.txt'); p.write_text(text)
    r = cross_check(p)
    assert not r['valid'], (name, r)
    if name in ['deleted_row', 'destroyed_column']:
        assert r['implementations_agree'] and r['missing_count'] > 0
    tests.append({'name':name, **r})
# A single omitted interaction, even if all others pass, must be rejected.
rows = [list(map(int,l.split())) for l in baseline.splitlines()]
for row in rows:
    if row[:3] == [0,0,0]: row[0] = 1
p = RUN/'tests/removed_triple_000.txt'
p.write_text('\n'.join(' '.join(map(str,r)) for r in rows)+'\n')
r = cross_check(p)
assert not r['valid'] and r['implementations_agree'] and any(x['columns_zero_based']==[0,1,2] and x['symbols']==[0,0,0] for x in r['missing'])
tests.append({'name':'removed_triple_000', **r})
(RUN/'tests/results.json').write_text(json.dumps(tests,indent=2))
for name in ['ca_table.csv','MANIFEST.csv','README.md','VERIFICATION_LOG.md']:
    shutil.copy2(catools/'table'/name, RUN/'reference'/('ca-tools-'+name))
for name in ['ColbournTables.md','README.md']:
    shutil.copy2(PREP/'CAs'/name, RUN/'reference'/('CAs-'+name))
table = list(csv.DictReader((catools/'table/ca_table.csv').open()))
selected = [r for r in table if r['t']=='3' and r['v']=='2' and int(r['k'])>=24 and r['tier'] in ['VERIFIED','CITED']]
assert min(int(r['N']) for r in selected) == 21
provenance = {'retrieved_utc':datetime.now(timezone.utc).isoformat(), 'selected':{'t':3,'k':24,'v':2,'baseline_N':21,'initial_target_N_max':20},
    'source_array_sha256':hashlib.sha256(full_text.encode()).hexdigest(),
    'transformation':'Take columns 0..23 in original order; all 21 rows unchanged.',
    'baseline_sha256':report['sha256'], 'live_table_rows_at_best':[r for r in selected if int(r['N'])==21],
    'original_sources':['https://github.com/ugroempi/CAs','https://github.com/ugroempi/CAs/blob/main/ColbournTables.md','https://github.com/chrispbsmolen/ca-tools','https://arxiv.org/html/2510.17596'],
    'scope':'Current checked table upper bound, not a claim of exhaustive literature coverage. No optimality proof found for (3,24,2).',
    'excluded':'All binary strength-2; Hiess-Kampel (3,k,2), k=17..20 and (4,18,2); other known-optimal small cases.',
    'selection_reason':'Binary strength 3; 24 columns; complete accessible reference; 16192 required interactions; near plateau edge; deletions and 23-column extension both available; compatible with five-hour search.',
    'rejected_alternatives':'t=2,v=3,k=11..20 are optimal by known classification; t=4 has more interactions; t=3,v=3 adds alphabet/row complexity.',
    'repositories':{d.name:subprocess.check_output(['git','log','-1','--format=%H %cI'],cwd=d,text=True).strip() for d in [catools,PREP/'CAs']}}
(RUN/'provenance.json').write_text(json.dumps(provenance,indent=2))
shutil.copytree(ROOT/'app/src', RUN/'runtime/src')
shutil.copy2(ROOT/'app/package.json',RUN/'runtime/package.json')
subprocess.run(['cmd','/c','mklink','/J',str(RUN/'runtime/node_modules'),str(ROOT/'app/node_modules')],check=True,capture_output=True)
# Dedicated snapshot removes count limits, rather than using a large enforced cap.
changes = {
 'llm/index.ts': [
  ('export const HARD_WALL_MS = 900_000;', 'export const HARD_WALL_MS = 18_000_000;'),
  ('maxOutputTokens: knobs.maxTokens,', '// Wall-clock-only campaign: omit maxOutputTokens.'),
  ('if (out.finishReason !== "length" || round >= knobs.continueTimes) break;', 'if (out.finishReason !== "length") break;'),
  ('`${x.cycle} ${x.used}/${x.cap}`', '`${x.cycle} ${x.used}/unlimited`')],
 'engine/loop.ts': [
  ('const cap = Number(task?.max_dead_siblings ?? 3);','const cap = Infinity; // This snapshot is wall-clock-only.'),
  ('if (used >= Number(cap.max_units)) {','if (false) { // No campaign execution-unit cap.')],
 'tree/dfs.ts': [
  ('return nodes.filter((n) => n.cycle === cycle && Number(n.node) === node).length >= Number(cap.max_units);','return false; // No campaign execution-unit cap.'),
  ('if (tried >= Number(a.task.max_dead_siblings ?? 3)) return { to: null, status } satisfies Said;','// No campaign restart-count cap.')],
 'objective/tool.ts': [
  ('const here = numberOf(sealed.checksOf(at.task), 5);','const here = Infinity; // No campaign verification-count cap.')]
}
patches=[]
for rel,replacements in changes.items():
    p=RUN/'runtime/src'/rel; old=p.read_text(encoding='utf-8'); new=old
    for a,b in replacements:
        assert new.count(a)==1,(rel,a,new.count(a)); new=new.replace(a,b)
    p.write_text(new,encoding='utf-8')
    patches.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='stock/'+rel,tofile='runtime/'+rel))
(RUN/'runtime-changes.patch').write_text(''.join(patches),encoding='utf-8')
files={str(p.relative_to(RUN/'runtime/src')):hashlib.sha256(p.read_bytes()).hexdigest() for p in (RUN/'runtime/src').rglob('*') if p.is_file()}
manifest={'repository_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
          'snapshot_hashes':files,'changes':'runtime-changes.patch; original application source untouched',
          'request_policy':'No max_tokens/max_completion_tokens/max_output_tokens, no price ceiling, no alternate model.',
          'count_fields':'Finite-integer schema placeholders are not enforced in this dedicated snapshot; all count guards disabled.',
          'python':sys.executable,'linux_env':'/home/imontlaji/.local/share/objrun-ca-20261030-env'}
(RUN/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2))
frozen={name:hashlib.sha256((RUN/name).read_bytes()).hexdigest() for name in ['checker.py','ca_verify.py','GOAL.md','run.ts','guard.py','supervise.py','finalize.py']}
(RUN/'trusted-hashes.json').write_text(json.dumps(frozen,indent=2))
env = subprocess.check_output(['wsl','-d','Ubuntu','--',manifest['linux_env']+'/bin/python','-m','pip','freeze'],text=True)
(RUN/'requirements-lock.txt').write_text(env)
(BASE/'latest-run.txt').write_text(str(RUN),encoding='utf-8')
print(json.dumps({'run':str(RUN),'baseline':report['size'],'sha256':report['sha256'],'required_interactions':report['required_interactions'],'tests':len(tests),'all_negative_tests_rejected':True}))
