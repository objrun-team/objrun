"""Durable actual-process observation of the unchanged adopted TS guard decision."""
import datetime,hashlib,json,os,pathlib,subprocess,time,traceback,uuid
from native_process import pin
from observed_owned_spawn import spawn_owned
_CACHE=None

def contract():
    global _CACHE
    path=pathlib.Path(os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']).resolve();raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest();assert digest==os.environ['NOVAEVE_PYTHON_MAPPING_SHA256']
    if _CACHE is not None:
        assert _CACHE[0]==str(path) and _CACHE[1]==digest
        return _CACHE[2]
    config=json.loads(raw);c=config['adoptedGuardCapture'];assert c['protocol']=='bench-adopted-guard-process-capture-v1'
    for item in [c['bunPin'],c['bridgePin']]:assert pin(item['path'])==item
    directory=pathlib.Path(config['childEvidenceRoot']).resolve()/'guard-bridge-processes';root=pathlib.Path(c['root']).resolve();assert directory.is_relative_to(root/'docs/repair-2026-10-10/full-f-rerun');directory.mkdir(parents=True,exist_ok=True)
    c={**c,'directory':str(directory)};_CACHE=(str(path),digest,c);return c

def run_guard_bridge(argv,**kwargs):
    c=contract();assert len(argv)==4 and pathlib.Path(argv[0]).resolve()==pathlib.Path(c['bunPin']['path']).resolve() and argv[1]=='--smol' and pathlib.Path(argv[2]).resolve()==pathlib.Path(c['bridgePin']['path']).resolve()
    assert str(pathlib.Path(argv[3]).resolve()) in [str(pathlib.Path(x).resolve()) for x in c['allowedActivationPaths']]
    assert pathlib.Path(kwargs['cwd']).resolve()==pathlib.Path(c['root']).resolve() and kwargs['timeout']==15 and kwargs['stdin']==subprocess.DEVNULL and kwargs['stdout']==kwargs['stderr']==subprocess.PIPE
    prefix=pathlib.Path(c['directory'])/(str(os.getpid())+'-'+uuid.uuid4().hex);row={};started=time.monotonic();process=None;out=b'';err=b'';timeout_error=None;failure=None
    try:
        process=spawn_owned(row,prefix,argv,cwd=kwargs['cwd'],stdin=kwargs['stdin'],stdout=kwargs['stdout'],stderr=kwargs['stderr'],creationflags=kwargs['creationflags'])
        try:out,err=process.communicate(timeout=15)
        except subprocess.TimeoutExpired as error:
            timeout_error=error;process.kill();out,err=process.communicate()
    except BaseException as error:
        failure=error
        if process is not None and process.poll() is not None:
            try:out,err=process.communicate()
            except BaseException:pass
    finally:
        stdout=pathlib.Path(str(prefix)+'.stdout');stderr=pathlib.Path(str(prefix)+'.stderr');stdout.write_bytes(out);stderr.write_bytes(err)
        row.update(protocol='bench-adopted-guard-bridge-process-v1',finishedAtUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),elapsedSeconds=time.monotonic()-started,exitCode=process.returncode if process else None,closeObserved=process is not None and process.poll() is not None,timedOut=timeout_error is not None,error=None if failure is None else dict(type=type(failure).__name__,message=str(failure)),stdoutPin=pin(stdout),stderrPin=pin(stderr),executablePin=c['bunPin'],bridgePin=c['bridgePin'])
        pathlib.Path(str(prefix)+'.json').write_text(json.dumps(row,indent=2)+'\n')
    if failure is not None:raise failure
    if timeout_error is not None:raise subprocess.TimeoutExpired(argv,15,output=out,stderr=err)
    return subprocess.CompletedProcess(argv,process.returncode,out,err)
