"""One explicit entry for Python children, including explicit file module loads."""
import argparse,hashlib,importlib.abc,importlib.util,json,os,pathlib,sys,time
from native_process import capture,pin

def check(p):
 actual=pin(p['path']);assert (actual['bytes'],actual['sha256'])==(p['bytes'],p['sha256']),'child_source_pin_changed'
 return pathlib.Path(p['path'])

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--original-script',required=True);a,rest=parser.parse_known_args();rest=rest[1:] if rest[:1]==['--'] else rest
 path=pathlib.Path(a.config).resolve();raw=path.read_bytes();c=json.loads(raw);digest=hashlib.sha256(raw).hexdigest()
 assert c['protocol']=='bench-qualified-python-source-mapping-v1'
 if 'NOVAEVE_PYTHON_MAPPING_CONFIG' in os.environ:
  assert path==pathlib.Path(os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']).resolve() and digest==os.environ['NOVAEVE_PYTHON_MAPPING_SHA256'],'explicit_child_configuration_changed'
 os.environ.update(NOVAEVE_PYTHON_MAPPING_CONFIG=str(path),NOVAEVE_PYTHON_MAPPING_SHA256=digest)
 approved=[c['originalStandPin'],*c.get('allowedEntryPins',[])];selected=[p for p in approved if check(p).resolve()==pathlib.Path(a.original_script).resolve()];assert len(selected)==1,'child_entry_not_approved'
 gp=check(c['guardPin']);spec=importlib.util.spec_from_file_location('_bench_original_owned_guard',gp);guard=importlib.util.module_from_spec(spec);sys.modules[spec.name]=guard;spec.loader.exec_module(guard)
 activation=guard.require_activation();assert os.environ['DOCKER_HOST']==activation['dockerHost'];guard.require_lease(c['resource']['memoryMb'],c['resource']['growthBytes'],c['resource']['bench'],1)
 policy=None
 if c.get('requireHistoryPolicy'):
  h=c['historyPolicy'];manifest=check(h['manifestPin']);helper=check(h['verifierPin']);bun=check(h['bunPin']);directory=pathlib.Path(c['childEvidenceRoot']);directory.mkdir(parents=True,exist_ok=True)
  row=capture([str(bun),str(helper),str(manifest),h['manifestPin']['sha256'],h['taskKey']],directory/('history-'+str(os.getpid())+'-'+str(time.time_ns())),30)
  assert row['closeObserved'] and row['exitCode']==0 and not row['timedOut'] and not row['error'],'child_root_policy_rejected'
  policy=json.loads(pathlib.Path(row['stdoutPin']['path']).read_bytes());assert policy['protocol']=='bench-verified-child-history-policy-v1' and policy['taskKey']==h['taskKey'] and policy['authorized'] is True
 def authorized_history(task):
  assert policy is not None and policy['taskKey'].split(':',1)[1]==task,'task_scoped_child_history_policy_required'
  return True
 modules={m['name']:m for m in c['modules']};original_spec=importlib.util.spec_from_file_location
 def transformed(m):
  code=check(m['pin']).read_bytes().decode('utf8')
  for change in m.get('exactReplacements',[]):
   assert len(change['from'])>=9 and code.count(change['from'])==1,'child_mapping_anchor_not_unique'
   code=code.replace(change['from'],change['to'])
  if c.get('requireHistoryPolicy'):assert 'paid_preserve_no_retry' not in code,'obsolete_unpaid_predicate_forbidden'
  return code
 class Loader(importlib.abc.Loader):
  def __init__(self,m):self.m=m
  def create_module(self,spec):return None
  def exec_module(self,module):
   module.__file__=str(check(self.m['pin']));module.__dict__['_bench_authorized_history']=authorized_history
   exec(compile(transformed(self.m),module.__file__,'exec'),module.__dict__)
   for name,kind in self.m.get('guardAliases',{}).items():
    assert callable(module.__dict__[name])
    assert kind in ('actual-adopted-control','actual-owned-lease')
    module.__dict__[name]=(lambda *args,**kwargs:guard.load_control()) if kind=='actual-adopted-control' else (lambda *args,**kwargs:guard.guard())
   if self.m.get('guardOwnedCommand'):
    original=module.OwnedDocker.command
    def command(owner,*args,**kwargs):guard.before_forward_guard();return original(owner,*args,**kwargs)
    module.OwnedDocker.command=command
 class Finder(importlib.abc.MetaPathFinder):
  def find_spec(self,name,path=None,target=None):return importlib.util.spec_from_loader(name,Loader(modules[name]),origin=modules[name]['pin']['path']) if name in modules else None
 def explicit(name,location,*args,**kwargs):
  m=modules.get(name)
  if m and pathlib.Path(location).resolve()==check(m['pin']).resolve():return importlib.util.spec_from_loader(name,Loader(m),origin=str(location))
  return original_spec(name,location,*args,**kwargs)
 for m in modules.values():check(m['pin'])
 sys.meta_path.insert(0,Finder());importlib.util.spec_from_file_location=explicit
 entry=pathlib.Path(a.original_script).resolve();sys.path.insert(0,str(entry.parent));sys.argv=[str(entry),*rest]
 mappings=[m for m in c.get('entryMappings',[]) if check(m['pin']).resolve()==entry];assert len(mappings)<=1
 module=type(sys)('__main__');sys.modules['__main__']=module;module.__file__=str(entry);module.__dict__['_bench_authorized_history']=authorized_history
 code=transformed(mappings[0]) if mappings else entry.read_text(encoding='utf8');exec(compile(code,str(entry),'exec'),module.__dict__)

if __name__=='__main__':main()
