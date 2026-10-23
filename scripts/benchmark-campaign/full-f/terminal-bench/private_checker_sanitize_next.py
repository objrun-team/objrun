"""Trusted offline checker entry. Never installed in a solving/worker island."""
import argparse
import base64
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import resource
import re
import sqlite3
import subprocess
import sys
import time


def install_caffe_worker_result(path):
    """Only data from the two exact official CLI operations is admitted."""
    result=json.loads(Path(path).read_bytes())
    assert result['protocol']=='terminal-caffe-worker-data-v1'
    rows=result['rows'];assert isinstance(rows,list) and len(rows)<=2
    binaries={'/app/caffe/.build_release/tools/caffe.bin','/app/caffe/build/tools/caffe'}
    seen=set()
    for row in rows:
        argv=row['argv'];assert isinstance(argv,list) and argv and argv[0] in binaries
        assert isinstance(row['exitCode'],int)
        assert all(isinstance(row[k],str) and len(row[k].encode())<=2*1024**2 for k in ['stdout','stderr'])
        allowed_version=[argv[0],'--version']
        allowed_test=[argv[0],'test','-model','/app/caffe/examples/cifar10/cifar10_quick_train_test.prototxt',
                      '-weights','/app/caffe/examples/cifar10/cifar10_quick_iter_500.caffemodel','-iterations','100']
        assert argv==allowed_version and row['cwd'] is None or argv==allowed_test and row['cwd']=='/app/caffe'
        key=(tuple(argv),row['cwd']);assert key not in seen;seen.add(key)
    def run(argv,*args,**kwargs):
        if args or kwargs.get('capture_output') is not True or kwargs.get('text') is not True or set(kwargs)-{'capture_output','text','cwd'}:
            raise RuntimeError('Unexpected official Caffe subprocess interface')
        matches=[r for r in rows if r['argv']==argv and r['cwd']==kwargs.get('cwd')]
        if len(matches)!=1:raise RuntimeError('Caffe command outside sealed worker data')
        r=matches[0]
        return subprocess.CompletedProcess(argv,r['exitCode'],r['stdout'],r['stderr'])
    subprocess.run=run


def install_pmars_worker_result(path):
    result=json.loads(Path(path).read_bytes())
    assert result['protocol']=='terminal-pmars-worker-data-v1'
    allowed={"echo -e 's\\ns\\ns\\nq' | pmars -e rave.red",
             "echo -e 's\\ns\\ns\\nq' | pmars -e flashpaper.red",
             "pmars -b -r 50 -f flashpaper.red rave.red | tail -n 1",
             "ldd /usr/local/bin/pmars"}
    rows=result['rows'];assert isinstance(rows,list) and len(rows)<=4
    commands=set()
    for row in rows:
        assert row['command'] in allowed and row['command'] not in commands
        commands.add(row['command']);assert isinstance(row['exitCode'],int)
        assert all(isinstance(row[k],str) and len(row[k].encode())<=2*1024**2 for k in ['stdout','stderr'])
    def check_output(command,*args,**kwargs):
        if args or kwargs!={'shell':True,'text':True}:raise RuntimeError('Unexpected official pMARS subprocess interface')
        matches=[r for r in rows if r['command']==command]
        if len(matches)!=1:raise RuntimeError('pMARS command outside sealed worker data')
        row=matches[0]
        if row['exitCode']!=0:raise subprocess.CalledProcessError(row['exitCode'],command,output=row['stdout'])
        return row['stdout']
    subprocess.check_output=check_output


