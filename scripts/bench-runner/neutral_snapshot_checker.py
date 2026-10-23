"""Trusted independent fixture assertions; contains no Bench task content."""
import argparse,hashlib,json,pathlib,runpy
p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args();c=json.loads(pathlib.Path(a.config).read_bytes())
assert c['protocol']=='tb12-private-checker-config-v1' and c['taskId']=='neutral-snapshot-control'
assert hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()==c['checkerSourceSha256']
for name,digest in c['officialTestHashes'].items():assert hashlib.sha256((pathlib.Path('/tests')/name).read_bytes()).hexdigest()==digest
passed=True
try:runpy.run_path('/tests/test_outputs.py')['test_neutral_data']()
except AssertionError:passed=False
r={'protocol':'tb12-private-checker-result-v1','invocationId':c['invocationId'],'taskId':c['taskId'],'exitCode':0 if passed else 1,'reward':int(passed),'ctrf':{'results':{'tests':[{'name':'test_neutral_data','status':'passed' if passed else 'failed'}]}},'neutralContentOnly':True}
print('TB12_RESULT:'+json.dumps(r),flush=True)
