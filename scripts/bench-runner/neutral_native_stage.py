"""No Bench content: the same original owned Docker stage and explicit child."""
import argparse,json,pathlib,hashlib
from docker_owned import OwnedDocker
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--base-image',required=True);p.add_argument('--input',required=True);a=p.parse_args()
out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=False);native=OwnedDocker(out/'native');cid=None
try:
 cid,initial,created=native.create('neutral-native-stage',a.base_image,'/bin/sh',['-c','exec sleep 180'],network='none',memory_mb=2048,cpus=1)
 native.start(cid);native.execute(cid,['/bin/mkdir','-p','/neutral'])
 fixture=pathlib.Path(a.input);assert fixture.read_bytes()==b'owned-native-stage-no-bench\n';native.upload(fixture,cid,'/neutral/value.txt')
 receipt=native.execute(cid,['/usr/bin/sha256sum','/neutral/value.txt']);assert native.text(receipt).split()[0]==hashlib.sha256(fixture.read_bytes()).hexdigest()
 execution=native.execute(cid,['/bin/sh','-c','test "$(cat /neutral/value.txt)" = owned-native-stage-no-bench && printf neutral-stage-ok']);assert native.text(execution)=='neutral-stage-ok'
finally:
 for actor,role,name in native.open_actors():native.remove(actor)
 native.close()
(out/'result.json').write_text(json.dumps({'complete':True,'modelCalls':0,'gradeCalls':0,'referenceCalls':0,'neutralContentOnly':True})+'\n')
