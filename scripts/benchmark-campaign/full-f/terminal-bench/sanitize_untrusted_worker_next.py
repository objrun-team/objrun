"""Original GitPython query on passive repository data in an offline island."""
import json,time
from pathlib import Path
from artifacts import capture_tree
from streaming_hash_next import pin
def sanitize_worker(native,candidate,task,capsule,output,proof,deadline):
 assert native.assert_actor(candidate)['State']['Paused']
 assert task['taskId']=='sanitize-git-repo' and proof['complete']
 output=Path(output);output.mkdir()
 files,dirs=capture_tree(native,candidate,'/app/dclm',512*1024**2,output/'repository')
 assert dirs and dirs[0]['exists']
 for f in files:assert pin(f['stored'])['sha256']==f['sha256']
 cid,initial,create=native.create('sanitize-untrusted-git-query',proof['imageId'],'/bin/sh',['-c','sleep 1200'],network='none',memory_mb=2048,cpus=1,storage_mb=10240)
 try:
  native.start(cid)
  absence=native.execute(cid,['/bin/sh','-c','test ! -e /tests && test ! -e /solution && test ! -e /opt/tb12/checker && rm -rf /app/dclm && mkdir -p /app'])
  native.upload(output/'repository/app/dclm',cid,'/app/dclm')
  metadata=output/'repository-modes.json';metadata.write_text(json.dumps([dict(path=f['path'],mode=f['originalMode']) for f in files]))
  native.upload(metadata,cid,'/tmp/repository-modes.json')
  script=output/'native-query.py';script.write_text("import git,json,os\nfrom pathlib import Path\nfor m in json.load(open('/tmp/repository-modes.json')):\n p=Path(m['path']);assert p.is_relative_to('/app/dclm') and not p.is_symlink();os.chmod(p,m['mode'])\nr=git.Repo('/app/dclm')\nprint(json.dumps([d.b_path for d in r.commit('d6987af002b122fef54bc0be402062c76488a4d9').diff(None)]))\n")
  native.upload(script,cid,'/tmp/native-query.py')
  remaining=deadline-time.monotonic();assert remaining>0
  query=native.command(['exec',cid,'/opt/checker/bin/python','-I','-B','/tmp/native-query.py'],timeout=remaining,stdout_limit=2*1024**2)
  assert query['exitCode']==0
  paths=json.loads(Path(query['stdout']['path']).read_bytes())
  assert isinstance(paths,list) and len(paths)<=10000
  return dict(protocol='sanitize-original-git-diff-v1',paths=paths,privateCandidateCodeExecution=False),dict(initial=initial,create=create,privateSourceAbsent=absence,nativeQuery=query,querySourcePin=pin(script),passiveRepositoryFiles=files)
 finally:native.remove(cid)
