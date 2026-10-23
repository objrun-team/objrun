"""Trusted pytest reporter: distinct nodeids and every setup/call/teardown are kept append-only."""
import base64, hashlib, json
from pathlib import Path
class NodeidPhaseReporter:
 def __init__(self):self.collected=[];self.reports=[];self.collection_errors=[]
 def pytest_collection_finish(self,session):self.collected=[item.nodeid for item in session.items]
 def pytest_collectreport(self,report):
  if report.failed:self.collection_errors.append({'nodeid':report.nodeid,'outcome':report.outcome})
 def pytest_runtest_logreport(self,report):self.reports.append({'nodeid':report.nodeid,'when':report.when,'outcome':report.outcome,'duration':report.duration,'wasxfail':getattr(report,'wasxfail',None)})
 def ledger(self):return {'protocol':'bench-pytest-nodeid-phase-ledger-v1','collected':self.collected,'reports':self.reports,'collectionErrors':self.collection_errors,'sourceSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

def validate_ledger(ledger,expected,exit_code):
 assert ledger['protocol']=='bench-pytest-nodeid-phase-ledger-v1' and ledger['collectionErrors']==[]
 collected=ledger['collected'];assert len(collected)==len(set(collected))==len(expected) and {n.split('::')[-1] for n in collected}==set(expected),'complete original collection required'
 seen={n:{} for n in collected}
 for report in ledger['reports']:
  assert report['nodeid'] in seen and report['when'] in ['setup','call','teardown'] and report['outcome'] in ['passed','failed','skipped'] and report.get('wasxfail') is None
  phases=seen[report['nodeid']];assert report['when'] not in phases,'duplicate nodeid phase';phases[report['when']]=report['outcome']
 for node,phases in seen.items():assert set(phases)=={'setup','call','teardown'} and phases['setup']=='passed' and phases['teardown']=='passed' and phases['call'] in ['passed','failed'],'complete case phases required'
 passed=sum(p['call']=='passed' for p in seen.values());failed=len(seen)-passed;assert exit_code==(1 if failed else 0),'original exit/phase outcome mismatch'
 return {'complete':True,'total':len(seen),'passed':passed,'failed':failed,'tests':[{'nodeid':n,'phases':seen[n]} for n in collected]}