def install_gpt2_result(path):
    result=json.loads(Path(path).read_bytes());assert result['protocol']=='terminal-gpt2-cli-data-v1'
    plans=[(['gcc','-O3','/app/gpt2.c','-lm'],None),
           (['/app/a.out','gpt2-124M.ckpt','vocab.bpe','THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT'],90)]
    rows=result['rows'];assert isinstance(rows,list) and len(rows)<=2
    for row,(argv,timeout) in zip(rows,plans):
        assert row['argv']==argv and row['timeout']==timeout and isinstance(row['exitCode'],int)
        assert row['exception'] in {None,'FileNotFoundError','TimeoutExpired'}
        assert timeout is not None or row['exception']!='TimeoutExpired'
        assert all(isinstance(row[k],str) and len(row[k].encode())<=2*1024**2 for k in ['stdout','stderr'])
        if row['exception']=='TimeoutExpired':
            assert set(row['timeoutStreams'])=={'stdout','stderr'}
            assert all(len(base64.b64decode(value,validate=True))<=2*1024**2 for value in row['timeoutStreams'].values())
    if len(rows)==1:assert rows[0]['exception'] is not None or rows[0]['exitCode']!=0
    if len(rows)==2:assert rows[0]['exception'] is None and rows[0]['exitCode']==0
    position=0
    def run(argv,*args,**kwargs):
        nonlocal position
        if position>=len(rows):raise RuntimeError('GPT2 command outside sealed worker data')
        row=rows[position];expected={'capture_output':True,'text':True}
        if row['timeout'] is not None:expected['timeout']=row['timeout']
        if args or argv!=row['argv'] or kwargs!=expected:raise RuntimeError('Unexpected official GPT2 subprocess interface')
        position+=1
        if row['exception']=='FileNotFoundError':raise FileNotFoundError(argv[0])
        if row['exception']=='TimeoutExpired':
            streams={key:base64.b64decode(value,validate=True) for key,value in row['timeoutStreams'].items()}
            raise subprocess.TimeoutExpired(argv,row['timeout'],output=streams['stdout'],stderr=streams['stderr'])
        return subprocess.CompletedProcess(argv,row['exitCode'],row['stdout'],row['stderr'])
    subprocess.run=run


def install_fixed_cli_result(path,task_id):
    result=json.loads(Path(path).read_bytes())
    assert result['protocol']=='terminal-fixed-cli-data-v1' and result['taskId']==task_id
    plans={'prove-plus-comm':[(['coqc','plus_comm.v'],None,None)],
           'rstan-to-pystan':[(['R','--version'],'/app',30),(['R','--slave','-e','library(rstan)'],'/app',30)],
           'winning-avg-corewars':[(['pmars','-b','-r','100','-f','/app/my_warrior.red','/app/warriors/'+name],None,None)
                                   for name in ['stone.red','vampire.red','paper.red','snake.red','g2-clear.red']]}
    assert task_id in plans
    rows=result['rows']
    if task_id=='winning-avg-corewars':
        assert 1<=len(rows)<=len(plans[task_id])
        assert all(row['exception'] is None and row['exitCode']==0 for row in rows[:-1])
        if len(rows)<len(plans[task_id]):assert rows[-1]['exception'] is not None or rows[-1]['exitCode']!=0
    else:assert len(rows)==len(plans[task_id])
    for row,(argv,cwd,timeout) in zip(result['rows'],plans[task_id]):
        assert row['argv']==argv and row['cwd']==cwd and row['timeout']==timeout
        assert row['exception'] in {None,'FileNotFoundError','TimeoutExpired'} and isinstance(row['exitCode'],int)
        assert all(isinstance(row[k],str) and len(row[k].encode())<=2*1024**2 for k in ['stdout','stderr'])
    def run(argv,*args,**kwargs):
        if args or kwargs.get('capture_output') is not True or kwargs.get('text') is not True or set(kwargs)-{'capture_output','text','cwd','timeout'}:
            raise RuntimeError('Unexpected official fixed CLI interface')
        matches=[r for r in result['rows'] if r['argv']==argv and r['cwd']==kwargs.get('cwd') and r['timeout']==kwargs.get('timeout')]
        if len(matches)!=1:raise RuntimeError('Command outside sealed fixed CLI data')
        row=matches[0]
        if row['exception']=='FileNotFoundError':raise FileNotFoundError(argv[0])
        if row['exception']=='TimeoutExpired':raise subprocess.TimeoutExpired(argv,row['timeout'],output=row['stdout'],stderr=row['stderr'])
        return subprocess.CompletedProcess(argv,row['exitCode'],row['stdout'],row['stderr'])
    subprocess.run=run


