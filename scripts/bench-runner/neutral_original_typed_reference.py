"""Reference-only original phase, typed profile retained, with real bridge proxy."""
import argparse,pathlib,json,urllib.request,urllib.error
from native_process import pin
from native_snapshot_control import run_control
from docker_owned import OwnedDocker
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=False)
 assert _bench_authorized_history('zero-model-owned-sb-asset') is True
 context=out/'context';context.mkdir();profile={'kind':'caffe-worker','artifacts':{'/app/value.txt':128}}
 task=dict(taskId='neutral-snapshot-control',agentSeconds=60,verifierSeconds=60,officialEnvironment=dict(memory_mb=2048,cpus=1,allow_internet=True,storage_mb=10240))
 manifest=context/'context-manifest.json';manifest.write_text(json.dumps(dict(tasks=[task]))+'\n')
 script=out/'public-reference.sh';script.write_bytes(b'''set -eu
mkdir -p /app
printf 'neutral-reference-only\n' > /app/value.txt
test "$http_proxy" = 'http://172.30.89.1:10809'
exec 3<>/dev/tcp/172.30.89.1/10809
printf 'GET http://archive.ubuntu.com/ubuntu/dists/noble/InRelease HTTP/1.1\r\nHost: archive.ubuntu.com\r\nConnection: close\r\n\r\n' >&3
IFS= read -r status <&3
case "$status" in 'HTTP/1.1 200'*|'HTTP/1.0 200'*) ;; *) printf '%s\n' "$status"; exit 9;; esac
printf '%s\n' "$status"
cat <&3
''')
 request=dict(protocol='bench-neutral-snapshot-control-phase-v1',neutralPolicyTaskId='zero-model-owned-sb-asset',taskId='neutral-snapshot-control',profile=profile,phase='reference',label='reference',contextDirectory=str(context),contextPin=pin(manifest),candidateImage='sha256:69f919497cada9a8611f3de61df902d9f94bf20f84552ef5bd93125c38608ef9',referenceFile=str(script),referencePin=pin(script),phaseSeconds=60)
 reference=run_control(request,out/'original-reference');assert reference['complete'] and reference['privateQualificationOnly'] and not reference['eligibleForPaidCandidate']
 assert reference['referenceExecution']['exitCode']==0
 cleanup=OwnedDocker(out/'cleanup-native')
 try:
  removed=cleanup.checked(['image','rm','--no-prune',reference['referenceImage']])
  try:urllib.request.urlopen(__import__('os').environ['DOCKER_HOST'].replace('tcp:','http:')+'/images/'+reference['referenceImage']+'/json',timeout=10);raise AssertionError('reference_image_still_present')
  except urllib.error.HTTPError as ex:assert ex.code==404
 finally:cleanup.close()
 (out/'result.json').write_text(json.dumps(dict(complete=True,originalReferenceOnly=True,originalTypedProfilePreserved=True,actualBridgeProxyHttp200=True,originalUploadedReferenceExecuted=True,allOwnedReferenceActorsClosed=True,privateReferenceImageRemoved=True,reference=reference,imageRemoval=removed,modelCalls=0,referenceCalls=0,gradeCalls=0,noBenchContent=True),indent=2)+'\n')
if __name__=='__main__':main()
