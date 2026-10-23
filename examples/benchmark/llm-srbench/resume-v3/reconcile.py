"""Read-only billing metadata; original receipts and all reserves remain unchanged."""
import urllib.request,urllib.parse
from shared import *

def reconcile():
    path=OUT/'reconciliation.json';old=load(path) if path.exists() else {'entries':[]};cached={e['requestDirectory']:e for e in old['entries']};entries=[]
    folders=[r/'outputs/tasks' for r in HISTORY]+[round_out(n)/'tasks' for n in ['main','repair']]
    for folder in folders:
        for u in ledger(folder)['unknownRequests']:
            d=pathlib.Path(u['path']);rp=d/'receipt.json';receipt=load(rp) if rp.exists() else {};stamp=sha(rp) if rp.exists() else None
            if str(d) in cached and cached[str(d)]['receiptSha256']==stamp:entries.append(cached[str(d)]);continue
            gen=receipt.get('generationId');entry={'requestDirectory':str(d),'receiptSha256':stamp,'generationId':gen,'reserveUsd':u['reserveUsd'],'allReserveRetained':True,'originalReceiptUnchanged':True}
            if not gen:entry['status']='no_generation_id; unresolved reserve retained'
            else:
                req=urllib.request.Request('https://openrouter.ai/api/v1/generation?'+urllib.parse.urlencode({'id':gen}),headers={'Authorization':'Bearer '+common.KEY})
                try:
                    with urllib.request.urlopen(req,timeout=30) as r:metadata=json.load(r)
                    cost=metadata.get('data',{}).get('total_cost');entry.update(status='metadata_observed_reserve_retained',metadata=metadata,reconciledCostUsd=cost)
                    if isinstance(cost,(int,float)) and cost>u['reserveUsd']+1e-7:raise RuntimeError('ReconciledCostExceededTrustedReservation')
                except RuntimeError:raise
                except Exception as e:entry.update(status='metadata_unavailable_reserve_retained',lookupError=type(e).__name__)
            entries.append(entry)
    value={'atUtc':utc(),'modelCalls':0,'allReservesRetained':True,'entries':entries};common.save(path,value);return value
