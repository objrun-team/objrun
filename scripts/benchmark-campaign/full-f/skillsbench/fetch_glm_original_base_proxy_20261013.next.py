"""Fetch only the task's original Ubuntu 20.04 amd64 base through the approved proxy."""
import gzip, hashlib, io, json, os, subprocess, tarfile, time
from pathlib import Path
import requests
from prepare import HOME, public, save, utc
from build_environment import DOCKER, ENV

out = HOME.parent/'efficient-resume-20261012/glm-original-base-proxy-20261013'
tag = 'objrun-skb-glm-original-base:ubuntu20-20261013'
assert not (out/'fetch-attempt.json').exists(), 'single_bounded_base_fetch_already_attempted'
save(out/'fetch-attempt.json', {'pid':os.getpid(), 'atUtc':utc(), 'modelCalls':0})
began = time.monotonic()
s = requests.Session(); s.trust_env=False
s.proxies={'http':'http://127.0.0.1:10809','https':'http://127.0.0.1:10809'}
token=s.get('https://auth.docker.io/token',params={'service':'registry.docker.io','scope':'repository:library/ubuntu:pull'},timeout=30)
token.raise_for_status()
headers={'Authorization':'Bearer '+token.json()['token'],'Accept':','.join(['application/vnd.oci.image.index.v1+json','application/vnd.docker.distribution.manifest.list.v2+json','application/vnd.oci.image.manifest.v1+json','application/vnd.docker.distribution.manifest.v2+json'])}
base='https://registry-1.docker.io/v2/library/ubuntu/'
def get_small(kind,ref):
    response=s.get(base+kind+'/'+ref,headers=headers,timeout=45)
    response.raise_for_status(); body=response.content
    assert len(body)<=2*1024**2
    digest='sha256:'+hashlib.sha256(body).hexdigest()
    if ref.startswith('sha256:'): assert digest==ref
    p=out/(kind+'-'+digest[7:]+'.json'); p.write_bytes(body)
    return json.loads(body),p,digest
index,index_path,_=get_small('manifests','20.04')
matches=[m for m in index['manifests'] if m.get('platform',{}).get('os')=='linux' and m.get('platform',{}).get('architecture')=='amd64']
assert len(matches)==1
manifest,manifest_path,manifest_digest=get_small('manifests',matches[0]['digest'])
config,config_path,config_digest=get_small('blobs',manifest['config']['digest'])
assert config['os']=='linux' and config['architecture']=='amd64'
assert sum(layer['size'] for layer in manifest['layers'])<256*1024**2
assert len(manifest['layers'])==len(config['rootfs']['diff_ids'])
layers=[]
for i,layer in enumerate(manifest['layers']):
    compressed=out/(layer['digest'][7:]+'.tar.gz')
    with s.get(base+'blobs/'+layer['digest'],headers=headers,timeout=(30,45),stream=True) as response:
        response.raise_for_status(); total=0; digest=hashlib.sha256()
        with compressed.open('xb') as f:
            for chunk in response.iter_content(1024**2):
                assert time.monotonic()-began<300, 'base_fetch_deadline'
                total+=len(chunk); assert total<=layer['size']
                digest.update(chunk);f.write(chunk)
    assert total==layer['size'] and 'sha256:'+digest.hexdigest()==layer['digest']
    unpacked=out/(layer['digest'][7:]+'-layer.tar'); total=0; digest=hashlib.sha256()
    with gzip.open(compressed,'rb') as source,unpacked.open('xb') as dest:
        while chunk:=source.read(1024**2):
            total+=len(chunk);assert total<=512*1024**2
            digest.update(chunk);dest.write(chunk)
    assert 'sha256:'+digest.hexdigest()==config['rootfs']['diff_ids'][i]
    layers.append(unpacked)
archive=out/'original-ubuntu20-docker.tar'
with tarfile.open(archive,'w') as tar:
    config_name=config_digest[7:]+'.json';tar.add(config_path,arcname=config_name)
    names=[]
    for i,layer in enumerate(layers):
        name=str(i)+'/layer.tar';tar.add(layer,arcname=name);names.append(name)
    data=json.dumps([{'Config':config_name,'RepoTags':[tag],'Layers':names}]).encode()
    info=tarfile.TarInfo('manifest.json');info.size=len(data);tar.addfile(info,io.BytesIO(data))
with (out/'load.stdout').open('wb') as stdout,(out/'load.stderr').open('wb') as stderr:
    p=subprocess.run([DOCKER,'load','--input',str(archive)],env=ENV,stdout=stdout,stderr=stderr,timeout=180)
assert p.returncode==0,'original_base_load_failed'
inspect=json.loads(subprocess.check_output([DOCKER,'image','inspect',tag],env=ENV,timeout=30))[0]
assert inspect['Id']==config_digest and inspect['RootFS']['Layers']==config['rootfs']['diff_ids']
assert inspect['Os']=='linux' and inspect['Architecture']=='amd64'
save(out/'base.json',{'atUtc':utc(),'tag':tag,'imageId':inspect['Id'],'originalRef':'ubuntu:20.04','manifestDigest':manifest_digest,'manifestPin':public.pin(manifest_path),'configPin':public.pin(config_path),'archivePin':public.pin(archive),'originalConfigAndLayersVerified':True,'modelCalls':0})
print(json.dumps({'baseReady':True,'tag':tag,'imageId':inspect['Id'],'modelCalls':0}))