def install_povray_cli_result(path):
    result=json.loads(Path(path).read_bytes())
    assert result['protocol']=='terminal-povray-cli-data-v1'
    render=['/usr/local/bin/povray','+L/app/povray-2.2/povdoc/include','+I/app/deps/illum1.pov',
            '+O/app/illum1.tga','+FT','+W640','+H480','+A0.1','+V','-P']
    plans=[(render,'/app'),(['convert','/app/illum1.tga','/app/illum1.png'],None),(['/usr/local/bin/povray','-h'],None)]
    rows=result['rows'];assert isinstance(rows,list) and 2<=len(rows)<=3
    seen=set()
    for row in rows:
        assert (row['argv'],row['cwd']) in plans and row['timeout'] is None
        key=tuple(row['argv']);assert key not in seen;seen.add(key)
        assert isinstance(row['exitCode'],int) and row['exception'] in {None,'FileNotFoundError'}
        assert all(isinstance(row[k],str) and len(row[k].encode())<=2*1024**2 for k in ['stdout','stderr'])
    assert tuple(render) in seen and ('/usr/local/bin/povray','-h') in seen
    def run(argv,*args,**kwargs):
        if args or kwargs.get('capture_output') is not True or kwargs.get('text') is not True or set(kwargs)-{'capture_output','text','cwd'}:
            raise RuntimeError('Unexpected official POV-Ray subprocess interface')
        matches=[r for r in rows if r['argv']==argv and r['cwd']==kwargs.get('cwd')]
        if len(matches)!=1:raise RuntimeError('Command outside sealed POV-Ray data')
        row=matches[0]
        if row['exception']=='FileNotFoundError':raise FileNotFoundError(argv[0])
        return subprocess.CompletedProcess(argv,row['exitCode'],row['stdout'],row['stderr'])
    subprocess.run=run


def install_polyglot_result(path):
    result=json.loads(Path(path).read_bytes());assert result['protocol']=='terminal-polyglot-cli-data-v1'
    plans=[(['gcc','/app/polyglot/main.py.c','-o','/app/polyglot/cmain'],False)]
    for value in ['42','10','0']:
        plans.extend([(['python3','/app/polyglot/main.py.c',value],True),(['/app/polyglot/cmain',value],True)])
    rows=result['rows'];assert isinstance(rows,list) and 0<=len(rows)<=len(plans)
    if not rows:assert not Path('/app/polyglot/main.py.c').exists()
    for index,(row,(argv,capture)) in enumerate(zip(rows,plans)):
        assert row['argv']==argv and row['capture'] is capture
        assert isinstance(row['exitCode'],int) and row['exception'] in {None,'FileNotFoundError'}
        if capture:assert all(isinstance(row[k],str) and len(row[k].encode())<=2*1024**2 for k in ['stdout','stderr'])
        else:assert row['stdout'] is None and row['stderr'] is None
        if row['exception'] is not None or row['exitCode']!=0:assert index==len(rows)-1
    if rows:
        last=rows[-1]
        assert len(rows)==len(plans) or last['exception'] is not None or last['exitCode']!=0
    def run(argv,*args,**kwargs):
        matches=[r for r in rows if r['argv']==argv]
        if len(matches)!=1:raise RuntimeError('Command outside sealed polyglot data')
        row=matches[0]
        expected={'check':True,**({'capture_output':True,'text':True} if row['capture'] else {})}
        if args or kwargs!=expected:raise RuntimeError('Unexpected official polyglot subprocess interface')
        if row['exception']=='FileNotFoundError':raise FileNotFoundError(argv[0])
        if row['exitCode']!=0:raise subprocess.CalledProcessError(row['exitCode'],argv,output=row['stdout'],stderr=row['stderr'])
        return subprocess.CompletedProcess(argv,row['exitCode'],row['stdout'],row['stderr'])
    subprocess.run=run


