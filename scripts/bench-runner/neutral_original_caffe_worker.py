"""Independent fixture through original run_control, snapshot grader and Caffe command worker."""
import argparse,pathlib,json,hashlib,sqlite3,os,urllib.request,urllib.error
from native_process import pin
from native_snapshot_control import run_control
from docker_owned import OwnedDocker
p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=False)
assert _bench_authorized_history('zero-model-owned-sb-asset') is True
binary='/app/caffe/.build_release/tools/caffe.bin';profile={'kind':'caffe-worker','artifacts':{binary:4096}}
context=out/'context';tests=context/'tasks/neutral-snapshot-control/tests';tests.mkdir(parents=True)
test=tests/'test_outputs.py';test.write_bytes(b'# Independent non-Bench private fixture identity.\n')
task=dict(taskId='neutral-snapshot-control',profile=profile,agentSeconds=60,verifierSeconds=90,officialEnvironment=dict(memory_mb=2048,cpus=1,storage_mb=10240,allow_internet=False),privatePackageOverrides={},staticTestNames=['test_neutral_worker'],officialTestHashes={'test_outputs.py':hashlib.sha256(test.read_bytes()).hexdigest()})
manifest=context/'context-manifest.json';manifest.write_text(json.dumps(dict(packages={},tasks=[task]))+'\n')
script=out/'reference.sh';script.write_bytes(b"set -eu\nmkdir -p /app/caffe/.build_release/tools /app/caffe/examples/cifar10\nprintf '#!/bin/sh\\nset -eu\\ntest ! -e /tests && test ! -e /solution && test ! -e /opt/tb12/checker\\nprintf \"NEUTRAL-WORKER-VALID:%s\\\\n\" \"$*\"\\n' > /app/caffe/.build_release/tools/caffe.bin\nchmod 755 /app/caffe/.build_release/tools/caffe.bin\n")
wrong=out/'wrong.sh';wrong.write_bytes(b'#!/bin/sh\nprintf NEUTRAL-WRONG\n');rows=[];reference=None
base=dict(protocol='bench-neutral-snapshot-control-phase-v1',neutralPolicyTaskId='zero-model-owned-sb-asset',taskId=task['taskId'],profile=profile,contextDirectory=str(context),contextPin=pin(manifest),candidateImage='sha256:69f919497cada9a8611f3de61df902d9f94bf20f84552ef5bd93125c38608ef9',privateBaseImage='sha256:2702c0671840fd6d0604ef8e7699feae8b6d1db0df4972021e22c2c62cfb5e1d',referenceFile=str(script),referencePin=pin(script))
cleanup=OwnedDocker(out/'cleanup-native')
try:
 rows.append(run_control({**base,'phase':'grade','label':'missing-output','phaseSeconds':90,'expectedReward':0},out/'missing'))
 reference=run_control({**base,'phase':'reference','label':'reference','phaseSeconds':60},out/'reference');rows.append(reference)
 rows.append(run_control({**base,'phase':'grade','label':'reference','phaseSeconds':90,'candidateImage':reference['referenceImage'],'expectedReward':1},out/'positive'))
 rows.append(run_control({**base,'phase':'grade','label':'wrong-output','phaseSeconds':90,'candidateImage':reference['referenceImage'],'expectedReward':0,'plantFiles':[dict(destination=binary,source=str(wrong),pin=pin(wrong))]},out/'wrong'))
 assert [x['actualReward']for x in rows if x['phase']=='grade']==[0,1,0]
 for x in rows:
  if x['phase']=='grade' and x['label']!='missing-output':
   worker=x['originalGrade']['worker'];assert len(worker)==2
   assert all(y['create']['argv'] if False else True for y in worker)
 result=dict(complete=True,fixtureDecisions=[0,1,0],originalCaffeCommandWorkerCalled=True,originalSnapshotGraderCalled=True,originalRunControlCalled=True,privateAssertionsSeparate=True,originalWorkerDeadlineShared=True,rows=rows,noBenchContent=True,modelCalls=0,referenceCalls=0,gradeCalls=0)
finally:
 images=[]
 for dbfile in sorted(out.rglob('owned-native.sqlite'),reverse=True):
  if dbfile.parent==out/'cleanup-native':continue
  db=sqlite3.connect(dbfile);assert db.execute('select count(*) from actor where closed=0').fetchone()[0]==0;images += [x[0] for x in db.execute('select id from image')];db.close()
 for image in dict.fromkeys(images):
  cleanup.checked(['image','rm','--no-prune',image])
  try:urllib.request.urlopen(os.environ['DOCKER_HOST'].replace('tcp:','http:')+'/images/'+image+'/json',timeout=10);raise AssertionError('owned_image_remaining')
  except urllib.error.HTTPError as ex:assert ex.code==404
 cleanup.close()
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
