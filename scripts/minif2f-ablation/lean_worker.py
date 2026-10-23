"""Fresh networkless namespace per candidate; the host alone owns scoring logs."""
from __future__ import annotations
import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import signal
import sqlite3
import subprocess
import threading
import time

def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()

def save(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + str(threading.get_ident()) + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n'); tmp.replace(path)

def source_functions(vendor):
    names = {'norm', 'starts_command', 'commands', 'split_cand', 'cand_of', 'is_error', 'has_sorry'}
    constants = {'BLOCK_COMMENT', 'LINE_COMMENT', 'MARK', 'ALLOWED_IMPORTS', 'AUX_HEAD', 'COMMAND_KW'}
    env = {'re': re}
    for filename in ['source_stand.py', 'kimina_models.py']:
        tree = ast.parse((vendor / filename).read_text())
        nodes = [ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)]
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in names: nodes.append(node)
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in node.targets): nodes.append(node)
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), filename, 'exec'), env)
    return env

def sandbox_args(root):
    assets = root / 'assets'
    paths = ['/opt/mathlib/.lake/build/lib']
    for p in sorted((assets / 'mathlib4/.lake/packages').iterdir()):
        if (p / '.lake/build/lib').exists(): paths.append('/opt/mathlib/.lake/packages/' + p.name + '/.lake/build/lib')
    # env -i works with the server's bubblewrap 0.4.0, which lacks --clearenv.
    # This boundary also clears deliberately inherited credentials in controls.
    return ['/usr/bin/env', '-i', 'PATH=/usr/bin:/bin', '/usr/bin/bwrap',
            '--unshare-all', '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
            '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib', '--ro-bind', '/lib64', '/lib64',
            '--ro-bind', str(assets / 'lean'), '/opt/lean', '--ro-bind', str(assets / 'mathlib4'), '/opt/mathlib',
            '--ro-bind', str(assets / 'repl-bin'), '/opt/repl', '--proc', '/proc', '--dev', '/dev',
            '--tmpfs', '/tmp', '--tmpfs', '/work', '--chdir', '/work',
            '--setenv', 'HOME', '/tmp', '--setenv', 'TMPDIR', '/tmp',
            '--setenv', 'PATH', '/opt/lean/bin:/usr/bin:/bin', '--setenv', 'LEAN_SYSROOT', '/opt/lean',
            '--setenv', 'LEAN_PATH', ':'.join(paths),
            '--setenv', 'LD_LIBRARY_PATH', '/opt/lean/lib/lean:/opt/lean/lib', '--', '/opt/repl']

def compile_raw(root, header, code, directory, timeout=300, memory_gib=12):
    directory.mkdir(parents=True, exist_ok=True)
    args = sandbox_args(root)
    # No credential is inherited even by bubblewrap itself.
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(root / 'home'), 'TMPDIR': str(root / 'tmp'), 'LANG': 'C.UTF-8'}
    args = ['prlimit', '--as=' + str(memory_gib * 1024**3), '--core=0', '--fsize=67108864',
            '--cpu=' + str(timeout + 600) + ':' + str(timeout + 605), '--'] + args
    start = time.monotonic()
    with (directory / 'stderr.txt').open('wb') as errors:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                                env=env, start_new_session=True)
        save(directory / 'process.json', {'pid': proc.pid, 'args': args, 'environment': env, 'freshProcess': True,
             'network': 'new empty namespace', 'credentialsInherited': False, 'memoryGiB': memory_gib,
             'compileTimeoutSeconds': timeout, 'headerTimeoutSeconds': 600})
        lines = queue.Queue()
        def read():
            try:
                with (directory / 'stdout.txt').open('wb') as output:
                    total = 0
                    for line in iter(proc.stdout.readline, b''):
                        output.write(line); output.flush(); total += len(line)
                        if total > 16 * 1024**2: lines.put(RuntimeError('OutputLimit')); return
                        lines.put(line)
            finally: lines.put(None)
        thread = threading.Thread(target=read, daemon=True); thread.start()
        def exchange(obj, seconds):
            proc.stdin.write((json.dumps(obj, ensure_ascii=False) + '\n\n').encode()); proc.stdin.flush()
            deadline = time.monotonic() + seconds
            buffer = b''
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise TimeoutError('ProcessDeadline')
                try: line = lines.get(timeout=remaining)
                except queue.Empty: raise TimeoutError('ProcessDeadline')
                if line is None: raise RuntimeError('ReplClosed:exit=' + str(proc.poll()))
                if isinstance(line, Exception): raise line
                buffer += line
                if not buffer.strip(): buffer = b''; continue
                try: value = json.loads(buffer)
                except json.JSONDecodeError: continue
                if not isinstance(value, dict): raise RuntimeError('ReplResponseShape')
                return value
        record = {'valid': False, 'passed': False}
        try:
            initial = exchange({'cmd': header}, 600)
            save(directory / 'header-response.json', initial)
            if 'env' not in initial or any(m.get('severity') == 'error' for m in initial.get('messages', [])):
                raise RuntimeError('HeaderInitializationFailed')
            compile_start = time.monotonic()
            try: result = exchange({'cmd': code, 'env': initial['env']}, timeout)
            except TimeoutError:
                # The deadline belongs to an actually running compilation, never an HTTP queue.
                record = {'valid': True, 'passed': False, 'outcome': 'candidate_compile_timeout',
                          'compilerWasRunning': proc.poll() is None, 'compileSeconds': time.monotonic() - compile_start}
                if not record['compilerWasRunning']: record.update(valid=False, outcome='process_failure')
            else:
                save(directory / 'lean-response.json', result)
                if 'env' not in result or 'message' in result: raise RuntimeError('ReplProtocolError:' + str(result.get('message')))
                record = {'valid': True, 'response': result, 'compileSeconds': time.monotonic() - compile_start}
        except Exception as exc:
            record = {'valid': False, 'passed': False, 'outcome': 'lean_infrastructure_error', 'error': str(exc)}
        finally:
            cleanup_initiated = proc.poll() is None
            if proc.poll() is None:
                try: os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            proc.wait(); thread.join(timeout=3)
            record.update(exitCode=proc.returncode, seconds=time.monotonic() - start,
                          controllerCleanupSignal=signal.SIGKILL if cleanup_initiated else None)
            save(directory / 'execution.json', {k: v for k, v in record.items() if k != 'response'})
        return record

