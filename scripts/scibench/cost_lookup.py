"""Read-only provider billing reconciliation; raw receipts remain immutable."""
from pathlib import Path
import datetime
import json
import sys
import urllib.request
import urllib.error

payload=json.load(sys.stdin);key=payload.pop('key')
root=Path(__file__).resolve().parents[1];out=root/'outputs/canonical'
roots=[root]
for name in payload.get('additionalRuns',[]):
 if name not in {'scibench-recovery-20261016-v1','scibench-recovery-20261016-v2'}:raise RuntimeError('UnknownAccountingScope')
 roots.append(root.parent/name)
results=[]
for home in roots:
 for rp in sorted((home/'outputs/canonical/calls').rglob('receipt.json')):
  receipt=json.loads(rp.read_text())
  if not receipt['unknownCost']:continue
  hp=rp.with_name('response-headers.json')
  generation=receipt.get('generationId') or (json.loads(hp.read_text()).get('generationId') if hp.exists() else None)
  record={'originalReceiptPath':str(rp),'generationId':generation,'atUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'actualCostUsd':None}
  if not generation:record['outcome']='no_generation_id_unknown_preserved'
  else:
   try:
    request=urllib.request.Request('https://openrouter.ai/api/v1/generation?id='+generation,headers={'Authorization':'Bearer '+key})
    with urllib.request.urlopen(request,timeout=25) as response:data=json.load(response).get('data',{})
    keep={k:data.get(k) for k in ['id','model','provider_name','total_cost','generation_time','tokens_prompt','tokens_completion','finish_reason','native_finish_reason']}
    record['providerRecord']=keep
    cost=keep['total_cost']
    if keep['id']==generation and isinstance(cost,(int,float)) and cost>=0 and keep['model'] in {'deepseek/deepseek-v4.1-flash','deepseek/deepseek-v4.1-flash-20260910'}:
     record.update(outcome='provider_billing_lookup',actualCostUsd=cost)
    else:record['outcome']='unsettled_or_identity_mismatch'
   except Exception as e:record.update(outcome='lookup_unavailable_unknown_preserved',errorType=type(e).__name__)
  results.append(record)
path=out/'billing-reconciliation.json';temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps({'records':results,'rawReceiptsModified':False},indent=2)+'\n');temporary.replace(path)
print(json.dumps({'unknownReceiptsChecked':len(results),'settled':sum(r['actualCostUsd'] is not None for r in results),'newlyIdentifiedCostUsd':sum(r['actualCostUsd'] or 0 for r in results)}))