def install_rust_polyglot_result(path):
    result=json.loads(Path(path).read_bytes());assert result['protocol']=='terminal-rust-polyglot-cli-data-v1'
    plans=[{'kind':'popen','command':'rustc /app/polyglot/main.rs -o /app/polyglot/main'},
           {'kind':'popen','command':'g++ -x c++ /app/polyglot/main.rs -o /app/polyglot/cmain'}]
    for value in ['0','1','2','10','42']:
        plans.extend([{'kind':'run','argv':['/app/polyglot/main',value]},{'kind':'run','argv':['/app/polyglot/cmain',value]}])
    rows=result['rows'];assert isinstance(rows,list) and 0<=len(rows)<=len(plans)
    if not rows:assert not Path('/app/polyglot/main.rs').is_file()
    for index,(row,op) in enumerate(zip(rows,plans)):
        assert all(row[k]==v for k,v in op.items())
        assert isinstance(row['exitCode'],int) and row['exception'] in {None,'FileNotFoundError'}
        assert isinstance(row['stdout'],str) and len(row['stdout'].encode())<=2*1024**2
        if row['kind']=='run':assert isinstance(row['stderr'],str) and len(row['stderr'].encode())<=2*1024**2
        else:assert row['stderr'] is None
        if row['exception'] is not None or (row['kind']=='run' and row['exitCode']!=0):assert index==len(rows)-1
    if rows and len(rows)<len(plans):
        assert rows[-1]['exception'] is not None or (rows[-1]['kind']=='run' and rows[-1]['exitCode']!=0)
    def popen(command,*args,**kwargs):
        if args or kwargs:raise RuntimeError('Unexpected official Rust polyglot popen interface')
        matches=[r for r in rows if r['kind']=='popen' and r['command']==command]
        if len(matches)!=1:raise RuntimeError('Shell command outside sealed Rust polyglot data')
        row=matches[0]
        if row['exception']=='FileNotFoundError':raise FileNotFoundError('/bin/sh')
        return io.StringIO(row['stdout'])
    def run(argv,*args,**kwargs):
        if args or kwargs!={'capture_output':True,'text':True,'check':True}:
            raise RuntimeError('Unexpected official Rust polyglot subprocess interface')
        matches=[r for r in rows if r['kind']=='run' and r['argv']==argv]
        if len(matches)!=1:raise RuntimeError('Program command outside sealed Rust polyglot data')
        row=matches[0]
        if row['exception']=='FileNotFoundError':raise FileNotFoundError(argv[0])
        if row['exitCode']!=0:raise subprocess.CalledProcessError(row['exitCode'],argv,output=row['stdout'],stderr=row['stderr'])
        return subprocess.CompletedProcess(argv,row['exitCode'],row['stdout'],row['stderr'])
    os.popen=popen;subprocess.run=run