class Grader:
    def __init__(self, root, config, environment_identity):
        self.root, self.config = root, config
        self.identity = digest(json.dumps({'environment': environment_identity,
            'graderSource': digest(Path(__file__).read_bytes()),
            'parserSource': digest((root / 'vendor/source_stand.py').read_bytes()),
            'officialPredicates': digest((root / 'vendor/kimina_models.py').read_bytes())}, sort_keys=True))
        self.functions = source_functions(root / 'vendor')
        self.pool = ThreadPoolExecutor(max_workers=config['graderConcurrency'], thread_name_prefix='lean')
        self.lock = threading.Lock(); self.key_locks = {}; self.executions = 0; self.active = 0; self.peak = 0
        self.db = root / 'outputs/score-cache.sqlite'
        self.db.parent.mkdir(exist_ok=True)
        with sqlite3.connect(self.db) as conn:
            conn.execute('create table if not exists scores (identity text primary key, result text not null)')

    def key(self, task, answer):
        return digest(json.dumps({'task': task['id'], 'header': digest(task['header']), 'statement': digest(task['statement']),
              'candidate': digest(answer), 'environment': self.identity, 'timeout': self.config['compileTimeoutSeconds'],
              'memory': self.config['workerMemoryGiB'], 'allowedAxioms': ['propext', 'Classical.choice', 'Quot.sound', 'Lean.ofReduceBool']}, sort_keys=True))

    def accept(self, task, answer):
        return self.pool.submit(self._accept, task, answer)

    def _accept(self, task, answer):
        identity = self.key(task, answer)
        with self.lock: gate = self.key_locks.setdefault(identity, threading.Lock())
        with gate:
            with sqlite3.connect(self.db) as conn:
                row = conn.execute('select result from scores where identity=?', (identity,)).fetchone()
            if row:
                result = json.loads(row[0]); result['cacheHit'] = True; return result
            with self.lock:
                self.executions += 1; self.active += 1; self.peak = max(self.peak, self.active)
            try:
                result = self._judge(task, answer, identity)
                if result['valid']:
                    with sqlite3.connect(self.db) as conn:
                        conn.execute('insert into scores values (?,?)', (identity, json.dumps(result)))
                return result
            finally:
                with self.lock: self.active -= 1

    def _judge(self, task, answer, identity):
        directory = self.root / 'outputs/grades' / identity / ('invocation-' + str(time.time_ns()))
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'candidate.txt').write_text(answer)
        save(directory / 'identity.json', {'taskId': task['id'], 'candidateSha256': digest(answer), 'key': identity, 'environmentIdentity': self.identity})
        plain = self.functions['cand_of'](answer)
        ok, prelude, body, why = self.functions['split_cand'](plain, task)
        result = {'valid': True, 'passed': False, 'candidateSha256': digest(answer), 'identity': identity,
                  'gradeDirectory': str(directory.relative_to(self.root)), 'cacheHit': False,
                  'stated': ok, 'compiles': False, 'sound': False}
        if not ok:
            result.update(outcome='candidate_format_failure', privateDiagnostic=why)
        else:
            code = (prelude.rstrip() + '\n\n' if prelude.strip() else '') + task['statement'].rstrip() + '\n' + body.rstrip() + '\n\n#print axioms ' + task['name'] + '\n'
            (directory / 'compiled-code.lean').write_text(task['header'] + code)
            execution = None
            for retry in range(2):
                execution = compile_raw(self.root, task['header'], code, directory / ('execution-' + str(retry)), self.config['compileTimeoutSeconds'], self.config['workerMemoryGiB'])
                if execution['valid']: break
                if 'ReplClosed' not in execution.get('error', ''): break
            result.update({k: v for k, v in execution.items() if k != 'response'})
            if execution['valid'] and 'response' in execution:
                response = execution['response']
                result['compiles'] = not self.functions['is_error'](response)
                axioms = None
                for message in response.get('messages', []):
                    match = re.search(r"'([^']+)' (?:does not depend on any axioms|depends on axioms: \[(.*?)\])", message.get('data', ''), re.S)
                    if match and match[1] == task['name']:
                        axioms = [a.strip() for a in (match[2] or '').split(',') if a.strip()]
                result['axioms'] = axioms
                allowed = {'propext', 'Classical.choice', 'Quot.sound', 'Lean.ofReduceBool'}
                result['sound'] = result['compiles'] and not self.functions['has_sorry'](response) and axioms is not None and set(axioms) <= allowed
                result['passed'] = result['stated'] and result['compiles'] and result['sound']
                result['outcome'] = 'passed' if result['passed'] else 'candidate_proof_failure'
        save(directory / 'grade.json', result)
        return result

    def close(self): self.pool.shutdown(wait=True)
