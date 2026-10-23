"""Exercise actual Harbor containers, candidate immutability and session isolation."""
import json
from pathlib import Path
import urllib.request
import urllib.error
import time
from controls import reference

ROOT = Path(__file__).resolve().parents[1]


def call(op, **data):
    conf = json.loads((ROOT / 'outputs/bridge.json').read_text())
    req = urllib.request.Request(conf['url'] + '/' + op, data=json.dumps(data).encode(), headers={'content-type': 'application/json', 'x-tpe-token': conf['token']})
    try:
        return json.load(urllib.request.urlopen(req, timeout=900))
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode()) from e


def write_answer(session, unit):
    spec = json.loads((ROOT / 'data/private' / unit['id'] / 'grading_spec.json').read_text())
    text = reference(spec)
    script = 'from pathlib import Path; p=Path(' + repr('/output/' + unit['answer_path']) + '); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(' + repr(text) + ')'
    r = call('compute', session=session, command='python - <<\'PY\'\n' + script + '\nPY', timeout=30)
    assert r['exitCode'] == 0


def main():
    catalog = json.loads((ROOT / 'data/catalog.json').read_text())
    normal = next(t for t in catalog if t['id'] == 'axion-dielectric-conversion')
    first = call('create', task=normal['id'])['session']
    try:
        call('stage', session=first, unit=normal['units'][0]['id'])
        safety = call('compute', session=first, command="python - <<'PY'\nimport os,pathlib,json,numpy,scipy,sympy\nprint(json.dumps({'uid':os.getuid(),'tests':pathlib.Path('/tests').exists(),'private':pathlib.Path('/data/private').exists(),'api_keys':[k for k in os.environ if k.endswith('_API_KEY')],'numpy':numpy.__version__,'scipy':scipy.__version__,'sympy':sympy.__version__}))\nPY", timeout=30)
        assert safety['exitCode'] == 0
        security = json.loads(safety['stdout'])
        assert security['uid'] == 65534 and not security['tests'] and not security['private'] and not security['api_keys']
        # A real docker-exec timeout must kill nested children, retain partial
        # stdout, and remain an ordinary solver-visible tool result.
        timed = call('compute', session=first, command="echo before-timeout; bash -c 'sleep 3; touch /output/timeout-survivor'", timeout=1)
        assert timed['exitCode'] == 124 and 'before-timeout' in timed['stdout'], timed
        time.sleep(3)
        check = call('compute', session=first, command='test ! -e /output/timeout-survivor', timeout=5)
        assert check['exitCode'] == 0, check
        (ROOT / 'control/timeout-controls.json').write_text(json.dumps({'passed': True, 'timeout': timed, 'nested_child_stopped': True}, indent=2) + '\n')
        conf = json.loads((ROOT / 'outputs/bridge.json').read_text())
        try:
            urllib.request.urlopen(urllib.request.Request(conf['url'] + '/catalog', data=b'{}', headers={'content-type': 'application/json'}))
            raise AssertionError('UnauthenticatedBridgeAccepted')
        except urllib.error.HTTPError as e:
            assert e.code == 401
        (ROOT / 'control/auth-controls.json').write_text(json.dumps({'passed': True, 'unauthenticated_http_status': 401}) + '\n')
        write_answer(first, normal['units'][0])
        frozen = call('snapshot', session=first)['candidate']
        assert call('grade', session=first, candidate=frozen, unit=normal['units'][0]['id'])['passed']
        assert call('compute', session=first, command="printf 'BROKEN' > /output/final_answer.txt", timeout=10)['exitCode'] == 0
        changed = call('snapshot', session=first)['candidate']
        assert changed != frozen
        assert call('grade', session=first, candidate=frozen, unit=normal['units'][0]['id'])['passed']
        assert not call('grade', session=first, candidate=changed, unit=normal['units'][0]['id'])['passed']
    finally:
        call('dispose', session=first)
    second = call('create', task=normal['id'])['session']
    try:
        empty = call('snapshot', session=second)
        assert not empty['files']
        assert not call('grade', session=second, candidate=frozen, unit=normal['units'][0]['id'])['passed']
        write_answer(second, normal['units'][0])
        (ROOT / 'control/engine-fixture-session.json').write_text(json.dumps({'session': second, 'task': normal['id']}))
    except BaseException:
        call('dispose', session=second)
        raise
    compound = next(t for t in catalog if len(t['units']) == 4)
    sid = call('create', task=compound['id'])['session']
    try:
        for unit in compound['units']:
            call('stage', session=sid, unit=unit['id'])
            write_answer(sid, unit)
            snap = call('snapshot', session=sid)['candidate']
            assert call('grade', session=sid, candidate=snap, unit=unit['id'])['passed']
        listing = call('snapshot', session=sid)
        assert all(u['answer_path'] in listing['files'] for u in compound['units'])
    finally:
        call('dispose', session=sid)
    report = {'passed': True, 'actual_docker_containers': True,
              'adapter': 'remote owned Docker' if (ROOT / 'control/remote-runtime.json').exists() else 'Harbor',
              'security': security, 'immutable_snapshot': True,
              'fresh_independent_workspace': True, 'cross_session_candidate_rejected': True, 'four_stage_upload_and_grading': True}
    (ROOT / 'control/container-controls.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
