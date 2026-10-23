"""Business-specific actual v50 guard; read-only mode never borrows/acquires resources."""
import argparse,json,os,shutil
from bootstrap import install,ROOT
install()
from activation_guard import require_activation,load_control,require_lease,before_forward_guard
assert shutil.disk_usage(ROOT).free>=5*1024**3,'original_F_free_5GiB_floor_required'
p=argparse.ArgumentParser();p.add_argument('--forward',action='store_true');p.add_argument('--read-only',action='store_true');a=p.parse_args();assert a.forward != a.read_only,'explicit_owner_preflight_mode_required'
if a.forward:
 assert os.environ['NOVAEVE_RESOURCE_MEMORY_MB']=='24576' and os.environ['NOVAEVE_RESOURCE_GROWTH_BYTES']=='32212254720' and os.environ['NOVAEVE_RESOURCE_BENCH']=='terminal-bench','pipeline_original_forward_environment_required'
 lease=require_lease(24576,32212254720,'terminal-bench',1)
else:
 activation=require_activation();control=load_control(activation);assert control['broker']['pid']==activation['adoption']['liveExecutorPid']
observed=before_forward_guard()
print(json.dumps({'protocol':'pipeline-wx-v50-owner-preflight','passed':True,'mode':'forward' if a.forward else 'read-only','actualBrokerPid':observed['brokerPid'],'actualSourcePinnedCommonGuard':True,'actualLeaseVerified':a.forward,'hostCapacity':observed['hostCapacity'],'providerTransportInvoked':False,'nativeActors':0,'resourceAcquisitions':0,'modelCalls':0,'newPaidRequests':0}))
