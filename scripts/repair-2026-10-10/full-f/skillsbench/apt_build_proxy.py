"""Use only a live source-pinned public APT service in temporary build args."""
import json
from pathlib import Path
from prepare import HOME,public

def build_args():
    # Explicit human-authorized local proxy. Original URLs/packages unchanged.
    proxy='http://host.docker.internal:10809'
    cached_args=verified_legacy_apt_build_args()
    assert cached_args, 'verified_original_apt_cache_proxy_required'
    apt_proxy=cached_args[-1].split('=',1)[1]
    return [*cached_args,'--build-arg','HTTP_PROXY='+apt_proxy,'--build-arg','https_proxy='+proxy,'--build-arg','HTTPS_PROXY='+proxy]

def verified_legacy_apt_build_args():
    pointer=HOME/'apt-transport-service/latest.json'
    if not pointer.exists():return []
    pin=json.loads(pointer.read_bytes())['servicePin'];assert public.pin(Path(pin['path']))==pin
    service=json.loads(Path(pin['path']).read_bytes());assert service['protocol']=='skillsbench-official-apt-transport-v1'
    assert public.pin(Path(service['sourcePin']['path']))==service['sourcePin']
    proof=json.loads((HOME/'apt-docker-transport-controls/latest.json').read_bytes())['resultPin'];assert public.pin(Path(proof['path']))==proof
    tested=json.loads(Path(proof['path']).read_bytes())
    assert tested.get('verified') and tested.get('ownedContainersRemaining')==0 and tested['servicePin']==pin
    assert public.pin(Path(tested['sourcePin']['path']))==tested['sourcePin']
    port=service['port'];assert isinstance(port,int) and 1<=port<=65535
    return ['--build-arg','http_proxy=http://host.docker.internal:'+str(port)]
