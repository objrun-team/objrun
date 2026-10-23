"""Zero-model controls exercise actual Lean execution and model-visible boundaries."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import json
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import threading
from lean_worker import Grader, compile_raw, digest, sandbox_args, save
from sequence import messages, check_messages
from transport import Transport, BudgetStop

def main(root):
    root = Path(root).resolve(); os.chdir(root)
    cfg = json.loads((root / 'package/experiment.json').read_text())
    environment = json.loads((root / 'outputs/environment.json').read_text())
    identity = digest(json.dumps(environment, sort_keys=True))
    grader = Grader(root, cfg, identity)
    output = root / 'outputs/control' / ('attempt-' + str(time.time_ns())); output.mkdir(parents=True)
    header = 'import Mathlib\nimport Aesop\nset_option maxHeartbeats 0\nopen BigOperators Real Nat Topology Rat\n'
    checks = []
    def task(name, prop='True'):
        return {'id': 'control/' + name, 'name': name, 'header': header, 'statement': 'theorem ' + name + ' : ' + prop + ' := by\n'}
    cases = [
        ('correct', task('mf_control_true'), 'theorem mf_control_true : True := by\n  trivial\n', True),
        ('incorrect', task('mf_control_false', 'False'), 'theorem mf_control_false : False := by\n  trivial\n', False),
        ('sorry', task('mf_control_sorry'), 'theorem mf_control_sorry : True := by\n  sorry\n', False),
        ('changed_statement', task('mf_control_changed'), 'theorem mf_control_changed : False := by\n  trivial\n', False),
        ('new_axiom', task('mf_control_axiom'), 'axiom fake : True\ntheorem mf_control_axiom : True := by\n  exact fake\n', False),
        ('auxiliary_lemma', task('mf_control_aux'), 'lemma mf_aux : True := by\n  trivial\ntheorem mf_control_aux : True := by\n  exact mf_aux\n', True),
        ('native_decide', task('mf_control_native', '(17 : Nat) < 19'), 'theorem mf_control_native : (17 : Nat) < 19 := by\n  native_decide\n', True),
        ('empty_candidate', task('mf_control_empty'), '', False),
    ]
    futures = [(name, expected, grader.accept(q, answer)) for name, q, answer, expected in cases]
    for name, expected, future in futures:
        grade = future.result(timeout=1000)
        check = {'name': name, 'passed': grade['valid'] and grade['passed'] == expected, 'grade': grade}
        checks.append(check); print(json.dumps({'control': name, 'passed': check['passed']}), flush=True)
    # Equal concurrent candidates cause one physical execution and then persistent-cache reuse.
    q = task('mf_control_singleflight_' + str(time.time_ns())); answer = q['statement'] + '  trivial\n'
    before = grader.executions
    repeated = [grader.accept(q, answer) for _ in range(8)]
    values = [f.result(timeout=1000) for f in repeated]
    checks.append({'name': 'concurrent_singleflight', 'passed': all(v['valid'] and v['passed'] for v in values) and grader.executions - before == 1,
                   'physicalExecutions': grader.executions - before, 'cacheHits': sum(v['cacheHit'] for v in values)})
    grader.close()
    restarted = Grader(root, cfg, identity)
    value = restarted.accept(q, answer).result(timeout=1000)
    checks.append({'name': 'persistent_cache_after_restart', 'passed': value['cacheHit'] and value['passed'] and restarted.executions == 0})
    restarted.close()
    # Same sandbox configuration, inherited sentinel deliberately removed by env -i.
    private = output / 'private-sentinel.txt'; private.write_text('private test artifact')
    args = sandbox_args(root)[:-1] + ['/usr/bin/python3.11', '-c',
        'import os,json,socket; s=socket.socket();s.settimeout(1); print(json.dumps({"key":os.getenv("OPENROUTER_API_KEY"),"privateVisible":os.path.exists(' + repr(str(private)) + '),"netns":os.readlink("/proc/self/ns/net"),"connect":s.connect_ex(("1.1.1.1",80)),"cwd":os.getcwd()}))']
    probe = subprocess.run(args, env={'PATH': '/usr/bin:/bin', 'OPENROUTER_API_KEY': 'CONTROL_SENTINEL'}, capture_output=True, text=True, timeout=20)
    (output / 'isolation.stdout.txt').write_text(probe.stdout); (output / 'isolation.stderr.txt').write_text(probe.stderr)
    isolation = json.loads(probe.stdout) if probe.returncode == 0 else {}
    checks.append({'name': 'namespace_and_credential_isolation', 'passed': probe.returncode == 0 and isolation.get('key') is None and isolation.get('privateVisible') is False and isolation.get('connect') != 0 and isolation.get('netns') != os.readlink('/proc/self/ns/net'), 'observation': isolation})
    # A real Lean tactic sleeps past a one-second compile deadline.
    timeout = compile_raw(root, header, 'theorem mf_control_sleep : True := by\n  run_tac do IO.sleep 4000\n  trivial\n', output / 'real-timeout', timeout=1)
    checks.append({'name': 'real_compile_timeout', 'passed': timeout.get('valid') is True and timeout.get('outcome') == 'candidate_compile_timeout' and timeout.get('compileSeconds', 0) >= 1, 'execution': {k: v for k, v in timeout.items() if k != 'response'}})
    # Kill only the exact owned worker after its real header has initialized.
    crash_dir = output / 'real-crash'
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(compile_raw, root, header, 'theorem mf_control_crash : True := by\n  run_tac do IO.sleep 6000\n  trivial\n', crash_dir, 30)
        until = time.monotonic() + 600
        killed = False
        while not future.done() and time.monotonic() < until:
            if (crash_dir / 'header-response.json').exists() and (crash_dir / 'process.json').exists():
                process = json.loads((crash_dir / 'process.json').read_text()); pid = process['pid']
                cmdline = Path('/proc/' + str(pid) + '/cmdline')
                if cmdline.exists() and str(root / 'assets').encode() in cmdline.read_bytes():
                    os.kill(pid, signal.SIGKILL); killed = True; break
            time.sleep(.05)
        crashed = future.result(timeout=60)
    checks.append({'name': 'repl_crash_is_not_failed_proof', 'passed': killed and not crashed['valid'], 'injectedIntoOwnedPid': killed, 'execution': {k: v for k, v in crashed.items() if k != 'response'}})
    public_task = json.loads((root / 'data/public-pilot.json').read_text())[0]
    history = [{'answer': 'old proof', 'grade': {'valid': True, 'passed': False, 'privateDiagnostic': 'PRIVATE_ERROR_SENTINEL'}}]
    independent = messages(cfg['systemPrompt'], public_task['prompt'], 'independent', history)
    binary = messages(cfg['systemPrompt'], public_task['prompt'], 'binary', history)
    a = check_messages(independent, cfg['systemPrompt'], public_task, 'independent', history)
    b = check_messages(binary, cfg['systemPrompt'], public_task, 'binary', history)
    checks.append({'name': 'model_message_information_isolation', 'passed': a and b and len(independent) == 2 and binary[-1]['content'] == 'failed' and 'PRIVATE_ERROR_SENTINEL' not in json.dumps([independent, binary])})
    invalid = [{'answer': 'old proof', 'grade': {'valid': False, 'passed': False}}]
    try: messages(cfg['systemPrompt'], public_task['prompt'], 'binary', invalid)
    except ValueError: rejected = True
    else: rejected = False
    checks.append({'name': 'invalid_grade_cannot_become_binary_feedback', 'passed': rejected})
    fake_root = output / 'budget-fixture'; fake_root.mkdir(exist_ok=True)
    tiny = dict(cfg, perTaskDollarCap=0, batchDollarCap=0, requestSpacingSeconds=0)
    transport = Transport(fake_root, tiny, 'DUMMY_NO_REQUEST_ALLOWED')
    blocked = 0
    for i in range(8):
        try: transport.generate('independent/example-' + str(i), 0, independent, time.time() + 10)
        except BudgetStop: blocked += 1
    checks.append({'name': 'cost_reservation_blocks_before_dispatch', 'passed': blocked == 8 and transport.accounting()['modelRequests'] == 0 and transport.held == 0})
    # A simulated HTTP boundary holds two requests simultaneously. Exactly two
    # reservations fit, proving in-flight dispatches are not counted twice.
    mock_root = output / 'concurrent-budget-fixture'; mock_root.mkdir()
    mock_cfg = dict(cfg, maxTokens=1, inputUsdPerMillionCeiling=0., outputUsdPerMillionCeiling=1., requestSpacingSeconds=0,
                    perTaskDollarCap=1., batchDollarCap=.000002)
    mock = Transport(mock_root, mock_cfg, 'DUMMY_SIMULATED_HTTP_ONLY')
    barrier = threading.Barrier(2)
    class Reply(io.BytesIO):
        status = 200
        headers = {}
    class SimulatedHTTP:
        def open(self, request, timeout):
            barrier.wait(timeout=5)
            value = {'id': 'synthetic-control-only', 'provider': cfg['provider'], 'model': cfg['model'],
                     'choices': [{'message': {'content': 'synthetic proof'}, 'finish_reason': 'stop'}], 'usage': {'cost': .000001}}
            return Reply(json.dumps(value).encode())
    mock.opener = SimulatedHTTP()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(mock.generate, 'independent/synthetic-' + str(i), 0, independent, time.time() + 10) for i in range(2)]
        values = [f.result() for f in futures]
    third_blocked = False
    try: mock.generate('independent/synthetic-third', 0, independent, time.time() + 10)
    except BudgetStop: third_blocked = True
    checks.append({'name': 'concurrent_cost_reservations_and_exact_cap', 'passed': len(values) == 2 and mock.accounting()['modelRequests'] == 2 and abs(mock.accounting()['budgetChargedUsd'] - .000002) < 1e-12 and third_blocked and abs(mock.held) < 1e-12, 'realNetworkRequests': 0})
    save(output / 'message-fixture.json', {'independent': independent, 'binary': binary})
    result = {'allPassed': all(c['passed'] for c in checks), 'modelCalls': 0, 'checks': checks, 'environmentIdentity': identity,
              'graderIdentity': grader.identity,
              'graderPeak': grader.peak, 'atEpoch': time.time()}
    result['sourcePins'] = {str(p.relative_to(root)): digest(p.read_bytes()) for d in ['package', 'vendor', 'data'] for p in (root / d).iterdir() if p.is_file()}
    save(output / 'controls.json', result); save(root / 'outputs/controls.json', result)
    print(json.dumps({'allPassed': result['allPassed'], 'controls': len(checks), 'failed': [c['name'] for c in checks if not c['passed']]}), flush=True)
    if not result['allPassed']: raise SystemExit(1)

if __name__ == '__main__': main(sys.argv[1])
