import sys,runpy,hashlib,importlib.util
from pathlib import Path
HERE=Path(__file__).resolve().parent
BASE=HERE.parents[3]
sys.path.insert(0,str(BASE/'coordinator/pipeline-owned-v83'))
from bootstrap import install
install()
from docker_owned import OwnedDocker
approved={Path(k).resolve():v for k,v in {'F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\repair-2026-10-10\\full-f\\novaeve_formal_v1\\group-04\\adapter_3\\versions\\pipeline-formal-successor-wx-v142\\tensor_protocol.py': {'path': 'F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\repair-2026-10-10\\full-f\\novaeve_formal_v1\\group-04\\adapter_3\\versions\\pipeline-formal-successor-wx-v142\\tensor_protocol.py', 'bytes': 1985, 'sha256': '02803869eb910936e69b40aad5460e1956cbe95388f176c482d32facb2f923fa'}, 'F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\repair-2026-10-10\\full-f\\novaeve_formal_v1\\group-04\\adapter_3\\versions\\pipeline-formal-successor-wx-v142\\pipeline_parallel.py': {'path': 'F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\repair-2026-10-10\\full-f\\novaeve_formal_v1\\group-04\\adapter_3\\versions\\pipeline-formal-successor-wx-v142\\pipeline_parallel.py', 'bytes': 1428, 'sha256': '0858bb04430f64e6d3b43cf06c1b66fe3a54363434f851b96e377e13099d51f1'}, 'F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\repair-2026-10-10\\full-f\\novaeve_formal_v1\\group-04\\adapter_3\\versions\\pipeline-formal-successor-wx-v142\\checker_runner.py': {'path': 'F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\repair-2026-10-10\\full-f\\novaeve_formal_v1\\group-04\\adapter_3\\versions\\pipeline-formal-successor-wx-v142\\checker_runner.py', 'bytes': 2225, 'sha256': '08ed930b397305d63f4eb4f81f13fc1ea8bdee98e2e6a0f39437df41bdbe379d'}}.items()}
old_upload=OwnedDocker.upload
def upload(self,source,cid,destination):
 source=Path(source).resolve()
 if source in approved:
  p=approved[source];data=source.read_bytes();assert not source.is_symlink() and len(data)==p['bytes'] and hashlib.sha256(data).hexdigest()==p['sha256']
  stage=self.directory/'root-approved-script-staging';stage.mkdir(parents=True,exist_ok=True);target=stage/source.name
  if target.exists():assert not target.is_symlink() and target.read_bytes()==data
  else:
   with target.open('xb') as f:f.write(data)
  assert target.resolve().is_relative_to(self.directory.resolve()) and target.read_bytes()==data
  source=target
 return old_upload(self,source,cid,destination)
OwnedDocker.upload=upload
sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location('pipeline_grade',HERE/'pipeline_grade.py');mod=importlib.util.module_from_spec(spec);sys.modules['pipeline_grade']=mod;spec.loader.exec_module(mod)
runpy.run_path(str(BASE/'group-04/adapter_3/versions/pipeline-wx-v50/stand_entry.py'),run_name='__main__' if __name__=='__main__' else 'pipeline_static_preflight')
