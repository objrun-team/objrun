"""Freeze the official 87-task F roster, exact budgets and isolation worklist.

This is preparation, never a pilot launcher or a score certificate. Source
inspection executes no oracle, verifier, task code, or model request.
"""
from __future__ import annotations
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import yaml

ROOT = Path(__file__).resolve().parents[4]
HOME = ROOT / 'docs/repair-2026-10-10/full-f-rerun/skillsbench'
VENDOR = ROOT / '.phase1-data/skillsbench/vendor/skillsbench'
OLD = ROOT / 'scripts/benchmark-repair'
spec = importlib.util.spec_from_file_location('skb_public_inventory', OLD / 'skillsbench_ten_public_metadata.py')
public = importlib.util.module_from_spec(spec)
spec.loader.exec_module(public)

def utc():
    return datetime.now(timezone.utc).isoformat()

def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()

def save(path, value, immutable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(value)
    if immutable and path.exists():
        if path.read_bytes() != raw:
            raise ValueError('Frozen source/config changed: ' + str(path))
    else:
        temp = path.with_suffix(path.suffix + '.tmp-' + str(os.getpid()))
        with temp.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    return public.pin(path)

def parse_task(directory):
    raw = (directory / 'task.md').read_bytes()
    parts = re.split(rb'(?m)^---[ \t]*\r?\n', raw, maxsplit=2)
    if len(parts) != 3 or parts[0]:
        raise ValueError('Invalid original frontmatter: ' + directory.name)
    meta = yaml.safe_load(parts[1])
    resources = {name: meta[name] for name in ('agent', 'verifier', 'environment')}
    if any(not isinstance(resources[k], dict) for k in resources):
        raise ValueError('Missing original resources')
    docker_text = (directory / 'environment/Dockerfile').read_text(encoding='utf-8')
    workdirs = re.findall(r'(?mi)^WORKDIR\s+(\S+)', docker_text)
    source_before = public.tree(directory)
    analyses, analysis_errors = {}, []
    for script in sorted((directory / 'verifier').rglob('*.py')):
        try:
            analyses[script.relative_to(directory / 'verifier').as_posix()] = public.ast_metadata(script)
        except (SyntaxError, UnicodeError) as error:
            analysis_errors.append({'file': script.name, 'type': type(error).__name__})
    execution = [{**call, 'source': file} for file, analysis in analyses.items() for call in analysis['executionCalls']]
    literals = sorted({p for analysis in analyses.values() for p in analysis['absolutePathLiterals']})
    test_shell = (directory / 'verifier/test.sh').read_text(encoding='utf-8')
    artifact = public.SELECTED.get(directory.name)
    row = {
        'taskId': directory.name, 'arm': 'F', 'replica': 0,
        'taskSourcePin': public.pin(directory / 'task.md'),
        'promptBodySha256': hashlib.sha256(parts[2]).hexdigest(), 'promptBodyBytes': len(parts[2]),
        'originalResources': resources,
        'taskSeconds': resources['agent']['timeout_sec'], 'verifierSeconds': resources['verifier']['timeout_sec'],
        'workdir': workdirs[-1] if workdirs else '/',
        'environmentSource': public.tree(directory / 'environment'),
        'verifierSource': public.tree(directory / 'verifier'),
        'oracleSourceMetadata': public.tree(directory / 'oracle'),
        'skillSource': public.tree(directory / 'environment/skills') if (directory / 'environment/skills').is_dir() else None,
        'verifierRunnerPin': public.pin(directory / 'verifier/test.sh'),
        'verifierAnalysis': analyses, 'analysisErrors': analysis_errors,
        'candidatePathHints': literals,
        'candidatePathHintsAreApprovedArtifacts': False,
        'verifierExecutionCalls': execution,
        'originalPackageTokens': sorted(set(re.findall(r'(?<![\w.-])([A-Za-z][A-Za-z0-9_.-]*==[0-9][A-Za-z0-9_.-]*)', docker_text + '\n' + test_shell))),
        'originalBaseRefs': re.findall(r'(?mi)^FROM\s+(\S+)', docker_text),
        'originalRunnerHasRuntimeInstall': any(s in test_shell for s in ('apt-get ', 'pip install ', 'pip3 install ', 'curl -LsSf')),
        'existingOrdinaryV2OutputPolicy': artifact,
        'readiness': {'environmentBuilt': False, 'privateGraderReady': False, 'fullCollectionReady': False, 'coldControlsReady': False, 'paidReady': False},
        'requiredPreparation': ['source-bound immutable candidate image', 'separate trusted grader image and interpreter', 'approved ordinary artifact paths', 'complete original pytest collection and reward protocol', 'empty/oracle/wrong controls', 'shared heavy slot and paid lane'],
        'sourceBeforeAfterEqual': source_before == public.tree(directory),
    }
    if not row['sourceBeforeAfterEqual']:
        raise ValueError('Source changed while inventoried: ' + directory.name)
    return row

def session_settings():
    tid = os.environ.get('CODEX_THREAD_ID')
    sessions = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'sessions'
    context = None
    for file in sessions.glob('2026/10/10/*' + str(tid) + '*'):
        with file.open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                    if event.get('type') == 'turn_context':
                        p = event['payload']
                        context = {'model': p.get('model'), 'reasoningEffort': p.get('effort'), 'collaborationReasoningEffort': p.get('collaboration_mode', {}).get('settings', {}).get('reasoning_effort')}
                except (ValueError, KeyError):
                    continue
    # Rollout context does not expose effective service tier; explicitly record
    # the workspace/global configuration observation instead of claiming it does.
    config = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'config.toml'
    text = config.read_text(encoding='utf-8') if config.exists() else ''
    tier = re.search(r'(?m)^service_tier\s*=\s*"([^"]+)"', text)
    return {'threadId': tid, 'actualTurnContext': context, 'configuredServiceTier': tier.group(1) if tier else None, 'effectiveServiceTierExposed': False, 'modelOrFastChanged': False}

def observe():
    docker = Path('D:/Program/resources/bin/docker.exe')
    argv = [str(docker), '--host', 'npipe:////./pipe/dockerDesktopLinuxEngine', 'info', '--format', '{{json .}}']
    try:
        result = subprocess.run(argv, capture_output=True, timeout=20)
        data = json.loads(result.stdout) if result.returncode == 0 else None
        return {'observedAtUtc': utc(), 'daemonReady': result.returncode == 0, 'exitCode': result.returncode,
                'error': result.stderr.decode(errors='replace')[-800:],
                'serverVersion': data.get('ServerVersion') if data else None,
                'dockerRootDir': data.get('DockerRootDir') if data else None,
                'containersRunning': data.get('ContainersRunning') if data else None,
                'images': data.get('Images') if data else None, 'dockerMutations': 0}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'observedAtUtc': utc(), 'daemonReady': False, 'error': type(error).__name__, 'dockerMutations': 0}

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--refresh', action='store_true'); args = parser.parse_args()
    registry = json.loads((VENDOR / 'registry.json').read_bytes())
    release = next(x for x in registry if x['version'] == '1.1')
    registry_ids = sorted(x['name'] for x in release['tasks'])
    directories = sorted(p for p in (VENDOR / 'tasks').iterdir() if p.is_dir())
    if len(directories) != 87 or [p.name for p in directories] != registry_ids:
        raise ValueError('Official v1.1 complete roster differs from local 87 tasks')
    if not (HOME / 'manifest.json').exists():
        rows = [parse_task(p) for p in directories]
        run_id = 'repair-' + datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%S-000Z')
        for index, row in enumerate(rows):
            row.update(index=index, id=run_id + '/skillsbench/F/0/' + row['taskId'], route=run_id + '/skillsbench/F/0/' + row['taskId'])
            save(HOME / 'task-descriptors' / (row['taskId'] + '.json'), row, True)
        schedule = [{k: row[k] for k in ('index', 'id', 'route', 'taskId', 'arm', 'replica', 'taskSeconds', 'verifierSeconds', 'workdir', 'promptBodySha256', 'taskSourcePin', 'originalResources')} for row in rows]
        manifest = {'protocol': 'skillsbench-full-f-manifest-v1', 'runId': run_id, 'createdAtUtc': utc(), 'benchmark': 'SkillsBench',
                    'version': '1.1', 'split': 'default tasks/', 'denominator': 87, 'plannedTaskRuns': 87, 'arms': ['F'],
                    'model': 'deepseek/deepseek-v4.1-flash', 'provider': 'relace', 'allow_fallbacks': False,
                    'reasoning': {'enabled': True, 'effort': 'high', 'exclude': False}, 'temperature': 0, 'maxOutputTokens': 16384,
                    'explicitVerifyChecks': 6, 'maxBranches': 4, 'maxDeadSiblings': 100000,
                    'skillsMode': 'with original task skills', 'perBenchMaxInFlight': 2, 'heavyContainerSlots': 1,
                    'taskSchedule': schedule, 'taskScheduleSha256': hashlib.sha256(canonical(schedule)).hexdigest(),
                    'source': {'repository': 'https://github.com/benchflow-ai/skillsbench', 'declaredTag': 'v1.1',
                               'registryDeclaredCommit': sorted({t['git_commit_id'] for t in release['tasks']}),
                               'registryPin': public.pin(VENDOR / 'registry.json'), 'archiveProvenancePin': public.pin(ROOT / '.phase1-data/skillsbench/source.json'),
                               'archiveProvenanceMatchesRegistryCommit': False, 'identityAuthority': 'frozen local complete task tree hashes; archive source.json commit differs from registry v1.1 commit',
                               'vendorHasOwnGitCheckout': (VENDOR / '.git').exists()},
                    'isolationProtocol': 'ordinary-artifact-v2-generalization-required',
                    'sourceFilePins': [public.pin(p) for d in directories for p in sorted(d.rglob('*')) if p.is_file()],
                    'formalScoreCertified': False, 'paidReady': False}
        save(HOME / 'manifest.json', manifest, True)
        audit = {'protocol': 'skillsbench-full-f-isolation-worklist-v1', 'denominator': 87,
                 'tenTaskOrdinaryPolicyExists': sum(bool(r['existingOrdinaryV2OutputPolicy']) for r in rows),
                 'tasksRequiringArtifactPolicy': [r['taskId'] for r in rows if not r['existingOrdinaryV2OutputPolicy']],
                 'tasksWithVerifierExecutionCalls': {r['taskId']: r['verifierExecutionCalls'] for r in rows if r['verifierExecutionCalls']},
                 'tasksWithAnalysisErrors': {r['taskId']: r['analysisErrors'] for r in rows if r['analysisErrors']},
                 'sourceBeforeAfterEqual': all(r['sourceBeforeAfterEqual'] for r in rows),
                 'noOracleOrVerifierExecuted': True, 'modelCalls': 0}
        save(HOME / 'isolation-worklist.json', audit, True)
    manifest = json.loads((HOME / 'manifest.json').read_bytes())
    if manifest['denominator'] != 87 or manifest['arms'] != ['F'] or len(manifest['taskSchedule']) != 87:
        raise ValueError('Full F denominator/config drift')
    observation = observe(); save(HOME / 'environment-observation.json', observation)
    config = session_settings(); save(HOME / 'codex-settings-observation.json', config)
    control = json.loads((HOME.parent / 'control.json').read_bytes())
    prior = json.loads((HOME / 'status.json').read_bytes()) if (HOME / 'status.json').exists() else {}
    blockers = ['full_87_ordinary_artifact_and_private_grader_generalization_pending']
    if not control.get('paidReady'): blockers.append('shared_paid_adapter_not_ready')
    if not observation['daemonReady']: blockers.append('docker_daemon_unavailable')
    status = {**prior, 'protocol': 'skillsbench-full-f-status-v1', 'updatedAtUtc': utc(), 'phase': 'preparing',
              'threadId': os.environ.get('CODEX_THREAD_ID'), 'runId': manifest['runId'], 'denominator': 87,
              'completed': prior.get('completed', 0), 'scored': prior.get('scored', 0), 'modelRequests': prior.get('modelRequests', 0),
              'costUsd': prior.get('costUsd', 0), 'costStatus': 'no requests dispatched' if not prior.get('modelRequests') else prior.get('costStatus', 'requires journal reconciliation'),
              'unknownCostRequests': prior.get('unknownCostRequests', 0), 'arms': ['F'], 'fullManifestFrozen': True,
              'sharedPaidReady': control.get('paidReady', False), 'daemonReady': observation['daemonReady'], 'blockers': blockers,
              'sharedChangesRequested': {'paidAdapter': 'Shared lane API + per-request journal/USD cash receipt access + heavy container lease required; no canonical owner acquired here.'},
              'actualCodexSettings': config, 'sourceIdentityCaveat': manifest['source']['identityAuthority'],
              'nextAction': 'Generalize source-pinned ordinary artifact isolation for all tasks; use shared adapter only after control.paidReady. Do not launch old paired/pilot/partial76 or snapshot graders.'}
    save(HOME / 'status.json', status)
    print(json.dumps({'manifest': str(HOME / 'manifest.json'), 'phase': status['phase'], 'denominator': 87, 'completed': status['completed'], 'costUsd': status['costUsd'], 'blockers': blockers}))

if __name__ == '__main__':
    main()
