"""Public-runtime cache API. SSH transport never uploads a large cached runtime."""
import argparse,base64,hashlib,json,os,pathlib,re,subprocess,time,ctypes
HERE=pathlib.Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/".phase1-data/terminal-bench/source.json").is_file())
def pin(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return {'path':str(path),'bytes':path.stat().st_size,'sha256':h.hexdigest()}
def copy_runtime_asset(source,cid,destination,expected_labels,receipt_directory,lease_pid=None,ssh_alias='novaeve',timeout_seconds=180):
 source=pathlib.Path(source).resolve();assert source.is_file() and not source.is_symlink()
 assert re.fullmatch(r'[a-f0-9]{64}',cid) and re.fullmatch(r'[a-zA-Z0-9_.-]+',ssh_alias)
 local_pin=pin(source);lease_pid=lease_pid or int(os.environ.get('NOVAEVE_RESOURCE_LEASE_PID',os.getppid()))
 activation_path=pathlib.Path(os.environ.get('NOVAEVE_ACTIVATION_PATH',str(ROOT/'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/activation.json')))
 activation=json.loads(activation_path.read_bytes())
 assert activation.get('active') is True and activation.get('activated') is True and activation['dockerHost']=='tcp://127.0.0.1:18750'
 control_path=pathlib.Path(os.environ.get('NOVAEVE_BROKER_CONTROL_PATH',activation.get('brokerControlPath',activation['controlPath'])))
 assert control_path.resolve()==pathlib.Path(activation.get('brokerControlPath',activation['controlPath'])).resolve()
 control=json.loads(control_path.read_bytes())
 assert control['broker']['endpoint']==activation['brokerEndpoint']
 assert activation.get('brokerRunId',activation['runId'])==control.get('runId',activation['runId'])
 from activation_guard import require_lease
 actual_held= require_lease(24576,32212254720,'terminal-bench',1)
 assert actual_held['verified'] and actual_held['resourceLeasePid']==int(os.environ['NOVAEVE_RESOURCE_PARENT_PID']) and actual_held['resourceSlots']==1,'public_actual_held_resource_lease_missing'
 request={'cid':cid,'destination':destination,'name':source.name,'sha256':local_pin['sha256'],'bytes':local_pin['bytes'],
          'expectedLabels':expected_labels,'leasePid':lease_pid,'leaseVerifiedWindows':True}
 if local_pin['bytes']<=10*1024*1024:request['smallFileBase64']=base64.b64encode(source.read_bytes()).decode('ascii')
 server=HERE/'server_copy_v4.py'
 encoded=base64.b64encode(json.dumps(request).encode()).decode('ascii')
 program=server.read_text(encoding='utf-8')+'\nmain(json.loads(base64.b64decode("'+encoded+'")))\n'
 start=time.monotonic()
 ssh_env=os.environ.copy()
 if os.name=='nt' and not ssh_env.get('PROGRAMDATA'):
  buffer=ctypes.create_unicode_buffer(32768);status=ctypes.windll.shell32.SHGetFolderPathW(None,35,None,0,buffer);assert status==0 and pathlib.Path(buffer.value).is_absolute();ssh_env['PROGRAMDATA']=buffer.value
 assert 0<timeout_seconds<=180
 p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=20',ssh_alias,'python3','-'],input=program.encode(),capture_output=True,timeout=timeout_seconds,env=ssh_env)
 directory=pathlib.Path(receipt_directory);directory.mkdir(parents=True,exist_ok=True)
 prefix=directory/(local_pin['sha256']+'-'+str(time.time_ns()))
 stdout=prefix.with_suffix('.stdout');stderr=prefix.with_suffix('.stderr');stdout.write_bytes(p.stdout);stderr.write_bytes(p.stderr)
 assert p.returncode==0,{'exitCode':p.returncode,'stderrPath':str(stderr),'stderr':p.stderr.decode('utf-8','replace')[-4096:]}
 result=json.loads(p.stdout);assert result['complete'] and result['sha256']==local_pin['sha256'] and result['bytes']==local_pin['bytes'] and result['cid']==cid
 result.update({'localSourcePin':local_pin,'helperSourcePins':[pin(pathlib.Path(__file__)),pin(server)],
   'leasePid':lease_pid,'sshAlias':ssh_alias,'sshExitCode':p.returncode,'stdoutPin':pin(stdout),'stderrPin':pin(stderr),'windowsElapsedSeconds':time.monotonic()-start})
 receipt=prefix.with_suffix('.json');receipt.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
 return {'receiptPin':pin(receipt),'result':result}
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--source',required=True);a.add_argument('--cid',required=True);a.add_argument('--destination',required=True);a.add_argument('--labels-json',required=True);a.add_argument('--receipts',required=True);a.add_argument('--lease-pid',type=int)
 args=a.parse_args();r=copy_runtime_asset(args.source,args.cid,args.destination,json.loads(args.labels_json),args.receipts,args.lease_pid)
 print(json.dumps({'complete':True,'receiptPin':r['receiptPin'],'sha256':r['result']['sha256'],'serverLocalDockerCp':True}))
