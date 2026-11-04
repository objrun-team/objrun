"""Authenticated host-side Harbor environment and private grading bridge."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import sys
import time
import uuid
from aiohttp import web
if os.environ.get('TPE_REMOTE_DOCKER') == '1':
    from remote_docker import DockerEnvironment, EnvironmentConfig, TrialPaths, admission
else:
    from harbor.environments.docker.docker import DockerEnvironment
    from harbor.models.task.config import EnvironmentConfig
    from harbor.models.trial.paths import TrialPaths
from grade import evaluate

ROOT = (Path(__file__).resolve().parents[4] / 'scripts')
CATALOG = {t['id']: t for t in json.loads((ROOT / 'data/catalog.json').read_text())}
TOKEN = secrets.token_hex(32)
SESSIONS = {}
SNAPSHOTS = {}


def save(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    tmp.replace(p)


async def create(data):
    task = CATALOG[data['task']]
    sid = 'tpe-' + uuid.uuid4().hex[:16]
    paths = TrialPaths(ROOT / 'outputs/environments' / sid)
    paths.mkdir()
    env = DockerEnvironment(environment_dir=ROOT / 'data/public' / task['id'] / 'environment',
                            environment_name='theophyseval-' + task['id'], session_id=sid,
                            trial_paths=paths, task_env_config=EnvironmentConfig(**task['resources']))
    if os.environ.get('TPE_REMOTE_DOCKER') == '1':
        env.arm = data.get('arm', 'control')
    await env.start(force_build=False)
    try:
        r = await env.exec('mkdir -p /workspace /output; chown -R 65534:65534 /workspace /output', user='root', timeout_sec=30)
        if r.return_code:
            raise RuntimeError('SolverDirectorySetupFailed')
        SESSIONS[sid] = {'env': env, 'task': task, 'lock': asyncio.Lock(), 'snapshots': [], 'stage': None}
        save(paths.trial_dir / 'owned-session.json', {'id': sid, 'task': task['id'], 'created_at': time.time(), 'controller_pid': os.getpid()})
        return {'session': sid}
    except BaseException:
        await env.stop(delete=True)
        raise


async def snapshot(sid):
    s = SESSIONS[sid]
    target = ROOT / 'outputs/snapshots' / sid / uuid.uuid4().hex
    output = target / 'output'
    output.mkdir(parents=True)
    # Pausing the owned container also freezes background children during capture.
    await s['env']._run_docker_compose_command(['pause'], check=True)
    try:
        await s['env'].download_dir('/output', output)
    finally:
        await s['env']._run_docker_compose_command(['unpause'], check=True)
    manifest = []
    total = 0
    for p in sorted(output.rglob('*')):
        if p.is_symlink():
            raise RuntimeError('SymlinkInCandidateArtifacts')
        if p.is_file():
            total += p.stat().st_size
            if total > 1024 ** 3:
                raise RuntimeError('CandidateArtifactLimit')
            manifest.append({'path': p.relative_to(output).as_posix(), 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    identity = sid + ':' + digest
    if identity not in SNAPSHOTS:
        SNAPSHOTS[identity] = {'output': output, 'manifest': manifest, 'task': s['task']['id'], 'session': sid, 'cache': {}}
    save(target / 'manifest.json', {'candidate': identity, 'files': manifest, 'stage': s['stage']})
    s['snapshots'].append(identity)
    return {'candidate': identity, 'sha256': digest, 'files': [m['path'] for m in manifest], 'bytes': total}


def grade(data):
    sid, identity, uid = data['session'], data['candidate'], data['unit']
    s = SESSIONS[sid]
    unit = next(u for u in s['task']['units'] if u['id'] == uid)
    item = SNAPSHOTS.get(identity)
    if item is None or item['session'] != sid or item['task'] != s['task']['id']:
        return {'valid': True, 'outcome': 'rejected', 'parsed': False, 'passed': False, 'candidate': identity}
    for m in item['manifest']:
        p = item['output'] / m['path']
        if not p.is_file() or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest() != m['sha256']:
            return {'valid': False, 'outcome': 'grader_error', 'errorType': 'FrozenCandidateChanged'}
    if uid not in item['cache']:
        result = evaluate(ROOT / 'data/private', unit, item['output'])
        if result['valid']:
            item['cache'][uid] = result
        save(item['output'].parent / (uid + '.grade.json'), result)
    return {**item['cache'].get(uid, result if 'result' in locals() else {}), 'candidate': identity}


async def dispatch(op, data):
    if op in {'resources', 'admit', 'release'} and os.environ.get('TPE_REMOTE_DOCKER') == '1':
        return admission(op, data)
    if op == 'create':
        return await create(data)
    if op == 'catalog':
        return {'parents': len(CATALOG), 'units': sum(len(t['units']) for t in CATALOG.values())}
    s = SESSIONS[data['session']]
    async with s['lock']:
        if op == 'stage':
            unit = next(u for u in s['task']['units'] if u['id'] == data['unit'])
            work = ROOT / 'data/public' / s['task']['id'] / 'workdir' / unit['id']
            if work.exists():
                await s['env'].upload_dir(work, '/workspace')
                await s['env'].exec('chown -R 65534:65534 /workspace', user='root', timeout_sec=30)
            s['stage'] = unit['id']
            return {'ready': True}
        if op == 'compute':
            timeout = min(90, max(1, int(data.get('timeout', 60))))
            command = str(data['command'])
            start = time.time()
            try:
                # Docker client termination does not kill docker-exec children.
                # Enforce the limit inside Linux, including its process group.
                wrapped = f'timeout --signal=TERM --kill-after=2s {timeout}s bash -lc {shlex.quote(command)}'
                r = await s['env'].exec(wrapped, cwd='/workspace', user='65534:65534', timeout_sec=timeout + 12)
                result = {'stdout': (r.stdout or '')[-30000:], 'stderr': (r.stderr or '')[-15000:], 'exitCode': r.return_code}
                if r.return_code in (124, 137):
                    result['stderr'] += '\nTool execution time limit reached.'
            except (asyncio.TimeoutError, RuntimeError):
                await s['env'].exec('pkill -KILL -u 65534 || true', user='root', timeout_sec=10)
                raise
            directory = ROOT / 'outputs/tools' / data['session']
            directory.mkdir(parents=True, exist_ok=True)
            save(directory / (str(time.time_ns()) + '.json'), {'command': command, 'result': result, 'seconds': time.time() - start, 'unit': s['stage']})
            return result
        if op == 'snapshot':
            return await snapshot(data['session'])
        if op == 'grade':
            return grade(data)
        if op == 'dispose':
            await s['env'].stop(delete=True)
            s['disposed'] = True
            return {'disposed': True}
        raise RuntimeError('UnknownOperation')


async def handler(request):
    if request.headers.get('x-tpe-token') != TOKEN:
        raise web.HTTPUnauthorized()
    try:
        return web.json_response(await dispatch(request.match_info['op'], await request.json()))
    except Exception as exc:
        # Detailed infrastructure diagnostics stay outside solver-visible responses.
        directory = ROOT / 'outputs/bridge-errors'
        save(directory / (str(time.time_ns()) + '.json'), {'type': type(exc).__name__, 'message': str(exc), 'operation': request.match_info['op']})
        return web.json_response({'valid': False, 'outcome': 'infrastructure_error', 'errorType': type(exc).__name__}, status=503)


async def main():
    app = web.Application(client_max_size=1024 ** 2)
    app.router.add_post('/{op}', handler)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    save(ROOT / 'outputs/bridge.json', {'pid': os.getpid(), 'url': f'http://127.0.0.1:{port}', 'token': TOKEN})
    print(json.dumps({'bridge_pid': os.getpid(), 'port': port}), flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        for s in SESSIONS.values():
            if not s.get('disposed'):
                await s['env'].stop(delete=True)
        await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
