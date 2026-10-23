"""Owner's original official completion ledger; root review stays separately visible."""
import json,sys,uuid
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare import HOME,public,save,utc
now=datetime.now(timezone.utc);events={}
for p in sorted((HOME/'private-native-closure-reviews').glob('*/result.json')):
 r=json.loads(p.read_bytes())
 if not r['officialValid']:continue
 pin=r['taskRecordPin'];assert public.pin(Path(pin['path']))==pin
 task=json.loads(Path(pin['path']).read_bytes());assert task['officialAcceptance']['valid'] and task['protocolValid']
 completion=datetime.fromtimestamp(Path(pin['path']).stat().st_mtime,timezone.utc)
 events[(r['taskId'],r['runId'])]={'taskId':r['taskId'],'runId':r['runId'],'completionAtUtc':completion.isoformat(),'completionSource':'unaltered original official native task receipt filesystem modification time','taskRecordPin':pin,'closureReviewPin':public.pin(p),'officialPassed':r['officialPassed'],'independentRootReviewPending':r.get('independentRootReviewPending',True)}
root=json.loads((HOME.parent/'official-valid-score-events-root.json').read_bytes())['events']
root_keys={(e.get('taskId'),e.get('runId')) for e in root if e['bench']=='skillsbench'}
for k,e in events.items():e['independentRootReviewPresent']=k in root_keys
recent=[e for e in events.values() if 0<=(now-datetime.fromisoformat(e['completionAtUtc'])).total_seconds()<=3600]
ledger={'atUtc':utc(),'events':list(events.values()),'rollingOneHourOwnerNativeOfficialValid':len(recent),'rollingEvents':recent,'modelCalls':0,'rootLedgerUnmodified':True,'originalReceiptsUnmodified':True}
pin=save(HOME/'owner-official-valid-events'/uuid.uuid4().hex/'result.json',ledger,True);save(HOME/'owner-official-valid-events/latest.json',{'resultPin':pin})
s=json.loads((HOME/'status.json').read_bytes());s.update(ownerOfficialValidEventsPin=pin,ownerRollingOneHourNativeOfficialValid=len(recent),updatedAtUtc=utc());save(HOME/'status.json',s)
print(json.dumps({'ledgerPin':pin,'rollingOwnerNativeOfficialValid':len(recent),'rootIndependentReviewStillSeparate':True}))
