"""Explicit child and public-runtime transport for the original SB HTTP stand."""
import base64,datetime,hashlib,json,os,pathlib,re,subprocess,time
from bound_child_entry import checked_config,child_argv
from native_process import pin
from observed_owned_spawn import spawn_owned
from original_sb_transport import require_original_lease
from remote_native_capture import REMOTE_CAPTURE
from bounded_child import run as bounded_run

def bind_http_config(config):
    _,mapping=checked_config();row=config['schedule'];assert len(row)==1
    verified=require_original_lease(config['resourceOwnerPid'],row[0]['originalResources'])
    original=config['resourceOwnerPid'];lease=verified['verifiedLeasePid'];config['resourceOwnerPid']=lease
    assert lease==int(os.environ['NOVAEVE_RESOURCE_LEASE_PID'])
    os.environ['NOVAEVE_RESOURCE_OWNER_PID']=str(lease)
    import build_environment
    build_environment.ENV['NOVAEVE_RESOURCE_OWNER_PID']=str(lease)
    out=pathlib.Path(config['output']).resolve();out.mkdir(parents=True,exist_ok=True)
    (out/'actual-shared-http-lease-binding.json').write_text(json.dumps(dict(originalOwnerPid=original,verifiedLeasePid=lease,taskId=row[0]['taskId'],verification=verified),indent=2)+'\n')
    return config

def spawn_http_worker(argv,env,stdout,stderr):
    actual=child_argv(argv[0],argv[1:]);record={};prefix=pathlib.Path(stdout.name).with_suffix('.process')
    process=spawn_owned(record,prefix,actual,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    process._bench_http_record=record;process._bench_http_prefix=prefix;process._bench_http_stdout=stdout;process._bench_http_stderr=stderr;process._bench_http_tick=time.monotonic();return process

def finish_http_worker(process):
    assert process.poll() is not None
    process._bench_http_stdout.flush();process._bench_http_stderr.flush()
    row=process._bench_http_record;row.update(finishedAtUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),elapsedSeconds=time.monotonic()-process._bench_http_tick,exitCode=process.returncode,closeObserved=True,stdoutPin=pin(process._bench_http_stdout.name),stderrPin=pin(process._bench_http_stderr.name))
    pathlib.Path(str(process._bench_http_prefix)+'.close.json').write_text(json.dumps(row,indent=2)+'\n')

def copy_runtime_asset(source,cid,destination,expected_labels,receipt_directory,lease_pid=None,ssh_alias='novaeve',resources=None,timeout=180,on_spawn=None,on_closed=None):
    _,config=checked_config();contract=config['skillsbenchRuntimeCopy'];assert contract['protocol']=='bench-skillsbench-runtime-copy-contract-v1'
    assert resources is not None;verified=require_original_lease(lease_pid,resources);lease_pid=verified['verifiedLeasePid']
    assert int(lease_pid)==int(os.environ['NOVAEVE_RESOURCE_LEASE_PID']) and 0<timeout<=180
    assert len(contract['assets'])==4 and {x['destination'] for x in contract['assets']}=={'/rt-lib/libgcc_s.so.1','/rt-lib/libstdc++.so.6','/rt-node','/rt-runtime.mjs'}
    source=pathlib.Path(source).resolve();actual=pin(source);matches=[x for x in contract['assets'] if x['destination']==destination and pathlib.Path(x['sourcePin']['path']).resolve()==source]
    assert len(matches)==1 and (actual['bytes'],actual['sha256'])==(matches[0]['sourcePin']['bytes'],matches[0]['sourcePin']['sha256'])
    assert re.fullmatch('[a-f0-9]{64}',cid) and ssh_alias==contract['sshAlias'] and expected_labels.get('objrun.skb.role')=='full-f-solver' and re.fullmatch('[a-f0-9]{32}',expected_labels.get('objrun.skb.nonce',''))
    for item in [contract['serverHelperPin'],contract['sshExecutablePin']]:assert pin(item['path'])==item
    request=dict(cid=cid,destination=destination,name=source.name,sha256=actual['sha256'],bytes=actual['bytes'],expectedLabels=expected_labels,leasePid=lease_pid,leaseVerifiedWindows=True)
    if actual['bytes']<=10*1024**2:request['smallFileBase64']=base64.b64encode(source.read_bytes()).decode('ascii')
    encoded=base64.b64encode(json.dumps(request).encode()).decode('ascii');server=pathlib.Path(contract['serverHelperPin']['path'])
    program=REMOTE_CAPTURE+'\n'+server.read_text(encoding='utf8')+'\ndef run(args,timeout=180):\n return captured_remote(DOCKER+args,timeout).decode("utf8").strip()\nmain(json.loads(base64.b64decode("'+encoded+'")))\n'
    directory=pathlib.Path(receipt_directory);directory.mkdir(parents=True,exist_ok=True);prefix=directory/(actual['sha256']+'-'+str(time.time_ns()));out=prefix.with_suffix('.stdout');err=prefix.with_suffix('.stderr')
    argv=[contract['sshExecutablePin']['path'],'-T','-o','BatchMode=yes','-o','ConnectTimeout=20','-o','ClearAllForwardings=yes',ssh_alias,'python3','-']
    result=bounded_run(argv,dict(os.environ),out,err,timeout,program.encode(),on_spawn=on_spawn)
    if result['directChildClosed'] and result['pipeReadersClosed'] and on_closed:on_closed(result['pid'])
    receipt=dict(protocol='bench-original-sb-http-runtime-copy-v1',originalSourcePin=matches[0]['sourcePin'],canonicalSourcePin=actual,request=request,argv=argv,transport=result)
    target=prefix.with_suffix('.json');target.write_text(json.dumps(receipt,indent=2)+'\n')
    assert result['exitCode']==0 and not result['faults'] and result['directChildClosed'] and result['pipeReadersClosed']
    frames=[json.loads(line) for line in out.read_text(encoding='utf8').splitlines()];value=frames[-1];commands=[x['remoteCommand'] for x in frames[:-1]]
    assert commands and all(x['pid'] and x['incarnation'] and x['closeObserved'] and x['exitCode']==0 and not x['error'] for x in commands)
    assert value['complete'] and value['cid']==cid and value['destination']==destination and value['sha256']==value['guestSha256']==actual['sha256'] and value['bytes']==actual['bytes'] and value['before']==value['after'] and value['expectedLabels']==expected_labels and value['remoteDockerUploadBytes']==0
    receipt.update(result=value,remoteCommands=commands);target.write_text(json.dumps(receipt,indent=2)+'\n')
    return dict(receiptPin=pin(target),result=value)
