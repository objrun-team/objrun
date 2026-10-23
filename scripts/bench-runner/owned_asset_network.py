"""Pinned public build proxy on the existing network; no host networking/mounts."""
import json,time
from native_process import pin
import _bench_original_owned_guard as guard

def build_network_arguments(request):
 assert request['operation']=='build' and request['network'] in ('none','default')
 if request['network']=='none':
  assert not request.get('proxyPolicyPin'),'offline_asset_cannot_gain_network_proxy'
  return ['--network','none']
 policy_pin=request['proxyPolicyPin'];assert pin(policy_pin['path'])==policy_pin,'exact_public_build_network_policy_pin'
 policy=json.loads(open(policy_pin['path'],encoding='utf8').read())
 assert policy['protocol']=='bench-pinned-public-build-network-v1'
 assert policy['originalNetwork']=='default' and policy['proxyUrl']=='http://172.30.89.1:10809'
 assert policy['publicNetworkSemanticsPreserved'] is True and policy['hostNetworkAdded'] is False and policy['hostMountAdded'] is False and policy['credentialsAdded'] is False
 assert policy['absoluteBuildSeconds']==600 and 0<request['deadline']-time.time()<=600
 assert policy['trustedExistingProxyEvidencePins']
 for proof in policy['trustedExistingProxyEvidencePins']:assert pin(proof['path'])==proof
 r=request['resource'];guard.require_lease(r['memoryMb'],r['growthBytes'],r['bench'],1)
 args=['--network','default']
 for key in ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy']:
  args+=['--build-arg',key+'='+policy['proxyUrl']]
 for key in ['NO_PROXY','no_proxy']:
  args+=['--build-arg',key+'=localhost,127.0.0.1']
 return args
