"""Immutable multi-file data replay; preserve all original pytest phases."""
import contextlib
import base64
import hashlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import sys
import shutil
import time

def safe_output(path,policies):
    assert isinstance(path,str) and path.startswith('/') and '\\' not in path and '\x00' not in path
    assert all(p not in ('','.','..') for p in path.split('/')[1:])
    for root in ('/verifier','/oracle','/logs','/opt','/usr','/bin','/sbin','/lib','/etc','/proc','/sys','/dev'):
        assert path!=root and not path.startswith(root+'/')
    assert Path(path).suffix.lower() not in ('.py','.pyc','.sh','.so','.exe','.dll','.js','.mjs','.jar','.class','.wasm','.ps1','.bat','.cmd')
    allowed=[p for p in policies if path==p['path'] and p['kind']=='file' or p['kind']=='directory' and path.startswith(p['path']+'/')]
    assert len(allowed)==1
    return allowed[0]

def main():
    assert sys.flags.isolated == 1 and sys.dont_write_bytecode
    assert os.environ.get('PYTEST_DISABLE_PLUGIN_AUTOLOAD') == '1'
    trusted = json.loads(Path('/opt/objrun/trusted.json').read_text())
    assert trusted['taskId']=='civ6-adjacency-optimizer'
    assert os.getcwd()==trusted['workingDirectory']
    # This new private tmpfs replay replaces Docker cp into a read-only root.
    # Fixtures originate solely from this pristine immutable image. Candidate
    # data arrive as bounded opaque bytes, never an interpreter or environment.
    for fixture in trusted['fixtureCopies']:
        shutil.copytree(fixture['source'],fixture['destination'],dirs_exist_ok=True)
    maximum=trusted['maximumArtifactBytes'];maximum_files=trusted['maximumArtifactFiles']
    raw_bound=maximum*4//3+maximum_files*1024+1024**2
    raw=sys.stdin.buffer.read(raw_bound+1)
    assert len(raw)<=raw_bound
    incoming=json.loads(raw or b'{"artifacts":[]}')
    assert set(incoming)=={'artifacts'} and len(incoming['artifacts'])<=maximum_files
    seen=set();total=0
    for artifact in incoming['artifacts']:
        assert set(artifact)=={'path','base64','sha256'} and artifact['path'] not in seen
        approved=safe_output(artifact['path'],trusted['outputPolicies']);seen.add(artifact['path'])
        body=base64.b64decode(artifact['base64'],validate=True)
        total+=len(body)
        assert len(body)<=8*1024**2 and total<=maximum and hashlib.sha256(body).hexdigest()==artifact['sha256']
        assert not body.startswith((b'#!',b'\x7fELF',b'MZ',b'\x00asm'))
        destination=Path(artifact['path'])
        assert not destination.is_symlink()
        destination.parent.mkdir(parents=True,exist_ok=True)
        for parent in destination.parents:assert not parent.is_symlink()
        with destination.open('wb') as stream:stream.write(body)
        destination.chmod(0o644)
    for pin in trusted['files']:
        assert hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest() == pin['sha256']
    for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS'):
        os.environ.pop(key, None)
    import pytest
    # These paths contain only the immutable original verifier, never candidate modules.
    sys.path.insert(0,'/verifier');sys.path.insert(0,'/verifier/src')
    entries = [e for e in importlib.metadata.distribution('pytest-json-ctrf').entry_points if e.group == 'pytest11']
    assert len(entries) == 1
    class Witness:
        def __init__(self): self.nodes=[]; self.reports=[]; self.errors=[]
        def pytest_collection_finish(self, session): self.nodes=[x.nodeid for x in session.items]
        def pytest_collectreport(self, report):
            if report.failed or report.skipped: self.errors.append({'nodeId':report.nodeid, 'outcome':report.outcome})
        def pytest_runtest_logreport(self, report):
            self.reports.append({'nodeId':report.nodeid, 'phase':report.when, 'outcome':report.outcome, 'wasXfail':getattr(report,'wasxfail',None),'skipReason':str(report.longrepr) if report.skipped else None})
    witness=Witness(); captured=io.StringIO(); began=time.monotonic()
    args=['-c','/opt/objrun/empty.ini','--confcutdir=/verifier','--ctrf','/logs/verifier/ctrf.json','/verifier/test_outputs.py','-rA']
    collect='--collect' in sys.argv
    if collect: args += ['--collect-only','-q']
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        code=int(pytest.main(args,plugins=[entries[0].load(),witness]))
    for pin in trusted['files']:
        assert hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest() == pin['sha256']
    phases={node:{} for node in witness.nodes}; issues=[]
    for report in witness.reports:
        if report['nodeId'] not in phases or report['phase'] in phases[report['nodeId']]: issues.append('duplicate_or_foreign_report'); continue
        phases[report['nodeId']][report['phase']]=report
        if report['wasXfail'] is not None: issues.append('xfail_or_xpass')
    if not collect:
        for values in phases.values():
            ordinary_call=set(values)=={'setup','call','teardown'} and values['setup']['outcome']=='passed' and values['call']['outcome'] in ('passed','failed') and values['teardown']['outcome']=='passed'
            failed_setup=set(values)=={'setup','teardown'} and values['setup']['outcome']=='failed' and values['teardown']['outcome']=='passed'
            # A genuinely missing/invalid candidate output can fail a fixture.
            # Retain that actual setup error; never invent a call report. All
            # collected nodes still need an attempted setup and final teardown.
            original_missing_output_skip=set(values)=={'setup','teardown'} and values['setup']['outcome']=='skipped' and values['teardown']['outcome']=='passed' and 'Solution file not found:' in str(values['setup'].get('skipReason'))
            if not (ordinary_call or failed_setup or original_missing_output_skip):issues.append('incomplete_or_skipped_test')
    if witness.errors: issues.append('collection_errors')
    passed=sum(r['phase']=='call' and r['outcome']=='passed' for r in witness.reports)
    failed=sum(r['phase']=='call' and r['outcome']=='failed' for r in witness.reports)
    errored=sum(values.get('setup',{}).get('outcome')=='failed' for values in phases.values())
    skipped=sum(values.get('setup',{}).get('outcome')=='skipped' for values in phases.values())
    complete=bool(witness.nodes) and len(set(witness.nodes))==len(witness.nodes) and not issues and code in (0,1) and (collect or passed+failed+errored+skipped==len(witness.nodes))
    score_path=Path('/logs/verifier/scores/scenario_3.txt');score=0.0
    if score_path.exists():
        assert score_path.is_file() and not score_path.is_symlink() and score_path.stat().st_size<=1024
        try:score=float(score_path.read_text().strip())
        except ValueError:score=0.0
    assert math.isfinite(score) and 0<=score<=1
    official_reward=float(f'{score:.3f}')
    result={'protocol':'skillsbench-full-f-private-multi-data-evaluation-v1','taskId':trusted['taskId'],
        'mode':'collect' if collect else 'grade','nodeIds':witness.nodes,'reports':witness.reports,'collectionErrors':witness.errors,
        'pytestExitCode':code,'complete':complete,'validationIssues':issues,'passedTests':passed,'failedTests':failed,'errorTests':errored,'skippedTests':skipped,'completedTests':passed+failed+errored+skipped,
        'reward':None if collect or not complete else official_reward,'officialRewardSource':'original private score file, rounded to three decimals','officialShellExitCode':0,
        'candidateExecutablesUsed':False,'candidateSnapshotUsed':False,'network':'none','hostBinds':False,
        'pythonVersion':sys.version,'pythonPath':sys.executable,'pythonSha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        'installedPackages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()},
        'elapsedSeconds':time.monotonic()-began,'rawPytestOutput':captured.getvalue(),
        'artifactInputs':[{'path':r['path'],'sha256':r['sha256']} for r in incoming['artifacts']]}
    print(json.dumps(result,ensure_ascii=False,separators=(',',':')))

if __name__=='__main__':main()
