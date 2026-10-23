"""Read-only generation metadata reconciliation. Original receipts and reserves never change."""
import urllib.request,urllib.parse
from shared import *
def main():
    if (CONTROL/'reconciliation.json').exists():return load(CONTROL/'reconciliation.json')
    entries=[]
    for root in [V1,MAIN]:
        for u in ledger(root/'outputs/tasks')['unknownRequests']:
            d=pathlib.Path(u['path']);raw=d/'response.raw.txt';value={}
            try:value=json.loads(raw.read_text()) if raw.exists() else {}
            except ValueError:pass
            gen=u.get('generationId') or value.get('id');e={**u,'originalReservePreserved':True,'generationId':gen,'localResponseCost':value.get('usage',{}).get('cost')}
            if not gen:e['status']='unreconciled_no_generation_id; original reserve retained'
            elif common.KEY:
                request=urllib.request.Request('https://openrouter.ai/api/v1/generation?'+urllib.parse.urlencode({'id':gen}),headers={'Authorization':'Bearer '+common.KEY})
                try:
                    with urllib.request.urlopen(request,timeout=30) as response:metadata=json.load(response)
                    e.update(status='metadata_read; reserve conservatively retained',metadata=metadata,reconciledCostUsd=metadata.get('data',{}).get('total_cost'))
                except Exception as exc:e.update(status='metadata_unavailable; reserve retained',lookupError=type(exc).__name__)
            else:e['status']='lookup_deferred_until_authorized_key_transport; reserve retained'
            entries.append(e)
    result={'atUtc':utc(),'entries':entries,'modelCalls':0,'originalReceiptsChanged':False,'allReservesRetained':True,'metadataEndpointDocumentation':'https://openrouter.ai/docs/api/api-reference/generations/get-generation'};common.save(CONTROL/'reconciliation.json',result);return result
if __name__=='__main__':print(json.dumps(main()))
