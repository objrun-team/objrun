"""Pinned legacy Python graph; source files and task semantics remain immutable."""
import argparse,hashlib,importlib.abc,importlib.util,json,os,runpy,sys
from pathlib import Path

def check(p):
 data=Path(p['path']).read_bytes()
 if len(data)!=p['bytes'] or hashlib.sha256(data).hexdigest()!=p['sha256']:raise RuntimeError('python_mapping_pin_changed')
 return data

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--original-script',required=True);args,rest=parser.parse_known_args();rest=rest[1:] if rest[:1]==['--'] else rest
 config=json.loads(Path(args.config).read_bytes())
 if config['protocol']!='bench-qualified-python-source-mapping-v1':raise RuntimeError('python_mapping_protocol')
 if Path(args.original_script).resolve()!=Path(config['originalStandPin']['path']).resolve():raise RuntimeError('python_mapping_original_entry')
 check(config['originalStandPin']);check(config['guardPin'])
 spec=importlib.util.spec_from_file_location('_bench_original_owned_guard',config['guardPin']['path']);guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
 activation=guard.require_activation()
 if os.environ.get('DOCKER_HOST')!=activation['dockerHost']:raise RuntimeError('python_mapping_actual_private_docker_required')
 guard.require_lease(config['resource']['memoryMb'],config['resource']['growthBytes'],config['resource']['bench'],1)
 modules={m['name']:m for m in config['modules']}
 class Loader(importlib.abc.Loader):
  def __init__(self,m):self.mapping=m
  def create_module(self,spec):return None
  def exec_module(self,module):
   m=self.mapping;code=check(m['pin']).decode('utf8')
   for c in m.get('exactReplacements',[]):
    if len(c['from'])<9 or code.count(c['from'])!=1:raise RuntimeError('python_mapping_anchor_not_unique')
    code=code.replace(c['from'],c['to'])
   module.__file__=m['pin']['path'];exec(compile(code,module.__file__,'exec'),module.__dict__)
   if m.get('guardOwnedCommand'):
    original=module.OwnedDocker.command
    def owned_command(self,*args,**kwargs):
     guard.before_forward_guard();return original(self,*args,**kwargs)
    module.OwnedDocker.command=owned_command
 class Finder(importlib.abc.MetaPathFinder):
  def find_spec(self,fullname,path=None,target=None):
   return importlib.util.spec_from_loader(fullname,Loader(modules[fullname]),origin=modules[fullname]['pin']['path']) if fullname in modules else None
 for m in modules.values():check(m['pin'])
 sys.meta_path.insert(0,Finder());sys.path.insert(0,str(Path(args.original_script).parent));sys.argv=[args.original_script,*rest]
 runpy.run_path(args.original_script,run_name='__main__')
if __name__=='__main__':main()
