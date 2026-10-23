import os,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'runtime_cache'))
from cache_client_v4 import copy_runtime_asset
from runtime_transport_circuit_drained_20261013_next import stage_runtime,call_tool,ship_runtime as original_ship_runtime
def ship_runtime(native,cid,staged):
 class Cached:
  def __getattr__(self,name):return getattr(native,name)
  def upload(self,source,candidate,destination):
   native.guard();assert candidate==cid;actor=native.assert_actor(cid);labels={k:actor['Labels'][k] for k in ('objrun.tb12.owner','objrun.tb12.role','objrun.tb12.native-source')};return copy_runtime_asset(source,cid,destination,labels,native.directory/'runtime-cache-receipts',lease_pid=int(os.environ['NOVAEVE_RESOURCE_PARENT_PID']))
 return original_ship_runtime(Cached(),cid,staged)
