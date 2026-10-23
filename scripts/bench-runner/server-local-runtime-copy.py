"""Hash-pinned server-local runtime copy; no large upload fallback or task policy."""
import base64,hashlib,json,pathlib,re,subprocess,time,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
from native_process import capture
from remote_native_capture import REMOTE_CAPTURE

def pin(path):
 p=pathlib.Path(path);h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return {'path':str(p),'bytes':p.stat().st_size,'sha256':h.hexdigest()}

def verify(p):
 actual=pin(p['path']);assert actual['bytes']==p['bytes'] and actual['sha256']==p['sha256'],'runtime_cache_pin_changed'
 return actual

def copy_cached_runtime(native,source,cid,destination,contract):
 assert contract['protocol']=='bench-server-local-runtime-copy-contract-v1'
 source=pathlib.Path(source).resolve()
 assert source.name==contract['assetName'] and destination==contract['destination'],'runtime_cache_asset_scope'
 actual=pin(source)
 assert (actual['sha256'],actual['bytes'])==(contract['assetSha256'],contract['assetBytes']),'runtime_cache_asset_changed'
 assert re.fullmatch('[a-f0-9]{64}',cid) and re.fullmatch('[A-Za-z0-9_.-]+',contract['sshAlias'])
 helper=verify(contract['serverHelperPin'])
 native.guard();actor=native.assert_actor(cid)
 labels={k:actor['Labels'][k] for k in ('objrun.tb12.owner','objrun.tb12.role','objrun.tb12.native-source')}
 request={'cid':cid,'destination':destination,'name':source.name,'sha256':actual['sha256'],'bytes':actual['bytes'],'expectedLabels':labels,'leasePid':int(__import__('os').environ['NOVAEVE_RESOURCE_LEASE_PID']),'leaseVerifiedWindows':True}
 # The frozen helper rejects cache misses for assets >10 MiB and verifies full NAS and guest bytes.
 encoded=base64.b64encode(json.dumps(request).encode()).decode('ascii')
 program=REMOTE_CAPTURE+'\n'+pathlib.Path(helper['path']).read_text(encoding='utf-8')+'\ndef run(args,timeout=180):\n return captured_remote(DOCKER+args,timeout).decode("utf8").strip()\nmain(json.loads(base64.b64decode("'+encoded+'")))\n'
 directory=native.directory/'server-local-runtime-cache';directory.mkdir(parents=True,exist_ok=True)
 prefix=directory/(actual['sha256']+'-'+str(time.time_ns()));started=time.monotonic()
 intent={'protocol':'bench-server-local-runtime-copy-intent-v1','sourcePin':actual,'serverHelperPin':helper,'request':request,'modelCalls':0}
 prefix.with_suffix('.intent.json').write_text(json.dumps(intent,indent=2)+'\n',encoding='utf-8')
 executable=contract.get('sshExecutablePin')
 assert executable,'explicit_pinned_ssh_executable_required'
 verify(executable)
 execution=capture([executable['path'],'-T','-o','BatchMode=yes','-o','ConnectTimeout=20','-o','ClearAllForwardings=yes',contract['sshAlias'],'python3','-'],prefix.with_suffix('.process'),240,input_bytes=program.encode())
 receipt={'protocol':'bench-server-local-runtime-copy-receipt-v1','intent':intent,**execution}
 receipt_path=prefix.with_suffix('.json');receipt_path.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
 assert execution['closeObserved'] and not execution['timedOut'] and not execution['error'] and execution['exitCode']==0,{'runtime_cache_copy_failed':str(receipt_path)}
 frames=[json.loads(line) for line in pathlib.Path(execution['stdoutPin']['path']).read_text().splitlines()]
 result=frames[-1]
 receipt['remoteCommands']=[frame['remoteCommand'] for frame in frames[:-1]]
 assert receipt['remoteCommands'] and all(row['pid'] and row['incarnation'] and row['closeObserved'] and row['exitCode']==0 and not row['error'] for row in receipt['remoteCommands']),'remote_runtime_command_identity_missing'
 receipt_path.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
 assert result['protocol']=='novaeve-server-local-runtime-copy-v4' and result['complete'] is True and result['cid']==cid and result['destination']==destination and result['sha256']==actual['sha256'] and result['guestSha256']==actual['sha256'] and result['bytes']==actual['bytes'] and result['expectedLabels']==labels and result['before']==result['after'] and result['remoteDockerUploadBytes']==0,'runtime_cache_copy_result_mismatch'
 native.guard();native.assert_actor(cid)
 return {'receiptPin':pin(receipt_path),'result':result,'serverLocalRuntimeCache':True}
