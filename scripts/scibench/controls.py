"""No-model tests against the pinned upstream scoring functions and real HTTP boundary."""
import contextlib
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'package'))
from grade import Scorer
scorer = Scorer(ROOT / 'package/vendor')
book = json.loads((ROOT / 'data/private-tasks.json').read_text(encoding='utf-8'))
checks = []
def check(name, value):
    checks.append({'name': name, 'passed': bool(value)})
    if not value:
        raise AssertionError(name)

for row in book:
    good = scorer.reference_candidate(row)
    check('reference:' + row['id'], scorer.judge(good, row)['passed'])
    target, _ = scorer.target(row)
    wrong = r'\boxed{0}' if float(target) != 0 else r'\boxed{1}'
    check('wrong:' + row['id'], not scorer.judge(wrong, row)['passed'])
    public = scorer.public(row)
    check('whitelist:' + row['id'], set(public) == {'id', 'source', 'prompt'})

synthetic = {'id': 'control', 'sourceFile': 'fixture', 'problem_text': 'Compute.', 'unit': 'm', 'answer_number': '100'}
for answer in ['100', '95', '94.999', '105', '105.264', '105.2649', '-100', '0', '1,00', '100 m', 'NaN', 'inf']:
    text = r'\boxed{' + answer + '}'
    expected = bool(scorer.f['equiv'](answer, '100', 'm'))
    check('upstream-differential:' + answer, scorer.judge(text, synthetic)['passed'] == expected)
for value in ['-100', '0', '1e-20']:
    row = {**synthetic, 'answer_number': value}
    check('sign-zero-small:' + value, scorer.judge(r'\boxed{' + value + '}', row)['passed'])
for text in ['', r'\boxed{NaN}', r'\boxed{inf}', r'\boxed{100', r'\boxed{abc}']:
    check('invalid-format:' + text, not scorer.judge(text, synthetic)['parsed'])
check('last-boxed', scorer.judge(r'\boxed{1} then \boxed{100}', synthetic)['passed'])
scientific = {**synthetic, 'answer_number': '2.2', 'unit': r'$10^{-31}$ m'}
check('scientific-scale', scorer.judge(r'\boxed{2.2\times 10^{-31}}', scientific)['passed'])
check('scientific-unit-sanitized', '10^' not in scorer.public(scientific)['prompt'])
check('scientific-wrong-scale', not scorer.judge(r'\boxed{2.2}', scientific)['passed'])

env = {k: os.environ[k] for k in ['PATH', 'SYSTEMROOT', 'WINDIR'] if k in os.environ}
env.update(PYTHONUTF8='1', SCIBENCH_GRADER_TOKEN='control-token')
proc = subprocess.Popen([sys.executable, str(ROOT / 'package/stand.py'), '--home', str(ROOT / 'data'), '--vendor', str(ROOT / 'package/vendor')], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    first = proc.stdout.readline()
    if not first:
        raise RuntimeError('ScoringServiceStartup: ' + proc.stderr.read())
    info = json.loads(first)
    base = 'http://127.0.0.1:' + str(info['port'])
    def request(path, data=None, token='control-token'):
        req = urllib.request.Request(base + path, json.dumps(data).encode() if data is not None else None,
                                     {'Content-Type': 'application/json', 'X-SciBench-Token': token})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)
    code, public = request('/problems')
    check('http-public-whitelist', code == 200 and len(public) == 437 and all(set(r) == {'id', 'source', 'prompt'} for r in public))
    row = book[-1]
    body = {'input': {'task': {'id': 'namespace/' + row['id']}, 'result': scorer.reference_candidate(row)}}
    code, value = request('/accept', body)
    check('http-reference-and-candidate-identity', code == 200 and value['passed'] and value['candidateSha256'] == hashlib.sha256(body['input']['result'].encode()).hexdigest())
    check('http-private-token', request('/accept', body, 'wrong-token')[0] == 403)
    check('http-unknown-task', request('/accept', {'input': {'task': {'id': 'missing'}, 'result': 'x'}})[0] == 422)
    check('http-unknown-endpoint', request('/answer', body)[0] == 404)
    body['input']['result'] = ''
    _, rejected = request('/correct', body)
    check('http-rejection-no-gold-diagnostics', rejected == {'value': False, 'note': ''})
finally:
    proc.terminate()
    proc.wait(timeout=10)

out = ROOT / 'outputs/canonical'
out.mkdir(parents=True, exist_ok=True)
(out / 'scoring-controls.json').write_text(json.dumps({'allPassed': all(x['passed'] for x in checks), 'count': len(checks), 'checks': checks}, indent=2) + '\n')
print(json.dumps({'allPassed': True, 'checks': len(checks), 'modelCalls': 0}))
