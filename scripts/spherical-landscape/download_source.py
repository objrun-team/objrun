"""Resumable source acquisition, bounded by the original experiment deadline."""
import json,sys,time,os,threading,hashlib
from pathlib import Path
import requests
run=Path(sys.argv[1]);end=json.loads((run/'deadline.json').read_text())['deadline_epoch'];dest=run/'sources/real_equal_norm.tar.gz'
meta=json.loads((run/'sources/zenodo-metadata.json').read_text());item=next(x for x in meta['files'] if x['key']=='real_equal_norm.tar.gz');url=item['links']['self'];size=item['size']
def hard_stop():time.sleep(max(0,end-time.time()));os._exit(124)
threading.Thread(target=hard_stop,daemon=True).start()
while time.time()<end and dest.stat().st_size<size:
    offset=dest.stat().st_size
    try:
        with requests.get(url,headers={'Range':f'bytes={offset}-'},stream=True,timeout=(20,30)) as response:
            assert response.status_code==206,f'HTTP {response.status_code}; refusing to append an unconfirmed range'
            assert response.headers.get('Content-Range','').startswith(f'bytes {offset}-'),'Unexpected range'
            with dest.open('ab') as out:
                for chunk in response.iter_content(65536):
                    if time.time()>=end:break
                    if chunk:out.write(chunk)
        print(json.dumps({'time':time.time(),'bytes':dest.stat().st_size,'event':'range_closed'}),flush=True)
    except Exception as exc:
        print(json.dumps({'time':time.time(),'offset':offset,'bytes':dest.stat().st_size,'event':'retry','error':str(exc)}),flush=True)
        time.sleep(min(5,max(0,end-time.time())))
if dest.stat().st_size==size:
    dig=hashlib.md5(dest.read_bytes()).hexdigest();result={'md5':dig,'expected_md5':item['checksum'].split(':')[1],'matches':dig==item['checksum'].split(':')[1],'size':size,'url':url,'finished_epoch':time.time()}
    (run/'sources/archive-integrity.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
