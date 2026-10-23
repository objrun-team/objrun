"""Explicit child argv. Every Python interpreter validates its own configured boundary."""
import hashlib,json,os,pathlib,sys

def checked_config():
 path=pathlib.Path(os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']);raw=path.read_bytes()
 assert hashlib.sha256(raw).hexdigest()==os.environ['NOVAEVE_PYTHON_MAPPING_SHA256'],'child_mapping_changed'
 return path,json.loads(raw)

def child_argv(executable,args):
 path,config=checked_config();args=list(map(str,args));flags=[]
 while args and args[0] in ('-B','-u'):flags.append(args.pop(0))
 assert args and pathlib.Path(executable).resolve()==pathlib.Path(sys.executable).resolve(),'explicit_python_child_required'
 entry=pathlib.Path(args.pop(0)).resolve();approved=[config['originalStandPin'],*config.get('allowedEntryPins',[])]
 matches=[p for p in approved if pathlib.Path(p['path']).resolve()==entry];assert len(matches)==1,'child_entry_not_approved'
 raw=entry.read_bytes();assert len(raw)==matches[0]['bytes'] and hashlib.sha256(raw).hexdigest()==matches[0]['sha256'],'child_entry_changed'
 bootstrap=pathlib.Path(__file__).with_name('python_child_entry.py')
 return [str(executable),*flags,str(bootstrap),'--config',str(path),'--original-script',str(entry),'--',*args]
