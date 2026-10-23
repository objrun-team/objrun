"""No Bench content: real owned Docker actor and the production Node upload hook."""
import json,os,pathlib,sys,urllib.request
from docker_owned import OwnedDocker
from native_process import pin,capture
from server_local_image_cache import prepare_and_load

def main():
 plan=json.loads(pathlib.Path(sys.argv[1]).read_bytes())['plan'];out=pathlib.Path(sys.argv[2]);out.mkdir(exist_ok=False)
 from _bench_original_owned_guard import guard
 guard()
 reuse=plan.get('completedPreparationReuse')
 if reuse:
  for proof in reuse['proofPins']:assert pin(proof['path'])==proof
  child=json.loads(pathlib.Path(reuse['childStdoutPin']['path']).read_bytes());assert child['protocol']=='bench-actual-child-boundary-probe-v1' and child['historyUnknownPreserved'] is True and child['modelCalls']==0
  frames=[json.loads(line) for line in pathlib.Path(reuse['imageStdoutPin']['path']).read_text().splitlines()]
  loaded={'result':frames[-1],'reuseProofPins':reuse['proofPins']}
  assert loaded['result']['complete'] is True and loaded['result']['image']==plan['baseImageId'] and loaded['result']['before']==loaded['result']['after']
 elif plan.get('childProbeConfigPin'):
  config=plan['childProbeConfigPin'];assert pin(config['path'])==config
  probe=capture([sys.executable,'-B',str(pathlib.Path(__file__).with_name('python_child_entry.py')),'--config',config['path'],'--original-script',str(pathlib.Path(__file__).with_name('infrastructure_child_probe.py'))],out/'actual-child-boundary',180,env=dict(os.environ))
  assert probe['pid'] and probe['incarnation'] and probe['closeObserved'] and probe['exitCode']==0 and not probe['error'] and not probe['timedOut'],probe
  (out/'child-boundary.json').write_text(json.dumps(probe,indent=2))
 if not reuse:loaded=prepare_and_load(plan['sshExecutablePin'],plan['baseImageId'],int(os.environ['NOVAEVE_RESOURCE_LEASE_PID']),out/'server-image-load')
 expected=json.loads(pathlib.Path(plan['baseInspectPin']['path']).read_text(encoding='utf-8-sig'))
 assert all(loaded['result']['after'][k]==expected[k] for k in ('Id','RootFS','Os','Architecture'))
 assert all(loaded['result']['after']['Config'].get(k)==v for k,v in expected['Config'].items())
 (out/'image-load.json').write_text(json.dumps(loaded,indent=2))
 native=OwnedDocker(out/'owned');cid=None;result={'modelCalls':0,'gradeCalls':0,'referenceCalls':0,'complete':False}
 try:
  cid,actor,_=native.create('infrastructure-acceptance',plan['baseImageId'],'/bin/sh',['-c','exec sleep infinity'],network='none',memory_mb=2048,cpus=1)
  native.start(cid)
  node=pathlib.Path(plan['nodePin']['path']);assert pin(node)==plan['nodePin']
  upload=native.upload(node,cid,'/rt-node')
  for asset in plan['libraryPins']:
   assert pin(asset['path'])==asset
   native.upload(pathlib.Path(asset['path']),cid,'/'+pathlib.Path(asset['path']).name)
  native.execute(cid,['/bin/chmod','0755','/rt-node'])
  hashed=native.execute(cid,['/usr/bin/sha256sum','/rt-node']);assert native.text(hashed).split()[0]==plan['nodePin']['sha256']
  ran=native.execute(cid,['/bin/sh','-c','LD_LIBRARY_PATH=/ /rt-node --version']);assert native.text(ran)=='v22.22.2'
  result.update(cid=cid,upload=upload,nodeHashReceipt=hashed,nodeRunReceipt=ran,complete=True)
 finally:
  if cid:
   native.remove(cid)
   try:urllib.request.urlopen('http://127.0.0.1:18750/containers/'+cid+'/json',timeout=5);raise AssertionError('actor_still_present')
   except urllib.error.HTTPError as e:assert e.code==404
  native.db.execute('PRAGMA wal_checkpoint(TRUNCATE)');native.db.close()
  result['actorClosed']=cid is not None
  (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
 assert result['complete'] and result['actorClosed']
 print(json.dumps({'complete':True,'resultPin':pin(out/'result.json')}))

if __name__=='__main__':main()
