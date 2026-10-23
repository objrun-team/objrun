"""Independent fixture assertions; never imports candidate code."""
import argparse,json,pathlib,hashlib
p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args();c=json.loads(pathlib.Path(a.config).read_bytes())
assert c['taskId']=='neutral-snapshot-control' and hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()==c['checkerSourceSha256']
for name,digest in c['officialTestHashes'].items():assert hashlib.sha256((pathlib.Path('/tests')/name).read_bytes()).hexdigest()==digest
rows=c['caffeWorkerResult']['rows'];passed=len(rows)==2 and all(x['exitCode']==0 and x['stdout'].startswith('NEUTRAL-WORKER-VALID:') for x in rows)
r=dict(protocol='tb12-private-checker-result-v1',invocationId=c['invocationId'],taskId=c['taskId'],exitCode=0 if passed else 1,reward=int(passed),ctrf={'results':{'tests':[{'name':'test_neutral_worker','status':'passed'if passed else 'failed'}]}})
print('TB12_RESULT:'+json.dumps(r),flush=True)
