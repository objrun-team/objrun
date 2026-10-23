"""Read a pinned public base's package/source metadata in an owned offline actor."""
import argparse,json,pathlib,re
from docker_owned import OwnedDocker
p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--output',required=True);a=p.parse_args()
r=json.loads(pathlib.Path(a.request).read_bytes())
assert r['protocol']=='owned-base-apt-metadata-input-v1' and r['neutralNoBench'] is True
assert r['modelCalls']==r['gradeCalls']==r['referenceCalls']==0 and r['formalActivation'] is False
assert r['readOnlyActor'] is True and r['network']=='none' and re.fullmatch('sha256:[a-f0-9]{64}',r['baseImage'])
assert r['actorArgv'][:2]==['/bin/sh','-ec'] and len(r['actorArgv'])==3
out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=False);native=OwnedDocker(out/'native');cid=None
try:
 image=native.checked(['image','inspect',r['baseImage']]);actual=json.loads(native.text(image))[0];assert actual['Id']==r['baseImage']
 resource=r['resource'];cid,initial,created=native.create('owned-base-metadata',r['baseImage'],r['actorArgv'][0],r['actorArgv'][1:],network='none',readonly=True,memory_mb=resource['memoryMb'],cpus=resource['cpu'])
 receipt=native.start(cid,attach=True,timeout=60);final=native.assert_actor(cid)
 assert final['State']['Status']=='exited' and final['State']['ExitCode']==0
 text=native.text(receipt);assert '---APT-SOURCES---' in text and '---KEYRING---' in text and '---APT-VERSION---' in text
 result={'complete':True,'neutralContentOnly':True,'modelCalls':0,'gradeCalls':0,'referenceCalls':0,'imageInspect':image,'initial':initial,'create':created,'metadataReceipt':receipt,'final':final,'metadataText':text}
finally:
 for actor,role,name in native.open_actors():native.remove(actor)
 native.close()
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
