"""Real original snapshot/reference phase callables over independent fixture bytes."""
import argparse,json,pathlib,os,time,sqlite3,urllib.request,urllib.error
from native_process import pin
from server_owned_asset import operate_owned_asset
from native_snapshot_control import run_control
from docker_owned import OwnedDocker
p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--output',required=True);a=p.parse_args();r=json.loads(pathlib.Path(a.request).read_bytes())
out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=False)
limit=json.loads(pathlib.Path(r['absoluteDeadlineFile']).read_bytes());assert limit['pid']==int(os.environ['NOVAEVE_RESOURCE_LEASE_PID'])
request=json.loads(pathlib.Path(r['runtimeBuildRequestPin']['path']).read_bytes());assert pin(r['runtimeBuildRequestPin']['path'])==r['runtimeBuildRequestPin'];request['deadline']=limit['deadline']/1000
runtime=None;rows=[];native=OwnedDocker(out/'cleanup-native')
try:
 built=operate_owned_asset(request,out/'runtime-build');runtime=built['result']['image']
 base={**r['controlTemplate'],'privateBaseImage':runtime}
 for label in ['missing-output','reference','wrong-output']:
  if label=='reference':
   reference=run_control({**base,'phase':'reference','label':label,'phaseSeconds':30},out/'reference-phase');rows.append(reference)
   candidate=reference['referenceImage']
  else:candidate=base['candidateImage']
  row=run_control({**base,'phase':'grade','label':label,'phaseSeconds':60,'candidateImage':candidate,'expectedReward':int(label=='reference'),'plantFiles':base['plantFiles'] if label=='wrong-output' else []},out/(label+'-grade'));rows.append(row)
 assert [x['actualReward'] for x in rows if x['phase']=='grade']==[0,1,0]
 result={'complete':True,'neutralContentOnly':True,'modelCalls':0,'gradeCalls':0,'referenceCalls':0,'actualNeutralReferenceFixtureExecutions':1,'actualOriginalSnapshotFixtureCalls':3,'fixtureDecisions':[0,1,0],'runtimeBuildProof':built,'rows':rows}
finally:
 # Only exact images created by these owned phase ledgers and this fresh runtime.
 images=[]
 for dbfile in sorted(out.rglob('owned-native.sqlite'),reverse=True):
  if dbfile.parent==out/'cleanup-native':continue
  db=sqlite3.connect(dbfile);assert db.execute('select count(*) from actor where closed=0').fetchone()[0]==0
  images += [x[0] for x in db.execute('select id from image')];db.close()
 for image in dict.fromkeys(images+([runtime] if runtime else [])):
  native.checked(['image','rm','--no-prune',image])
  try:urllib.request.urlopen(os.environ['DOCKER_HOST'].replace('tcp:','http:')+'/images/'+image+'/json',timeout=5);raise AssertionError('neutral_phase_image_still_present')
  except urllib.error.HTTPError as error:assert error.code==404
 native.close()
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
