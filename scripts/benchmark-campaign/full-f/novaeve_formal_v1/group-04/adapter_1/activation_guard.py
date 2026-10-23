"""Require root activation, current broker, and public parent resource lease."""
import json,os
from pathlib import Path
from bootstrap import ROOT
BASE=ROOT/'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013'
PATH=Path(os.environ.get('NOVAEVE_ACTIVATION_PATH',str(BASE/'activation.json')))
def load_control(activation):
 path=Path(os.environ.get('NOVAEVE_BROKER_CONTROL_PATH') or activation.get('brokerControlPath') or activation.get('controlPath') or BASE/'broker/control.private.json').resolve()
 if not path.is_relative_to(BASE.resolve()):raise RuntimeError('novaeve_control_path_outside_new_campaign')
 control=json.loads(path.read_bytes());broker=control.get('broker',{})
 if control.get('paidReady') is not True or broker.get('endpoint')!='http://127.0.0.1:17889' or control.get('novaeve',{}).get('totalConcurrency')!=16 or broker.get('runId')!=activation.get('runId'):raise RuntimeError('novaeve_root_broker_activation_required')
 return control
def require_activation():
 if not PATH.is_file():raise RuntimeError('novaeve_activation_missing_local_checks_only')
 value=json.loads(PATH.read_text(encoding='utf-8-sig'))
 if value.get('activated') is not True or value.get('dockerHost')!='tcp://127.0.0.1:18750':raise RuntimeError('novaeve_activation_not_active_or_wrong_route')
 load_control(value)
 return value
def require_lease(memory_mb=4096,growth_bytes=32212254720):
 import os
 activation=require_activation();control=load_control(activation)
 health=json.loads(Path(control['broker']['healthPath']).read_bytes())
 if health.get('runId')!=activation['runId']:raise RuntimeError('novaeve_lease_wrong_broker_run')
 matches=[r for r in health['resourceSlots'] if r['pid']==os.getppid() and r['slug']=='terminal-bench' and r['kind']=='heavy-container']
 if len(matches)!=1 or matches[0]['memoryMb']<memory_mb or matches[0]['plannedGrowthBytes']<growth_bytes:raise RuntimeError('novaeve_public_parent_lease_missing_or_insufficient')
 return matches[0]
