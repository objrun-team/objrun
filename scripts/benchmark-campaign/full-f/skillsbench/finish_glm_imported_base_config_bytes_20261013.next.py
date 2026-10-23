"""Finish config custody for the already imported original base, without another download/import."""
import hashlib,json,subprocess,tarfile,threading,time
from prepare import HOME,public,save,utc
from build_environment import DOCKER,ENV
out=HOME.parent/'efficient-resume-20261012/glm-original-base-proxy-20261013'
tag='objrun-skb-glm-original-base:ubuntu20-20261013'
config_path=out/'blobs-b7bab04fd9aa0c771e5720bf0cc7cbf993fd6946645983d9096126e5af45d713.json'
raw=config_path.read_bytes();config=json.loads(raw)
inspect=json.loads(subprocess.check_output([DOCKER,'image','inspect',tag],env=ENV,timeout=30))[0]
assert inspect['RootFS']['Layers']==config['rootfs']['diff_ids']
assert inspect['Architecture']==config['architecture'] and inspect['Os']==config['os']
assert all(config['config'].get(key)==value for key,value in inspect['Config'].items())
# image inspect omits legacy empty/default fields and build Image metadata.
# The archive check below still requires the complete original config byte-for-byte.
assert not (out/'export-config-proof.json').exists(),'config_export_already_verified'
with (out/'config-export.stderr').open('wb') as stderr:
    process=subprocess.Popen([DOCKER,'image','save',tag],env=ENV,stdout=subprocess.PIPE,stderr=stderr)
    timer=threading.Timer(90,process.kill);timer.start();matches=[];total=0
    try:
        with tarfile.open(fileobj=process.stdout,mode='r|') as tar:
            for member in tar:
                total+=member.size;assert total<=512*1024**2
                if member.isfile() and member.size==len(raw):
                    body=tar.extractfile(member).read()
                    if body==raw:matches.append(member.name)
        assert process.wait(timeout=10)==0 and matches
    finally:
        timer.cancel()
        if process.poll() is None:process.kill();process.wait()
proof={'atUtc':utc(),'configPin':public.pin(config_path),'exactConfigArchiveMembers':matches,'rootFSDiffIds':inspect['RootFS']['Layers'],'dockerImageId':inspect['Id'],'transportIdentity':'containerd converted Docker archive manifest; config bytes and original rootfs unchanged','newDownloads':0,'newImports':0,'modelCalls':0}
save(out/'export-config-proof.json',proof)
manifest_path=out/'manifests-c664f8f86ed5a386b0a340d981b8f81714e21a8b9c73f658c4bea56aa179d54a.json'
save(out/'base.json',{'atUtc':utc(),'tag':tag,'imageId':inspect['Id'],'originalRef':'ubuntu:20.04','manifestDigest':'sha256:c664f8f86ed5a386b0a340d981b8f81714e21a8b9c73f658c4bea56aa179d54a','manifestPin':public.pin(manifest_path),'configPin':public.pin(config_path),'archivePin':public.pin(out/'original-ubuntu20-docker.tar'),'originalConfigAndLayersVerified':True,'importVerificationPin':public.pin(out/'export-config-proof.json'),'modelCalls':0})
print(json.dumps({'originalBaseValidated':True,'imageId':inspect['Id'],'newDownloads':0,'newImports':0,'modelCalls':0}))
