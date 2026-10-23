from pathlib import Path
import sys,ast,uuid,json
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare import HOME,public,save,utc
p=Path(__file__).parent;old=p/'apt_transport_proxy10809.next.py';s=old.read_text(encoding='utf-8')
helper='''
import subprocess,email.parser
class CurlResponse:
    def __init__(self,url):
        self.url=url
        self.proc=subprocess.Popen(['C:/Windows/System32/curl.exe','--proxy','http://127.0.0.1:10809','--connect-timeout','10','--max-time','45','--http1.1','--include','--suppress-connect-headers','--silent','--show-error','--url',url],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            line=self.proc.stdout.readline(8192);assert line.startswith(b'HTTP/1.1 '),'original_http_status_required'
            self.status=int(line.split()[1]);headers=b''
            while True:
                part=self.proc.stdout.readline(8192);assert part,'complete_origin_headers_required'
                if part in (b'\\r\\n',b'\\n'):break
                headers+=part;assert len(headers)<=65536,'bounded_origin_headers'
            self.headers=email.parser.BytesParser().parsebytes(headers)
            if self.status!=200:raise urllib.error.HTTPError(url,self.status,'original origin status',self.headers,None)
        except BaseException:
            self.close();raise
    def read(self,size):
        body=self.proc.stdout.read(size)
        if not body:
            code=self.proc.wait(timeout=5)
            if code:raise OSError('native_proxy_curl_failure:'+str(code))
        return body
    def close(self):
        if self.proc.poll() is None:self.proc.kill()
        self.proc.wait(timeout=5)
        self.proc.stdout.close();self.proc.stderr.close()

class QueuedAPTServer(ThreadingHTTPServer):
    request_queue_size=64

'''
s=s.replace('def main():',helper+'def main():',1).replace('response=proxy_opener.open(url,timeout=20)','response=CurlResponse(url)').replace("server=ThreadingHTTPServer(('0.0.0.0',0),Handler)","server=QueuedAPTServer(('0.0.0.0',0),Handler)")
ast.parse(s);target=p/'apt_transport_native_curl10809_v2.next.py';assert not target.exists();target.write_text(s,encoding='utf-8')
folder=HOME/'apt-native-curl-service-staging'/uuid.uuid4().hex;folder.mkdir(parents=True);archive=folder/old.name;archive.write_bytes(old.read_bytes())
pin=save(folder/'result.json',{'atUtc':utc(),'oldSourcePin':public.pin(old),'archivePin':public.pin(archive),'newSourcePin':public.pin(target),'originalAllowedHostsAndSignedAptChecksUnchanged':True,'originalVerifiedCacheReplayUnchanged':True,'streamingBodyNoDuplicateDiskCopy':True,'clientBacklog':64,'servicePublished':False,'models':0,'DockerCalls':0},True)
print(json.dumps({'resultPin':pin,'servicePublished':False}))