def install_git_leak_result(path):
    result=json.loads(Path(path).read_bytes());assert result['protocol']=='terminal-git-leak-cli-data-v1'
    fixed=[['git','-C','/app/repo','log','--all','--grep','secret\\[','--regexp-ignore-case'],
           ['git','-C','/app/repo','log','--all','-p','-S','secret['],
           ['git','-C','/app/repo','log','--oneline','--all'],
           ['git','-C','/app/repo','fsck','--lost-found'],
           ['sh','-c',"find /app/repo -type f -not -path '*/\\.*' -exec sha256sum {} + | sort | sha256sum"]]
    rows=result['rows'];assert isinstance(rows,list) and 5<=len(rows)<=10005
    fsck=next(r for r in rows if r['argv']==fixed[3])
    queries=[line.split()[-1] for line in fsck['stdout'].splitlines() if 'dangling' in line] if fsck['exitCode']==0 and fsck['exception'] is None else []
    allowed_ids=set(queries)
    assert all(re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}',v) for v in allowed_ids)
    for row in rows:
        argv=row['argv']
        assert argv in fixed or (len(argv)==6 and argv[:5]==['git','-C','/app/repo','cat-file','-p'] and argv[5] in allowed_ids)
        assert isinstance(row['exitCode'],int) and row['exception'] in {None,'FileNotFoundError'}
        assert all(isinstance(row[k],str) and len(row[k].encode())<=2*1024**2 for k in ['stdout','stderr'])
    assert all(sum(r['argv']==argv for r in rows)==1 for argv in fixed)
    assert all(sum(r['argv']==['git','-C','/app/repo','cat-file','-p',v] for r in rows)==queries.count(v) for v in allowed_ids)
    cursors={}
    def run(argv,*args,**kwargs):
        if args or kwargs!={'capture_output':True,'text':True}:raise RuntimeError('Unexpected official Git subprocess interface')
        matches=[r for r in rows if r['argv']==argv]
        key=tuple(argv);index=cursors.get(key,0)
        if index>=len(matches):raise RuntimeError('Git command outside sealed query data')
        row=matches[index];cursors[key]=index+1
        if row['exception']=='FileNotFoundError':raise FileNotFoundError(argv[0])
        return subprocess.CompletedProcess(argv,row['exitCode'],row['stdout'],row['stderr'])
    subprocess.run=run


def install_heap_result(path):
    result=json.loads(Path(path).read_bytes());assert result['protocol']=='terminal-heap-cli-data-v1'
    def compile_argv(build):
        flags=['-g','-O0'] if build=='debug' else ['-O2','-DNDEBUG']
        return ['g++','-std=c++17','-o','/app/'+build,'/app/main.cpp','/app/user.cpp',*flags,
                '-L/usr/local/gcc-custom-'+build+'/lib64','-Wl,-Bstatic','-lstdc++','-Wl,-Bdynamic','-lm']
    plans=[(compile_argv('debug'),None),(compile_argv('release'),None),(compile_argv('debug'),None),
           ('/app/debug',10),(compile_argv('release'),None),('/app/release',10),(compile_argv('release'),None),
           (['valgrind','--leak-check=full','--error-exitcode=1','--errors-for-leak-kinds=definite','--quiet','/app/release'],30)]
    rows=result['rows'];assert isinstance(rows,list) and 5<=len(rows)<=8
    cursor=0;compile_ok=False
    for argv,timeout in plans:
        is_compile=isinstance(argv,list) and argv[0]=='g++'
        if not is_compile and not compile_ok:continue
        assert cursor<len(rows);row=rows[cursor];cursor+=1
        assert row['argv']==argv and row['timeout']==timeout and row['kind']==('compile' if is_compile else 'run')
        assert isinstance(row['exitCode'],int) and row['exception'] in {None,'FileNotFoundError','TimeoutExpired'}
        assert all(isinstance(row[k],str) and len(row[k].encode())<=2*1024**2 for k in ['stdout','stderr'])
        if is_compile:
            assert row['binary']==argv[3] and isinstance(row['binaryExists'],bool)
            compile_ok=row['exception'] is None and row['exitCode']==0
    assert cursor==len(rows)
    original_exists=os.path.exists;position=0;existence={}
    def exists(path):
        if str(path) in {'/app/debug','/app/release'}:return existence.get(str(path),False)
        return original_exists(path)
    def run(argv,*args,**kwargs):
        nonlocal position
        if position>=len(rows):raise RuntimeError('Heap operation beyond sealed sequence')
        row=rows[position]
        expected={'capture_output':True,'text':True,**({'timeout':row['timeout']} if row['timeout'] is not None else {})}
        if args or argv!=row['argv'] or kwargs!=expected:raise RuntimeError('Unexpected official heap subprocess interface')
        position+=1
        if row['kind']=='compile':existence[row['binary']]=row['binaryExists']
        if row['exception']=='FileNotFoundError':raise FileNotFoundError(argv[0] if isinstance(argv,list) else argv)
        if row['exception']=='TimeoutExpired':raise subprocess.TimeoutExpired(argv,row['timeout'],output=row['stdout'],stderr=row['stderr'])
        return subprocess.CompletedProcess(argv,row['exitCode'],row['stdout'],row['stderr'])
    os.path.exists=exists;subprocess.run=run


