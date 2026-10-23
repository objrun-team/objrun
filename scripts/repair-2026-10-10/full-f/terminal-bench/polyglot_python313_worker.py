"""Staged C/Python worker with interpreter-only official verifier dependency.

Not imported by the production grader. A real transfer and reference cold
control must pass before any future readiness includes this source.
"""
import json
import os
import time
from pathlib import Path

from polyglot_worker import PLAN
from verifier_python313 import prepare_runtime_transfer, install_runtime_transfer


def python313_polyglot_worker(native, candidate, task, deadline, capsule, dependency_proof):
    if not any(f['path'] == '/app/polyglot/main.py.c' and f['exists'] for f in capsule['files']):
        return {'protocol': 'terminal-polyglot-cli-data-v1', 'rows': []}, []
    if deadline <= time.monotonic():
        raise TimeoutError('Official polyglot verifier deadline exhausted')
    source = native.assert_actor(candidate)
    assert source['State']['Paused']
    transfer = prepare_runtime_transfer(native, dependency_proof, deadline)
    image, initial_commit = native.commit(candidate, 'untrusted-polyglot-python313')
    rows, receipts = [], []
    for index, operation in enumerate(PLAN):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Official polyglot verifier deadline exhausted')
        # Read PATH from this actual candidate-derived image, not a host default.
        env_receipt = native.checked(['image', 'inspect', '--format', '{{json .Config.Env}}', image], timeout=remaining)
        image_env = json.loads(native.text(env_receipt)) or []
        path_values = [value[5:] for value in image_env if value.startswith('PATH=')]
        assert len(path_values) == 1 and '\x00' not in path_values[0]
        managed_bin = transfer['interpreterDirectory']
        path = ':'.join([managed_bin, *[part for part in path_values[0].split(':') if part != managed_bin]])
        environment = dict(os.environ)
        environment['PATH'] = path
        argv, worker_image = operation['argv'], image
        cid, initial, create = native.create(
            'untrusted-polyglot-python313-' + str(index), image, argv[0], argv[1:],
            network='none', cwd='/app', env_names=('PATH',), environment=environment,
            memory_mb=task['officialEnvironment']['memory_mb'], cpus=task['officialEnvironment']['cpus'])
        try:
            # Subsequent snapshots inherit the installed tree from successful gcc.
            installation = install_runtime_transfer(native, cid, transfer, deadline) if index == 0 else None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Official polyglot verifier deadline exhausted')
            start = native.command(['start', '-a', cid], timeout=remaining, stdout_limit=2 * 1024**2)
            final = native.assert_actor(cid)
            fault = final['State'].get('Error', '')
            missing = 'executable file not found' in fault or ('stat ' + argv[0] + ': no such file or directory') in fault
            exception = 'FileNotFoundError' if final['State']['Status'] == 'created' and missing else None
            if exception is None:
                assert final['State']['Status'] == 'exited'
            captured = {}
            for name in ('stdout', 'stderr'):
                captured[name] = Path(start[name]['path']).read_bytes().decode('utf-8').replace('\r\n', '\n').replace('\r', '\n') if operation['capture'] else None
            next_commit = None
            if exception is None and final['State']['ExitCode'] == 0:
                image, next_commit = native.commit(cid, 'untrusted-polyglot-python313-chain-' + str(index))
            rows.append({**operation, 'exitCode': final['State']['ExitCode'], **captured, 'exception': exception})
        finally:
            removal, absence = native.remove(cid)
        receipts.append({'cid': cid, 'initial': initial, 'create': create, 'start': start, 'final': final,
                         'sourceState': source, 'snapshot': worker_image, 'initialCommit': initial_commit,
                         'nextImage': image, 'nextCommit': next_commit, 'removal': removal, 'absence': absence,
                         'runtimeInstall': installation, 'candidatePathReceipt': env_receipt,
                         'interpreterArchiveSha256': transfer['archiveSha256'],
                         'interpreterDirectory': managed_bin, 'dependencyProofPath': transfer['proofPath'],
                         'privateTestSourcesSupplied': 0})
        if exception is not None or final['State']['ExitCode'] != 0:
            break
    # Raw archive bytes stay local; only native receipts and hashes are persisted.
    transfer_evidence = {key: value for key, value in transfer.items() if key != 'raw'}
    receipts[0]['interpreterTransfer'] = transfer_evidence
    return {'protocol': 'terminal-polyglot-cli-data-v1', 'rows': rows}, receipts
