"""Release this exact already-closed failed pilot lock; no score certificate."""
import json,subprocess,sys
from pathlib import Path
import skb_artifact_task_v2 as task
import skb_artifact_ram_executor_v2 as grader
r=json.loads(Path(sys.argv[1]).read_text());output=Path(r['output']);layout=task.read_json(r['storageDescriptorPin']);root=Path(layout['storePhysical']);lock=task.REPO/'.phase1-data/owned-paid-campaign.lock.json';owned=json.loads(lock.read_text());task.demand(owned['runId']==r['runId'],'release_owner','Exact failed own run required')
state=json.loads((Path(layout['directories']['journal'])/'api-state.json').read_text());task.demand(not state['pending'] and not state['active'],'release_pending','Provider still active')
pids=[owned['pid'],*[json.loads(p.read_text())['pid'] for p in output.glob('process-*.json')]]
q=subprocess.run(['powershell.exe','-NoProfile','-Command',f"$p=@({','.join(map(str,pids))}); @(Get-CimInstance Win32_Process | Where-Object {{$_.ProcessId -in $p}} | Select-Object ProcessId) | ConvertTo-Json -Compress"],capture_output=True,timeout=30)
task.demand(q.returncode==0 and not q.stdout.strip(),'release_actor','Own actor remains')
closures=[]
for lp in r['slotStorageDescriptorPins']:
 s=task.read_json(lp);p=Path(s['directories']['stand'])/'bridge-owned-close.json';c=json.loads(p.read_text());task.demand(c['ownedSolversClosed'],'release_solver','Own solver remains');closures.append(task.pin(p))
proof=grader.fresh(output/'failed-closed-release-v6.json',task.canonical({'owned':owned,'actorPids':pids,'actorAbsenceNativeObserved':True,'bridgeClosurePins':closures,'providerPending':0,'journalPrefix':state['durablePrefix'],'priorFailureRetained':True,'secretAuditNotCompleted':True,'financialCertificate':False,'scoreCertificate':False,'modelCalls':0}),root)
task.demand(json.loads(lock.read_text())==owned,'release_changed','Owner changed');lock.unlink();print(json.dumps({'releasePin':proof,'modelCalls':0}),flush=True)
