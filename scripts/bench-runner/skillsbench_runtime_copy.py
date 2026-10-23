"""Pinned public runtime copy for the existing SkillsBench cache child API."""
import base64,hashlib,json,os,pathlib,re,time
from native_process import capture,pin
from remote_native_capture import REMOTE_CAPTURE
import _bench_original_owned_guard as guard

def copy_runtime_asset(source,cid,destination,expected_labels,receipt_directory,lease_pid=None,ssh_alias='novaeve',*,memory_mb=None,growth_bytes=None,slug=None,slots=None):
 config_path=pathlib.Path(os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']);raw=config_path.read_bytes()
 assert hashlib.sha256(raw).hexdigest()==os.environ['NOVAEVE_PYTHON_MAPPING_SHA256']
 config=json.loads(raw);contract=config['skillsbenchRuntimeCopy'];resource=config['resource'];assert contract['protocol']=='bench-skillsbench-runtime-copy-contract-v1'
 assert len(contract['assets'])==4 and {asset['destination'] for asset in contract['assets']}=={'/rt-lib/libgcc_s.so.1','/rt-lib/libstdc++.so.6','/rt-node','/rt-runtime.mjs'},'exact_four_public_runtime_destinations_required'
 assert resource['bench']=='skillsbench' and type(resource['memoryMb']) is int and resource['memoryMb']>0 and type(resource['growthBytes']) is int and resource['growthBytes']>0
 assert int(lease_pid)==int(os.environ['NOVAEVE_RESOURCE_OWNER_PID'])==int(os.environ['NOVAEVE_RESOURCE_LEASE_PID'])
 assert all(value is None or value==expected for value,expected in [(memory_mb,resource['memoryMb']),(growth_bytes,resource['growthBytes']),(slug,'skillsbench'),(slots,1)])
 guard.require_lease(resource['memoryMb'],resource['growthBytes'],'skillsbench',1)
 source=pathlib.Path(source).resolve();actual=pin(source)
 matches=[asset for asset in contract['assets'] if asset['destination']==destination and pathlib.Path(asset['sourcePin']['path']).resolve()==source]
 assert len(matches)==1 and (actual['bytes'],actual['sha256'])==(matches[0]['sourcePin']['bytes'],matches[0]['sourcePin']['sha256']),'exact_public_runtime_asset_required'
 assert re.fullmatch('[a-f0-9]{64}',cid) and ssh_alias==contract['sshAlias'] and expected_labels.get('objrun.skb.role')=='full-f-solver' and re.fullmatch('[a-f0-9]{32}',expected_labels.get('objrun.skb.nonce',''))
 def check(p):
  assert pin(p['path'])==p,'skillsbench_runtime_transport_pin_changed'
  return pathlib.Path(p['path'])
 server=check(contract['serverHelperPin']);ssh=check(contract['sshExecutablePin'])
 request={'cid':cid,'destination':destination,'name':source.name,'sha256':actual['sha256'],'bytes':actual['bytes'],'expectedLabels':expected_labels,'leasePid':lease_pid,'leaseVerifiedWindows':True}
 if actual['bytes']<=10*1024*1024:request['smallFileBase64']=base64.b64encode(source.read_bytes()).decode('ascii')
 encoded=base64.b64encode(json.dumps(request).encode()).decode('ascii')
 program=REMOTE_CAPTURE+'\n'+server.read_text(encoding='utf8')+'\ndef run(args,timeout=180):\n return captured_remote(DOCKER+args,timeout).decode("utf8").strip()\nmain(json.loads(base64.b64decode("'+encoded+'")))\n'
 directory=pathlib.Path(receipt_directory);directory.mkdir(parents=True,exist_ok=True);prefix=directory/(actual['sha256']+'-'+str(time.time_ns()))
 intent={'originalSourcePin':matches[0]['sourcePin'],'canonicalSourcePin':actual,'canonicalSourcePath':str(source),'request':request,'serverHelperPin':contract['serverHelperPin'],'sshPin':contract['sshExecutablePin']}
 prefix.with_suffix('.intent.json').write_text(json.dumps(intent,indent=2)+'\n')
 execution=capture([str(ssh),'-T','-o','BatchMode=yes','-o','ConnectTimeout=20','-o','ClearAllForwardings=yes',ssh_alias,'python3','-'],prefix.with_suffix('.process'),240,input_bytes=program.encode())
 receipt={'protocol':'bench-skillsbench-server-local-runtime-copy-v1','intent':intent,**execution};path=prefix.with_suffix('.json');path.write_text(json.dumps(receipt,indent=2)+'\n')
 assert execution['closeObserved'] and execution['exitCode']==0 and not execution['timedOut'] and not execution['error'],'actual_skillsbench_runtime_copy_failed'
 frames=[json.loads(line) for line in pathlib.Path(execution['stdoutPin']['path']).read_text().splitlines()];result=frames[-1];commands=[frame['remoteCommand'] for frame in frames[:-1]]
 assert commands and all(row['pid'] and row['incarnation'] and row['closeObserved'] and row['exitCode']==0 and not row['error'] for row in commands)
 assert result['complete'] and result['cid']==cid and result['destination']==destination and result['sha256']==actual['sha256'] and result['guestSha256']==actual['sha256'] and result['bytes']==actual['bytes'] and result['expectedLabels']==expected_labels and result['before']==result['after'] and result['remoteDockerUploadBytes']==0
 guard.require_lease(resource['memoryMb'],resource['growthBytes'],'skillsbench',1)
 receipt.update(result=result,remoteCommands=commands);path.write_text(json.dumps(receipt,indent=2)+'\n')
 return {'receiptPin':pin(path),'result':result}
