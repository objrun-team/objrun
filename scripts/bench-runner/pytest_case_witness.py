"""Preserve exact pytest node IDs independently of CTRF's parametrization merging."""
import hashlib,json,os,pathlib

def _digest(value):
 return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def run_with_witness(argv):
 import pytest
 class Witness:
  def __init__(self):self.collected=[];self.reports=[]
  def pytest_collection_finish(self,session):self.collected=[item.nodeid for item in session.items]
  def pytest_runtest_logreport(self,report):
   self.reports.append({'nodeid':report.nodeid,'when':report.when,'outcome':report.outcome,'wasxfail':bool(getattr(report,'wasxfail',False))})
 plugin=Witness();code=int(pytest.main(argv,plugins=[plugin]))
 value={'protocol':'bench-pytest-case-witness-v1','pytestVersion':pytest.__version__,'collected':plugin.collected,'reports':plugin.reports,'exitCode':code}
 return code,{**value,'sha256':_digest(value)}

def validate_case_identity(result,expected):
 """The original four-case requirement remains exact; raw CTRF is never rewritten."""
 tests=result['ctrf']['results']['tests'];expected=set(expected)
 names=[x['name'].split('::')[-1] for x in tests]
 if len(tests)==len(expected) and set(names)==expected:return
 assert result['packages']['pytest']=='8.4.1' and result['packages']['pytest-json-ctrf']=='0.3.5','unsupported_ctrf_format'
 collapsed={name.split('[')[0] for name in expected}
 assert len(tests)==len(collapsed) and set(names)==collapsed and len(names)==len(set(names)),'ctrf_case_identity_mismatch'
 assert all(x['status'] in ('passed','failed') for x in tests)
 w=result['pytestCaseWitness'];payload={k:v for k,v in w.items() if k!='sha256'}
 assert w['protocol']=='bench-pytest-case-witness-v1' and w['sha256']==_digest(payload)
 assert w['pytestVersion']=='8.4.1' and w['exitCode']==result['exitCode']
 collected=w['collected'];assert len(collected)==len(expected) and len(set(collected))==len(expected)
 assert {x.split('::')[-1] for x in collected}==expected
 reports=w['reports'];assert len(reports)==3*len(expected)
 calls=[]
 for nodeid in collected:
  rows=[x for x in reports if x['nodeid']==nodeid]
  assert [x['when'] for x in rows]==['setup','call','teardown']
  assert all(x['wasxfail'] is False for x in rows) and rows[0]['outcome']==rows[2]['outcome']=='passed'
  assert rows[1]['outcome'] in ('passed','failed');calls.append(rows[1]['outcome'])
 assert all(x['nodeid'] in collected for x in reports)
 assert result['reward']==int(all(x=='passed' for x in calls))
 # CTRF 0.3.5 overwrites each parameter group's outcome with its last case.
 last={nodeid.split('::')[-1].split('[')[0]:status for nodeid,status in zip(collected,calls)}
 assert all(x['status']==last[x['name'].split('::')[-1]] for x in tests)

def stage_checker_witness(native,checker,original,output):
 """Stage the pinned original runner with only an additive report witness."""
 from native_process import pin
 config=json.loads(pathlib.Path(os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']).read_bytes())
 assert hashlib.sha256(pathlib.Path(os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']).read_bytes()).hexdigest()==os.environ['NOVAEVE_PYTHON_MAPPING_SHA256']
 binding=config['pytestCaseWitness'];original=pathlib.Path(original);output=pathlib.Path(output)
 assert pin(original)==binding['originalCheckerPin'] and pin(pathlib.Path(__file__))==binding['helperPin']
 raw=original.read_bytes();source=raw.decode()
 before="exit_code=int(pytest.main(['-p','ctrf.main','--ctrf','/tmp/ctrf.json','/tests/test_outputs.py','-rA','-o','cache_dir=/tmp/pipeline-pytest-cache']))"
 after="import pytest_case_witness as _case_witness;assert hashlib.sha256(Path(_case_witness.__file__).read_bytes()).hexdigest()=="+repr(binding['helperPin']['sha256'])+";exit_code,case_witness=_case_witness.run_with_witness(['-p','ctrf.main','--ctrf','/tmp/ctrf.json','/tests/test_outputs.py','-rA','-o','cache_dir=/tmp/pipeline-pytest-cache'])"
 assert source.count(before)==1;source=source.replace(before,after)
 before="'collectOnly':False,'exitCode':exit_code";assert source.count(before)==1;source=source.replace(before,"'collectOnly':False,'pytestCaseWitness':case_witness,'exitCode':exit_code")
 target=output/'case-witness-checker.py';assert not target.exists();target.write_text(source)
 staged=output/'pytest_case_witness.py';assert not staged.exists();staged.write_bytes(pathlib.Path(__file__).read_bytes());assert pin(staged)['sha256']==binding['helperPin']['sha256']
 native.upload(staged,checker,'/opt/pipeline-checker/router/pytest_case_witness.py')
 (output/'case-witness-source.json').write_text(json.dumps({'original':pin(original),'helper':pin(pathlib.Path(__file__)),'derived':pin(target),'exactReplacements':2},indent=2)+'\n')
 return target
