"""Manifest-bound Python import bridge; original files are never rewritten."""
import argparse,hashlib,importlib.abc,importlib.util,json,runpy,sys
from pathlib import Path
CONFIG=None

def verified(pin):
 p=Path(pin['path']);raw=p.read_bytes();assert len(raw)==pin['bytes'] and hashlib.sha256(raw).hexdigest()==pin['sha256'];return p

def stage_checked_source(native,pin):
 source=verified(pin);root=Path(native.directory).resolve();stage=root/'common-qualified-script-staging';stage.mkdir(exist_ok=True);target=stage/source.name;raw=source.read_bytes();assert not source.is_symlink()
 if target.exists():assert not target.is_symlink() and target.read_bytes()==raw
 else:
  with target.open('xb') as output:output.write(raw)
 assert target.resolve().is_relative_to(root) and target.read_bytes()==raw;return target

def prepare_checker_inputs(native,checker,configpath):
 c=json.loads(Path(configpath).read_bytes());validator=sys.modules['grade_contract'];assert validator._original is not None
 c.update({'originalTestPath':CONFIG['checker']['originalTestPath'],'pytestArgs':CONFIG['checker']['pytestArgs'],'expectedTestNames':sorted(validator._original.EXPECTED)})
 Path(configpath).write_text(json.dumps(c));native.upload(stage_checked_source(native,CONFIG['checker']['reporterPin']),checker,'/opt/pipeline-checker/nodeid_phase_reporter.py')

def transform_grade(source,binding):
 a="runner=Path(__file__).with_name('checker_runner.py');";b="native.upload(runner,checker,'/opt/pipeline-checker/checker_runner.py');";c="{'name':name,'missing':request is None,'receipt':capture_receipt}"
 final="assert receipt['closeObserved'] and not receipt.get('timedOut') and receipt['exitCode']==0;"
 assert source.count(a)==source.count(b)==source.count(c)==source.count(final)==1,'unique reviewed checker bridge anchors required'
 verified(CONFIG['checker']['runnerPin']);source=source.replace(a,"runner=stage_checked_source(native,CONFIG['checker']['runnerPin']);")
 source=source.replace(b,"prepare_checker_inputs(native,checker,configpath);"+b)
 source=source.replace(c,"{'name':name,'missing':request is None and capture_receipt.get('classification')!='checker-completed','checkerCompleted':capture_receipt.get('classification')=='checker-completed','receipt':capture_receipt}")
 source=source.replace(final,"assert receipt['closeObserved'] and not receipt.get('timedOut') and not receipt.get('overflow') and not receipt.get('captureFaults') and not receipt.get('signal') and receipt['exitCode']==0;")
 return 'from bench_python_bindings import prepare_checker_inputs,stage_checked_source,CONFIG\n'+source

class GradeLoader(importlib.abc.Loader):
 def __init__(self,binding):self.binding=binding
 def create_module(self,spec):return None
 def exec_module(self,module):
  p=verified(self.binding['originalPin']);module.__file__=str(p);exec(compile(transform_grade(p.read_text(),self.binding),str(p),'exec'),module.__dict__)

def install(config):
 global CONFIG
 assert config['protocol']=='bench-qualified-python-module-bindings-v1';CONFIG=config
 assert len({x['name'] for x in config['modules']})==len(config['modules'])
 for p in [config['checker']['runnerPin'],config['checker']['reporterPin']]:verified(p)
 sys.modules['bench_python_bindings']=sys.modules[__name__]
 for binding in config['modules']:
  if binding['kind']=='checker-phase-source-bridge':continue
  assert binding['kind'] in ['configured-module','plain-module'];p=verified(binding['sourcePin']);spec=importlib.util.spec_from_file_location(binding['name'],p);module=importlib.util.module_from_spec(spec);sys.modules[binding['name']]=module;spec.loader.exec_module(module)
  if binding['kind']=='configured-module':verified(binding['originalPin']);module.configure(binding['originalPin'])
 original_spec=importlib.util.spec_from_file_location
 def bound_spec(name,location,*args,**kwargs):
  matches=[b for b in config['modules'] if b['kind']=='checker-phase-source-bridge' and b['name']==name and Path(location).resolve()==verified(b['originalPin']).resolve()]
  if matches:return importlib.util.spec_from_loader(name,GradeLoader(matches[0]),origin=str(location))
  return original_spec(name,location,*args,**kwargs)
 importlib.util.spec_from_file_location=bound_spec
 return original_spec

def main():
 p=argparse.ArgumentParser();p.add_argument('--bindings',required=True);p.add_argument('--original-script',required=True);p.add_argument('rest',nargs=argparse.REMAINDER);a=p.parse_args();config=json.loads(Path(a.bindings).read_bytes());assert Path(a.original_script).resolve()==verified(config['originalStandEntryPin']).resolve();install(config);sys.argv=[a.original_script]+(a.rest[1:] if a.rest[:1]==['--'] else a.rest);runpy.run_path(a.original_script,run_name='__main__')
if __name__=='__main__':main()
