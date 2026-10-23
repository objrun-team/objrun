"""Public official APT HTTP-to-HTTPS transport, no keys or model endpoints.

Passed only as Docker's temporary predefined http_proxy build argument; not
an image ENV or Docker setting. APT still verifies original signed metadata.
"""
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from prepare import HOME,public,save,utc

HOSTS={'deb.debian.org','security.debian.org','archive.ubuntu.com','security.ubuntu.com'}

def official_https(raw):
    value=urllib.parse.urlsplit(raw)
    if value.scheme!='http' or value.hostname not in HOSTS or value.username or value.password or value.port not in (None,80) or value.query or value.fragment:
        raise ValueError('official_apt_http_url_required')
    if not value.path.startswith(('/debian/','/debian-security/','/ubuntu/')):raise ValueError('official_apt_repository_path_required')
    if '..' in urllib.parse.unquote(value.path).split('/') or '\\' in value.path:raise ValueError('official_apt_path_traversal')
    return urllib.parse.urlunsplit(('https',value.hostname,value.path,'',''))

def main():
    home=HOME/'apt-transport-service'/uuid.uuid4().hex;home.mkdir(parents=True)
    source=public.pin(Path(__file__))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_CONNECT(self):self.send_error(403,'Official APT GET only')
        def do_POST(self):self.send_error(405)
        def do_GET(self):
            began=utc();row={'beganAtUtc':began,'modelCalls':0};response=None;digest=hashlib.sha256();count=0
            try:
                url=official_https(self.path);row['officialHttpsUrl']=url
                cache_pointer=HOME/'official-apt-cache/latest.json'
                if url.endswith('.deb') and cache_pointer.exists():
                    cache_pin=json.loads(cache_pointer.read_bytes())['resultPin'];assert public.pin(Path(cache_pin['path']))==cache_pin
                    cache=json.loads(Path(cache_pin['path']).read_bytes())
                    matches=[r for r in cache['rows'] if r['url']==url and r['verified']]
                    if matches:
                        item=matches[0];package=item['packagePin'];path=Path(package['path']).resolve()
                        assert path.parent==(HOME/'official-apt-cache').resolve() and public.pin(path)==package
                        assert package['sha256']==item['sha256'] and package['bytes']==item['bytes']
                        self.send_response(200);self.send_header('Connection','close');self.send_header('Content-Length',str(package['bytes']));self.send_header('Content-Type','application/vnd.debian.binary-package');self.end_headers();self.close_connection=True
                        with path.open('rb') as stream:
                            while True:
                                chunk=stream.read(65536)
                                if not chunk:break
                                self.wfile.write(chunk);count+=len(chunk);digest.update(chunk)
                        assert count==package['bytes'] and digest.hexdigest()==package['sha256']
                        row.update(httpStatus=200,complete=True,bytes=count,sha256=digest.hexdigest(),cacheResultPin=cache_pin,packagePin=package,servedOriginalVerifiedPackage=True);return
                for attempt in range(3):
                    try:response=urllib.request.urlopen(url,timeout=20);break
                    except urllib.error.HTTPError as error:
                        if error.code not in (502,503,504) or attempt==2:raise
                        time.sleep(.2*(attempt+1))
                assert urllib.parse.urlsplit(response.url).hostname in HOSTS
                length=response.headers.get('Content-Length')
                if length is not None:assert int(length)<=10*1024**3
                self.send_response(response.status);self.send_header('Connection','close')
                if length is not None:self.send_header('Content-Length',length)
                if response.headers.get('Content-Type'):self.send_header('Content-Type',response.headers['Content-Type'])
                self.end_headers();self.close_connection=True
                while True:
                    chunk=response.read(65536)
                    if not chunk:break
                    count+=len(chunk)
                    if count>10*1024**3:raise ValueError('original_maximum_storage_request_limit')
                    self.wfile.write(chunk);digest.update(chunk)
                row.update(httpStatus=response.status,complete=True,bytes=count,sha256=digest.hexdigest())
            except urllib.error.HTTPError as error:
                row.update(httpStatus=error.code,complete=False,errorType=type(error).__name__)
                try:self.send_error(error.code)
                except OSError:pass
            except Exception as error:
                row.update(complete=False,bytes=count,errorType=type(error).__name__)
                try:self.send_error(502 if response else 403)
                except OSError:pass
            finally:
                if response:response.close()
                row['endedAtUtc']=utc();save(home/('request-'+uuid.uuid4().hex+'.json'),row,True)
    server=ThreadingHTTPServer(('0.0.0.0',0),Handler);server.daemon_threads=True
    pin=save(home/'service.json',{'protocol':'skillsbench-official-apt-transport-v1','pid':os.getpid(),'port':server.server_port,'createdAtUtc':utc(),'sourcePin':source,'allowedHosts':sorted(HOSTS),'modelCalls':0,'storesPackageBytes':True,'cacheRequiresOriginalCompleteReceiptSha256':True},True)
    save(HOME/'apt-transport-service/latest.json',{'servicePin':pin});print(json.dumps({'pid':os.getpid(),'port':server.server_port,'servicePin':pin}),flush=True)
    server.serve_forever()

if __name__=='__main__':main()
