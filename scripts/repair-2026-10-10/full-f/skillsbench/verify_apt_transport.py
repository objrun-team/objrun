"""Local URL authority controls, not Docker/network verification."""
from pathlib import Path
import uuid
from prepare import HOME,public,save
import apt_transport

def main():
    cases=[]
    assert apt_transport.official_https('http://deb.debian.org/debian/pool/a.deb')=='https://deb.debian.org/debian/pool/a.deb';cases.append('same_official_repository_and_path_https')
    for name,url in [('supplier','http://openrouter.ai/ubuntu/payload'),('host_file','file:///etc/passwd'),('localhost','http://127.0.0.1/ubuntu/key'),
        ('credentials','http://user:password@deb.debian.org/debian/a.deb'),('query','http://deb.debian.org/debian/a.deb?key=value'),('port','http://deb.debian.org:8080/debian/a.deb'),('foreign_path','http://deb.debian.org/private/key')]:
        try:apt_transport.official_https(url)
        except ValueError:cases.append(name)
        else:raise AssertionError('unrejected_'+name)
    home=HOME/'apt-transport-local-controls'/uuid.uuid4().hex;home.mkdir(parents=True)
    pin=save(home/'result.json',{'protocol':'skillsbench-apt-transport-local-controls-v1','verified':True,'cases':cases,'modelCalls':0,'realDockerTransportVerified':False,
        'sourcePins':[public.pin(Path(apt_transport.__file__)),public.pin(Path(__file__))]},True)
    save(HOME/'apt-transport-local-controls/latest.json',{'resultPin':pin});print({'resultPin':pin,'cases':len(cases)})

if __name__=='__main__':main()
