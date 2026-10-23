"""Small public official package probes; prefix only, no model/provider calls."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import urllib.error
import urllib.request
import uuid
from prepare import HOME,public,save,utc

def main():
    paths=['deb.debian.org/debian/pool/main/n/npth/libnpth0t64_1.8-3_amd64.deb',
        'archive.ubuntu.com/ubuntu/pool/main/libf/libfile-fcntllock-perl/libfile-fcntllock-perl_0.22-4ubuntu5_amd64.deb']
    def probe(url):
        row={'url':url,'beganAtUtc':utc(),'modelCalls':0}
        try:
            with urllib.request.urlopen(url,timeout=15) as response:
                raw=response.read(512);row.update(httpStatus=response.status,prefixBytes=len(raw),prefixSha256=hashlib.sha256(raw).hexdigest(),isDebianArchivePrefix=raw.startswith(b'!<arch>\n'))
        except urllib.error.HTTPError as error:row.update(httpStatus=error.code,errorType=type(error).__name__)
        except Exception as error:row.update(errorType=type(error).__name__,detail=str(error))
        row['endedAtUtc']=utc();return row
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(probe,[scheme+'://'+path for path in paths for scheme in ('http','https')]))
    home=HOME/'apt-transport-probes'/uuid.uuid4().hex;home.mkdir(parents=True)
    pin=save(home/'result.json',{'protocol':'skillsbench-official-apt-prefix-probes-v1','probes':rows,'modelCalls':0,'fullPackageDownloaded':False,'sourcePin':public.pin(__import__('pathlib').Path(__file__))},True)
    save(HOME/'apt-transport-probes/latest.json',{'resultPin':pin});print(json.dumps({'resultPin':pin,'probes':rows}))

if __name__=='__main__':main()
