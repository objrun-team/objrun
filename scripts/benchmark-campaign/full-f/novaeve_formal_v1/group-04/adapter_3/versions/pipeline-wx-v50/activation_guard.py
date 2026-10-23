"""Pipeline-specific pinned v50 owner adapter; resource contract is explicit."""
import importlib.util,json,hashlib,os,time
from pathlib import Path
from bootstrap import ROOT
SHARED_PINS={'adopted_owner_guard_v50.py': {'path': 'F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\benchmark-campaign\\full-f\\novaeve_formal_v1\\broker\\adopted_owner_guard_v50.py', 'bytes': 6172, 'sha256': '8f3a35ef9e20074dcd3175fb6d30be7f48de383086a3c598b6208b82a05325b1'}, 'adopted-python-bridge-v50.ts': {'path': 'F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\benchmark-campaign\\full-f\\novaeve_formal_v1\\broker\\adopted-python-bridge-v50.ts', 'bytes': 1982, 'sha256': '2347c04ec226281afdf3d27c24bfcb778d12948686b7fb0a082c25cce43adbb5'}}
BASE=ROOT/'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013'
PATH=BASE/'activation-adopted-v48.json'
def _source_guard():
 for p in SHARED_PINS.values():
  b=Path(p['path']).read_bytes();assert len(b)==p['bytes'] and hashlib.sha256(b).hexdigest()==p['sha256'],'frozen_common_owner_source_changed'
_source_guard()
spec=importlib.util.spec_from_file_location('pipeline_pinned_shared_owner_v50',SHARED_PINS['adopted_owner_guard_v50.py']['path']);shared=importlib.util.module_from_spec(spec);spec.loader.exec_module(shared)
def _fresh_disk_wait(deadline):
 while True:
  d=json.loads((BASE/'broker/remote-disk.json').read_bytes());age=time.time()*1000-d['observedAtMs']
  if 0<=age<=10000 and d.get('probeExitCode')==0 and d.get('dataRoot')=='/data/wpx/tgengin/docker' and d.get('freeBytes',0)>=5*1024**3:return
  if time.monotonic()>=deadline:raise RuntimeError('actual_fresh_remote_disk_floor_required')
  time.sleep(.25)
def _actual(method,*args,**kwargs):
 _source_guard();deadline=time.monotonic()+25
 while True:
  _fresh_disk_wait(deadline)
  try:return method(*args,**kwargs)
  except RuntimeError as e:
   if str(e)!='actual_fresh_remote_disk_floor_required' or time.monotonic()>=deadline:raise
   time.sleep(.25)
def require_activation():return _actual(shared.require_activation)
def load_control(activation=None):return _actual(shared.load_control,activation)
def require_lease(memory_mb,growth_bytes,slug,slots):
 import psutil
 assert (memory_mb,growth_bytes,slug,slots)==(24576,32212254720,'terminal-bench',1),'original_pipeline_aggregate_resource_contract_required'
 parent=int(os.environ['NOVAEVE_RESOURCE_PARENT_PID']);assert parent==int(os.environ['NOVAEVE_RESOURCE_LEASE_PID']) and parent in [p.pid for p in psutil.Process().parents()],'actual_pipeline_resource_owner_ancestry_required'
 return _actual(shared.require_lease,memory_mb=memory_mb,growth_bytes=growth_bytes,slug=slug,slots=slots)
def before_forward_guard():return _actual(shared.before_forward_guard)
def bound_control(root):
 a=require_activation();return a,load_control(a)
