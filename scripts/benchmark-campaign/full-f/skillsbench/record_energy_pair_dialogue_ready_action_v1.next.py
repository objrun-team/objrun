"""Persist fresh formal evidence and the qualified, zero-model disk queue."""
import json,uuid,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare import HOME,public,save,utc
run=HOME/'runs/repair-2026-10-11T11-50-05-363Z-13-2026-10-11T17-09-56-567Z'
cash=json.loads((run/'cash/cash-close.json').read_bytes());assert cash['snapshot']['pendingCount']==0 and cash['snapshot']['billedUsd']==0
assert (run/'journal/api-events.jsonl').stat().st_size==0
pending=json.loads((run/'physical-disk-pending-12.json').read_bytes());assert pending['taskId']=='dialogue-parser' and pending['originalBudgetRetained']
prep_pointer=json.loads((HOME/'generic-ordinary-preparation-controls/dialogue-parser/latest.json').read_bytes())['resultPin'];assert public.pin(Path(prep_pointer['path']))==prep_pointer
prep=json.loads(Path(prep_pointer['path']).read_bytes());cold=json.loads(Path(prep['controlPin']['path']).read_bytes());assert cold['controlsPassed'] and cold['decisions']==[0,1,0] and cold['ownedContainersRemaining']==0
oracle=json.loads(Path(cold['oraclePin']['path']).read_bytes());assert oracle['complete'] and oracle['passedTests']==len(oracle['nodeIds'])==35
q=json.loads((HOME/'task-queue-v2.json').read_bytes())
assert 'dialogue-parser' not in q['completed'] and 'dialogue-parser' not in q['running']
for k in ['preparing','repair']:q[k]=[t for t in q[k] if t!='dialogue-parser']
q['ready']=sorted(set(q.get('ready',[])+['dialogue-parser']));q['updatedAtUtc']=utc();save(HOME/'task-queue-v2.json',q)
latest=json.loads((HOME/'heartbeat-actions/latest.json').read_bytes())['resultPin']
proof={'atUtc':utc(),'denominator':87,'originalManifestPin':public.pin(HOME/'manifest.json'),'latestActualFormalEvidencePin':latest,'energyPairRealLaunchPin':public.pin(HOME/'energy-pair-qualified-formal-resume/c0253478be464dc5b070410dd5361938/launch.json'),'schedulerQueueGuardControlPin':public.pin(HOME/'scheduler-v6-queue-build-check/actual-native-status-controls.json'),'dialogueOriginalColdPin':prep['controlPin'],'dialogueOriginalFullOracleTests':35,'dialogueControls':[0,1,0],'dialogueCachedImagesRebuilt':False,'dialogueQualifiedReadyDiskQueue':True,'dialogueZeroModelAdmittedRunAccountingPin':public.pin(run/'accounting-close.json'),'dialogueZeroModelJournalPin':public.pin(run/'journal/api-events.jsonl'),'dialoguePhysicalQueuePin':public.pin(run/'physical-disk-pending-12.json'),'auditPin':public.pin(HOME.parent/'audit-2026-10-11T17-04-48-466Z.json'),'scoresAddedByThisRecorder':0,'modelCallsByThisRecorder':0,'originalCashOrReceiptsModified':False,'priorDedupAttemptFailedWithoutReceipt':'old prior dedup rejected already-shared inode; no unsafe replacement continued','salesOracleStillNotCertified':'original 26 collected:23 passed,3 intentional native skips; positive completeness retained, no repeat launched'}
pin=save(HOME/'heartbeat-actions'/uuid.uuid4().hex/'action.json',proof,True)
s=json.loads((HOME/'status.json').read_bytes());s.update(energyPairDialogueExecutionActionPin=pin,dialogueQualifiedReadyPendingActualDisk=True,updatedAtUtc=utc());save(HOME/'status.json',s)
print(json.dumps({'actionPin':pin,'dialogueReady':True,'scoresAdded':0}))
