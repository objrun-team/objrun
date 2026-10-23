"""One original ordinary-data private JSON control phase, never a task grader.

Images, original contracts, retained exports and output are explicit pinned data.
The original image emits the grading result; this module only transports it.
"""
import argparse, base64, hashlib, json, os, pathlib, time, uuid
from native_process import pin
from bounded_child import run as bounded_run
from build_environment import DOCKER, ENV
from original_sb_transport import require_original_lease
from ordinary_artifacts import Policy, parse_daemon_tar
from docker_mutation_ack import require as require_docker_mutation_ack


def checked(p):
    assert pin(p['path']) == p, 'ordinary_control_pin_changed'
    return pathlib.Path(p['path'])


def load(p):
    return json.loads(checked(p).read_bytes())


def run_phase(r, output):
    neutral = r['protocol'] == 'bench-neutral-ordinary-private-control-phase-v1'
    assert neutral or r['protocol'] == 'bench-original-ordinary-private-control-phase-v1'
    if neutral:
        assert r['taskId'] == 'neutral-ordinary-private-control'
        assert r['neutralPolicyTaskId'] == 'zero-model-owned-sb-asset'
    policy_task = r['neutralPolicyTaskId'] if neutral else r['taskId']
    history = globals().get('_bench_authorized_history')
    assert callable(history) and history(policy_task) is True
    assert r['phase'] in ('collect', 'empty', 'oracle', 'wrong')
    built = load(r['builtImagesPin'])
    assert built['taskId'] == r['taskId']
    original = load(r['originalBuiltImagesPin'])
    for key in ('taskId', 'originalResources', 'dataArtifactPolicy', 'workingDirectory',
                'artifactTmpfsBytes', 'artifactTmpfsParent'):
        assert built[key] == original[key], 'original_private_contract_changed:' + key
    snapshot = built['privateRunnerSourcePin']
    checked(snapshot)
    assert all(snapshot[k] == original['privateRunnerSourcePin'][k] for k in ('bytes', 'sha256'))
    resources = built['originalResources']
    assert r['phaseSeconds'] == resources['verifier']['timeout_sec']
    lease = require_original_lease(os.getppid(), resources)
    assert lease['taskId'] == policy_task
    output = pathlib.Path(output)
    output.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic() + r['phaseSeconds']
    serial = 0
    command_pins = []
    containers = []

    def command(args, body=None, cleanup=False):
        nonlocal serial
        serial += 1
        remaining = deadline - time.monotonic()
        assert cleanup or remaining > 0, 'original_private_phase_deadline'
        prefix = output / ('command-%03d' % serial)
        outcome = bounded_run([DOCKER, *args], ENV, prefix.with_suffix('.stdout'),
                              prefix.with_suffix('.stderr'), 30 if cleanup else remaining,
                              body, stdout_limit=16 * 1024**2)
        row = {'argv': [DOCKER, *args], **outcome,
               'stdoutPin': pin(prefix.with_suffix('.stdout')),
               'stderrPin': pin(prefix.with_suffix('.stderr')), 'modelCalls': 0}
        receipt = prefix.with_suffix('.json')
        receipt.write_text(json.dumps(row, indent=2) + '\n')
        command_pins.append(pin(receipt))
        assert not outcome['faults'] and outcome['directChildClosed'] and outcome['pipeReadersClosed']
        assert outcome['exitCode'] == 0, 'original_private_command_failed'
        raw = prefix.with_suffix('.stdout').read_bytes()
        require_docker_mutation_ack(args, raw)
        return raw

    incoming = []
    expected_manifest = []
    if r['phase'] in ('oracle', 'wrong'):
        controls = load(r['originalControlsResultPin'])
        assert controls['taskId'] == r['taskId'] and controls['controlsPassed'] is True
        assert controls['decisions'] == [0, 1, 0] and controls['ownedContainersRemaining'] == 0
        expected_manifest = controls['oracleArtifactManifest']
        policy = built['dataArtifactPolicy']
        outputs = policy.get('outputs') or [dict(path=policy['output'], kind=policy['kind'],
                    maximumBytes=policy['maximumBytes'], maximumFiles=policy['maximumFiles'])]
        allowed = {x['path']: x for x in outputs}
        for capture in r['retainedExports']:
            spec = capture['policy']
            assert allowed[spec['path']] == spec, 'original_artifact_policy_changed'
            path = spec['path']
            envelope = parse_daemon_tar(checked(capture['pin']).read_bytes(),
                Policy(r['taskId'], path, path, spec['kind'], spec['maximumBytes'],
                       spec['maximumFiles'], True, 'csv' if path.endswith('.csv') else None))
            for item in envelope['files']:
                incoming.append({'path': item['destination'], 'base64': base64.b64encode(item['body']).decode(),
                                 'sha256': item['sha256']})
        assert sorted((x['path'], x['sha256']) for x in incoming) == sorted(
            (x['path'], x['sha256']) for x in expected_manifest), 'retained_original_oracle_identity'
        if r['phase'] == 'wrong':
            # The existing original ordinary-data controls use this malformed data.
            wrong = b'not-a-valid-task-artifact\n'
            incoming = [dict(path=x['path'], base64=base64.b64encode(wrong).decode(),
                        sha256=hashlib.sha256(wrong).hexdigest()) for x in incoming]
    result = None
    try:
        e = resources['environment']
        args = ['create', '-i', '--pull', 'never', '--read-only', '--network', 'none',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--label', 'objrun.skb.role=full-f-private-control',
                '--label', 'objrun.skb.task-id=' + r['taskId'],
                '--memory', str(e['memory_mb'] * 1024**2), '--memory-swap', str(e['memory_mb'] * 1024**2),
                '--cpus', str(e['cpus']), '--tmpfs', '/logs/verifier:rw,nosuid,nodev,noexec,size=64m',
                '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=64m']
        for parent in built.get('artifactTmpfsParents', [built['artifactTmpfsParent']]):
            args += ['--tmpfs', parent + ':rw,nosuid,nodev,noexec,size=' + str(built['artifactTmpfsBytes'])]
        args += ['--workdir', built['workingDirectory'], built['privateImageId']]
        if r['phase'] == 'collect':
            args += ['--collect']
        cid = command(args).decode().strip()
        assert len(cid) == 64 and all(x in '0123456789abcdef' for x in cid)
        containers.append(cid)
        inspected = json.loads(command(['inspect', cid]))[0]
        h = inspected['HostConfig']
        assert inspected['Image'] == built['privateImageId'] and h['ReadonlyRootfs']
        assert h['NetworkMode'] == 'none' and not h.get('Binds') and not h.get('Mounts') and not h.get('Privileged')
        assert h['Memory'] == e['memory_mb'] * 1024**2 and h['MemorySwap'] == h['Memory']
        raw = command(['start', '-a', '-i', cid], json.dumps({'artifacts': incoming}).encode())
        original_result = json.loads(raw)
        assert original_result['taskId'] == r['taskId']
        assert original_result['candidateExecutablesUsed'] is False and original_result['candidateSnapshotUsed'] is False
        assert original_result['mode'] == ('collect' if r['phase'] == 'collect' else 'grade')
        if r['phase'] in ('collect', 'oracle'):
            assert original_result['complete'] is True, 'original_positive_completeness_required'
        result = {'protocol': 'bench-original-ordinary-private-phase-result-v1', 'taskId': r['taskId'],
                  'phase': r['phase'], 'builtImagesPin': r['builtImagesPin'], 'originalResult': original_result,
                  'rawOriginalResultPin': pin(output / ('command-%03d.stdout' % serial)),
                  'rawOriginalCommandPin': command_pins[-1], 'inspect': inspected,
                  'originalOracleExecutionRepeated': False, 'modelCalls': 0,
                  'gradeCalls': 0 if neutral else int(r['phase'] != 'collect'), 'referenceCalls': 0,
                  'originalPhaseSeconds': r['phaseSeconds'], 'retainedOracleManifest': expected_manifest,
                  'helperSourcePin': pin(__file__), 'complete': True}
    finally:
        for cid in containers[:]:
            command(['rm', '-f', cid], cleanup=True)
            containers.remove(cid)
        if result is not None:
            result.update(ownedContainersRemaining=len(containers), commandPins=command_pins)
            (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--request', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    result = run_phase(json.loads(pathlib.Path(a.request).read_bytes()), a.output)
    print(json.dumps({'complete': result['complete'], 'taskId': result['taskId'], 'phase': result['phase']}))


if __name__ == '__main__':
    main()