def install_openssl_worker_result(path):
    """Only the exact original script command is delegated to an untrusted island.

    Certificate parsing commands still run the frozen checker image's OpenSSL.
    The candidate script is never imported or executed by this checker.
    """
    result = json.loads(Path(path).read_bytes())
    assert result["protocol"] == "tb12-openssl-untrusted-worker-result-v1"
    assert isinstance(result["exitCode"], int)
    assert all(isinstance(result[key], str) and len(result[key].encode()) <= 1024 ** 2 for key in ("stdout", "stderr"))
    original = subprocess.run
    commands = {
        ("openssl", "rsa", "-in", "/app/ssl/server.key", "-text", "-noout"),
        ("openssl", "x509", "-in", "/app/ssl/server.crt", "-text", "-noout"),
        ("openssl", "x509", "-in", "/app/ssl/server.crt", "-noout", "-dates"),
        ("openssl", "x509", "-in", "/app/ssl/server.pem", "-text", "-noout"),
    }

    def run(argv, *args, **kwargs):
        if args or set(kwargs) != {"capture_output", "text"} or not kwargs["capture_output"] or not kwargs["text"]:
            raise RuntimeError("Unexpected official subprocess interface")
        if tuple(argv) == ("python", "/app/check_cert.py"):
            if result.get("encodingError"):
                error = result["encodingError"]
                raise UnicodeDecodeError(error["encoding"], base64.b64decode(error["objectBase64"], validate=True),
                                         error["start"], error["end"], error["reason"])
            return subprocess.CompletedProcess(argv, result["exitCode"], result["stdout"], result["stderr"])
        if tuple(argv) not in commands:
            raise RuntimeError("Command outside the frozen official OpenSSL interface")
        return original(argv, **kwargs, timeout=30)

    subprocess.run = run


