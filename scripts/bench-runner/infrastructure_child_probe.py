"""Exercise actual nested interpreters and explicit-file loads without Bench content."""
import importlib.util,json,os,pathlib,sys,time
from bound_child_entry import checked_config,child_argv
from native_process import capture

path,c=checked_config();assert _bench_authorized_history('count-dataset-tokens')
spec=importlib.util.spec_from_file_location('_infra_explicit_probe',pathlib.Path(__file__).with_name('infrastructure_probe_module.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
observed=module.observed();assert pathlib.Path(observed['guardPath']).resolve()==pathlib.Path(c['guardPin']['path']).resolve() and observed['resourceMemoryMb']==2048
if '--leaf' not in sys.argv:
 row=capture(child_argv(sys.executable,['-B',__file__,'--leaf']),pathlib.Path(c['childEvidenceRoot'])/('nested-'+str(os.getpid())+'-'+str(time.time_ns())),120,env=dict(os.environ))
 assert row['pid'] and row['incarnation'] and row['closeObserved'] and row['exitCode']==0 and not row['error'] and not row['timedOut'],row
 leaf=json.loads(pathlib.Path(row['stdoutPin']['path']).read_bytes());assert leaf['leaf'] is True and leaf['observed']==observed
print(json.dumps({'protocol':'bench-actual-child-boundary-probe-v1','leaf':'--leaf' in sys.argv,'pid':os.getpid(),'observed':observed,'historyUnknownPreserved':True,'modelCalls':0}))
