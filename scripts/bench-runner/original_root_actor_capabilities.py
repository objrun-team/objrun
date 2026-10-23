"""Explicit root actor capabilities, bound to immutable original USER root source.

No host privileges are added. The private verifier receives no capabilities.
"""
import pathlib,re
from native_process import pin
CAPABILITIES=('CHOWN','DAC_OVERRIDE','FOWNER')

def original_root_capability_arguments(policy,task_id,private=False):
    assert policy['protocol']=='bench-original-root-actor-capabilities-v1'
    assert policy['taskId']==task_id,'exact_original_root_actor_task_scope'
    assert policy['privateActorCapabilitiesUnchanged'] is True
    assert policy['hostNetworkAdded'] is False and policy['hostMountAdded'] is False
    assert policy['privilegedAdded'] is False and policy['securityOptNoNewPrivilegesPreserved'] is True
    assert policy['capabilities']==list(CAPABILITIES)
    source=policy['originalDockerfilePin'];assert pin(source['path'])==source
    users=re.findall(r'(?im)^\s*USER\s+([^#\r\n]+)',pathlib.Path(source['path']).read_text())
    assert users and users[-1].strip() in ('root','0','0:0','root:root'),'explicit_original_root_user_required'
    assert policy['actualImageConfigUser'] in ('root','0','0:0','root:root')
    if private:return []
    return [item for cap in CAPABILITIES for item in ('--cap-add',cap)]