def install_sqlite_guard():
    """Keep the original benchmark queries and PRAGMAs, prohibit mutation/extension.

    SQLite's read-only open and an authorizer protect both the pristine fixture
    and the candidate query. No candidate Python code or custom SQLite UDF runs.
    """
    original = sqlite3.connect
    blocked = {getattr(sqlite3, name) for name in (
        "SQLITE_CREATE_INDEX", "SQLITE_CREATE_TABLE", "SQLITE_CREATE_TEMP_INDEX",
        "SQLITE_CREATE_TEMP_TABLE", "SQLITE_CREATE_TEMP_TRIGGER", "SQLITE_CREATE_TEMP_VIEW",
        "SQLITE_CREATE_TRIGGER", "SQLITE_CREATE_VIEW", "SQLITE_DELETE", "SQLITE_DROP_INDEX",
        "SQLITE_DROP_TABLE", "SQLITE_DROP_TEMP_INDEX", "SQLITE_DROP_TEMP_TABLE",
        "SQLITE_DROP_TEMP_TRIGGER", "SQLITE_DROP_TEMP_VIEW", "SQLITE_DROP_TRIGGER",
        "SQLITE_DROP_VIEW", "SQLITE_INSERT", "SQLITE_UPDATE", "SQLITE_ATTACH",
        "SQLITE_DETACH", "SQLITE_ALTER_TABLE", "SQLITE_REINDEX", "SQLITE_ANALYZE",
        "SQLITE_CREATE_VTABLE", "SQLITE_DROP_VTABLE",
    )}
    allowed_pragmas = {("temp_store", "MEMORY"), ("cache_size", "-100000"), ("case_sensitive_like", "OFF"), ("optimize", None)}

    def authorize(action, first, second, database, trigger):
        if action in blocked:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and str(second).lower() in {"load_extension", "readfile", "writefile"}:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_PRAGMA and (str(first).lower(), str(second).upper() if second is not None else None) not in allowed_pragmas:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def connect(database, *args, **kwargs):
        if str(database) != "file:/app/oewn.sqlite?mode=ro" or kwargs.get("uri") is not True:
            raise RuntimeError("SQLite open outside the read-only original fixture")
        connection = original(database, *args, **kwargs)
        connection.enable_load_extension(False)
        connection.set_authorizer(authorize)
        return connection

    sqlite3.connect = connect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_bytes())
    assert config["protocol"] == "tb12-private-checker-config-v1"
    if "checkerSourceSha256" in config:
        assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == config["checkerSourceSha256"]
    task_id = config["taskId"]
    start_wall, start_mono = time.time(), time.monotonic()
    assert sys.version_info[:2] == (3, 13)
    limit = int(config["verifierSeconds"])
    # Frozen official 2.1 verifier limits reach 12000 seconds (POV-Ray).
    assert 0 < limit <= 12000
    resource.setrlimit(resource.RLIMIT_CPU, (limit, limit + 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    import pytest
    versions = {name: importlib.metadata.version(name) for name in config["packages"] if name != "chess"}
    for name, expected in config["packages"].items():
        if name != "chess":
            assert versions[name] == expected, (name, versions[name], expected)
    for name, expected in config["officialTestHashes"].items():
        path = Path("/tests") / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name
    if not args.collect_only:
        assert task_id=='sanitize-git-repo'
        from importlib.util import spec_from_file_location,module_from_spec
        source=Path('/opt/tb12/checker/sanitize_private_router_next.py')
        assert hashlib.sha256(source.read_bytes()).hexdigest()==config['routerSourceSha256']
        spec=spec_from_file_location('trusted_circuit_router',source);module=module_from_spec(spec);spec.loader.exec_module(module)
        module.install(config['sanitizeWorkerResult'])
    target = "/tmp/ctrf.json"
    command = ["-p", "ctrf.main", "--ctrf", target, "/tests/test_outputs.py", "-rA", "-o", "cache_dir=/tmp/pytest-cache"]
    if args.collect_only:
        command.insert(0, "--collect-only")
    exit_code = int(pytest.main(command))
    raw = Path(target).read_bytes() if Path(target).exists() else b""
    if len(raw) > 2 * 1024 ** 2:
        raise RuntimeError("CTRF receipt exceeded frozen capture boundary")
    ctrf = json.loads(raw) if raw else None
    assert not Path("/tmp/isolation-fault.json").exists(), "Private adapter transport fault"
    result = {"protocol": "tb12-private-checker-result-v1", "invocationId": config["invocationId"], "taskId": task_id, "collectOnly": args.collect_only, "exitCode": exit_code, "reward": int(exit_code == 0 and not args.collect_only), "ctrf": ctrf, "ctrfRawSha256": hashlib.sha256(raw).hexdigest(), "pythonVersion": sys.version, "pythonExecutable": sys.executable, "pythonExecutableSha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(), "checkerSourceSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "numericGuestPid": os.getpid(), "numericParentPid": os.getppid(), "procStatus": Path("/proc/self/status").read_text(), "mountInfoSha256": hashlib.sha256(Path("/proc/self/mountinfo").read_bytes()).hexdigest(), "packages": versions, "privateNamespaces": {name: os.readlink("/proc/self/ns/" + name) for name in ("pid", "mnt", "net")}, "wallStart": start_wall, "wallStop": time.time(), "monotonicSeconds": time.monotonic() - start_mono}
    # Final frame comes from trusted code after pytest; worker output remains JSON
    # string data. Host requires this final frame, invocation ID and actual exit.
    print("TB12_RESULT:" + json.dumps(result, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
