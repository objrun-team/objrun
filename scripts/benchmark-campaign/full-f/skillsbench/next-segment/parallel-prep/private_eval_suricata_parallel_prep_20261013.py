"""Version2 trusted data verifier: retain original pytest setup failures."""
import contextlib
import base64
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import sys
import shutil
import time

def main():
    assert sys.flags.isolated == 1 and sys.dont_write_bytecode
    assert os.environ.get('PYTEST_DISABLE_PLUGIN_AUTOLOAD') == '1'
    trusted = json.loads(Path('/opt/objrun/trusted.json').read_text())
    assert os.getcwd()==trusted['workingDirectory']
    # This new private tmpfs replay replaces Docker cp into a read-only root.
    # Fixtures originate solely from this pristine immutable image. Candidate
    # data arrive as bounded opaque bytes, never an interpreter or environment.
    shutil.copytree(trusted['fixtureSource'],trusted['fixtureDestination'],dirs_exist_ok=True)
    raw=sys.stdin.buffer.readline(12*1024**2+1)
    assert len(raw)<=12*1024**2
    incoming=json.loads(raw or b'{"artifacts":[]}')
    assert set(incoming)=={'artifacts','session'} and len(incoming['artifacts'])<=1
    for artifact in incoming['artifacts']:
        assert set(artifact)=={'path','base64','sha256'} and artifact['path']==trusted['outputPath']
        body=base64.b64decode(artifact['base64'],validate=True)
        assert len(body)<=8*1024**2 and hashlib.sha256(body).hexdigest()==artifact['sha256']
        destination=Path(artifact['path'])
        assert not destination.is_symlink()
        with destination.open('wb') as stream:stream.write(body)
        destination.chmod(0o600)
        assert destination.stat().st_mode & 0o777 == 0o600
    for pin in trusted['files']:
        assert hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest() == pin['sha256']
    for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS'):
        os.environ.pop(key, None)
    import pytest
    entries = [e for e in importlib.metadata.distribution('pytest-json-ctrf').entry_points if e.group == 'pytest11']
    assert len(entries) == 1
    class Witness:
        def __init__(self): self.nodes=[]; self.reports=[]; self.errors=[]
        def pytest_collection_finish(self, session): self.nodes=[x.nodeid for x in session.items]
        def pytest_collectreport(self, report):
            if report.failed or report.skipped: self.errors.append({'nodeId':report.nodeid, 'outcome':report.outcome})
        def pytest_runtest_logreport(self, report):
            self.reports.append({'nodeId':report.nodeid, 'phase':report.when, 'outcome':report.outcome, 'wasXfail':getattr(report,'wasxfail',None),'skipReason':str(report.longrepr[2]) if report.skipped and isinstance(report.longrepr,tuple) else None})
    witness=Witness(); captured=io.StringIO(); began=time.monotonic()
    args=['-c','/opt/objrun/empty.ini','--confcutdir=/verifier','--ctrf','/logs/verifier/ctrf.json','/verifier/test_outputs.py','-rA']
    collect='--collect' in sys.argv
    if collect: args += ['--collect-only','-q']
    sys.path.insert(0,'/opt/objrun')
    from suricata_private_bridge_parallel_prep_20261013 import Bridge
    def callback(request):
        sys.__stdout__.write(json.dumps({'kind':'suricata_callback','request':request},separators=(',',':'))+'\n');sys.__stdout__.flush()
        reply=sys.stdin.buffer.readline(34*1024**2+1)
        assert len(reply)<=34*1024**2 and reply.endswith(b'\n')
        return json.loads(reply)
    bridge=Bridge(callback,incoming['session'])
    with bridge, contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        code=int(pytest.main(args,plugins=[entries[0].load(),witness]))
    for pin in trusted['files']:
        assert hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest() == pin['sha256']
    phases={node:{} for node in witness.nodes}; issues=[]
    for report in witness.reports:
        if report['nodeId'] not in phases or report['phase'] in phases[report['nodeId']]: issues.append('duplicate_or_foreign_report'); continue
        phases[report['nodeId']][report['phase']]=report
        if report['wasXfail'] is not None: issues.append('xfail_or_xpass')
    def original_sales_skip(node, values):
        if trusted['taskId']!='sales-pivot-analysis':return False
        expected={'Population by State-sum-None':'Population by State','Earners by State-sum-None':'Earners by State','Regions by State-count-None':'Regions by State'}
        matches=[sheet for case,sheet in expected.items() if node.endswith('::TestPivotTableConfiguration::test_pivot_col_field['+case+']')]
        return (len(matches)==1 and set(values)=={'setup','call','teardown'}
                and values['setup']['outcome']=='passed' and values['teardown']['outcome']=='passed'
                and values['call']['outcome']=='skipped' and values['call']['wasXfail'] is None
                and values['call'].get('skipReason')=="Skipped: '"+matches[0]+"' is not a matrix pivot")
    def original_exoplanet_negative_skip(node, values):
        if trusted['taskId']!='exoplanet-detection-period' or code!=1:return False
        prefix='::TestExoplanetPeriod::'
        expected={prefix+n for n in ('test_period_file_exists','test_period_is_valid_number','test_period_value_correct','test_period_format')}
        first=phases.get(prefix+'test_period_file_exists',{})
        missing=(set(first)=={'setup','call','teardown'} and first['setup']['outcome']=='passed'
                 and first['call']['outcome']=='failed' and first['call']['wasXfail'] is None
                 and first['teardown']['outcome']=='passed')
        return (set(phases)==expected and missing and not incoming['artifacts']
                and node in expected-{prefix+'test_period_file_exists'}
                and set(values)=={'setup','call','teardown'}
                and values['setup']['outcome']=='passed' and values['teardown']['outcome']=='passed'
                and values['call']['outcome']=='skipped' and values['call']['wasXfail'] is None
                and values['call'].get('skipReason')=='Skipped: Period file not found')
    if not collect:
        for node,values in phases.items():
            ordinary_call=set(values)=={'setup','call','teardown'} and values['setup']['outcome']=='passed' and values['call']['outcome'] in ('passed','failed') and values['teardown']['outcome']=='passed'
            failed_setup=set(values)=={'setup','teardown'} and values['setup']['outcome']=='failed' and values['teardown']['outcome']=='passed'
            # A genuinely missing/invalid candidate output can fail a fixture.
            # Retain that actual setup error; never invent a call report. All
            # collected nodes still need an attempted setup and final teardown.
            if not (ordinary_call or failed_setup or original_sales_skip(node,values) or original_exoplanet_negative_skip(node,values)):issues.append('incomplete_or_skipped_test')
    if witness.errors: issues.append('collection_errors')
    passed=sum(r['phase']=='call' and r['outcome']=='passed' for r in witness.reports)
    failed=sum(r['phase']=='call' and r['outcome']=='failed' for r in witness.reports)
    errored=sum(values.get('setup',{}).get('outcome')=='failed' for values in phases.values())
    original_skipped=sum(original_sales_skip(node,values) or original_exoplanet_negative_skip(node,values) for node,values in phases.items())
    complete=bool(witness.nodes) and len(set(witness.nodes))==len(witness.nodes) and not issues and code in (0,1) and (collect or passed+failed+errored+original_skipped==len(witness.nodes))
    result={'protocol':'skillsbench-full-f-private-data-evaluation-v2','taskId':trusted['taskId'],
        'mode':'collect' if collect else 'grade','nodeIds':witness.nodes,'reports':witness.reports,'collectionErrors':witness.errors,
        'pytestExitCode':code,'complete':complete,'validationIssues':issues,'passedTests':passed,'failedTests':failed,'errorTests':errored,'completedTests':passed+failed+errored+original_skipped,'originalConditionalSkippedTests':original_skipped,
        'reward':None if collect or not complete else round(passed/(passed+failed),3) if trusted['taskId']=='lab-unit-harmonization' else int(code==0),
        'candidateExecutablesUsed':False,'candidateSnapshotUsed':False,'suricataSeparateSandbox':True,'suricataCallbackCount':bridge.serial,'network':'none','hostBinds':False,
        'pythonVersion':sys.version,'pythonPath':sys.executable,'pythonSha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        'installedPackages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()},
        'elapsedSeconds':time.monotonic()-began,'rawPytestOutput':captured.getvalue(),
        'artifactInputs':[{'path':r['path'],'sha256':r['sha256']} for r in incoming['artifacts']]}
    print(json.dumps(result,ensure_ascii=False,separators=(',',':')))

if __name__=='__main__':main()
