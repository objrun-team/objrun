"""Project-only Docker lifecycle on Novaeve. No system services or disk changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

NAS = Path('/mnt/aliyunsb/pingxingwang/tgengin-bench')
DATA = Path('/data/wpx/tgengin')
CONFIG = NAS / 'runtime/daemon.json'
SOCKET = DATA / 'run/docker.sock'
GLOBALS = ['/etc/docker/daemon.json','/usr/local/bin/docker','/etc/subuid','/etc/subgid','/etc/sysctl.conf']

def command(argv, timeout=20, **kwargs):
    return subprocess.run(argv, timeout=timeout, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs).stdout

def stamp(): return time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
def write_json(path, value):
    path=Path(path);temp=path.with_suffix(path.suffix+'.partial')
    temp.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n');temp.replace(path)

def mounts():
    for path,target,types in [(Path('/data'),'/data',('ext4','xfs')),(Path('/mnt/aliyunsb'),'/mnt/aliyunsb',('nfs','nfs4'))]:
        row=command(['findmnt','-rn','-T',str(path),'-o','TARGET,FSTYPE']).decode().split()
        if len(row)!=2 or row[0]!=target or row[1] not in types:raise RuntimeError('unexpected_mount:'+str(row))
    if DATA.resolve()!=DATA or NAS.resolve()!=NAS:raise RuntimeError('project_path_symlink_denied')

def globals_snapshot():
    return {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).is_file() else None for p in GLOBALS}

def environment():
    result={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','HOME':str(NAS/'runtime/home'),
            'TMPDIR':str(DATA/'tmp'),'XDG_CONFIG_HOME':str(NAS/'runtime/config'),
            'XDG_CACHE_HOME':str(NAS/'runtime/cache'),'DOCKER_CONFIG':str(NAS/'runtime/client'),
            'DOCKER_HOST':'unix://'+str(SOCKET)}
    proxy=NAS/'runtime/proxy.json'
    if proxy.exists():
        url=json.loads(proxy.read_text())['url']
        if url!='http://127.0.0.1:18189':raise ValueError('project_loopback_proxy_required')
        result.update(HTTP_PROXY=url,HTTPS_PROXY=url,NO_PROXY='127.0.0.1,localhost')
    return result

def prepare():
    mounts()
    for path in [DATA/'docker',DATA/'exec',DATA/'run',DATA/'tmp',NAS/'runtime/home',NAS/'runtime/client',NAS/'runtime/config',NAS/'runtime/cache',NAS/'runtime/logs',NAS/'evidence']:
        path.mkdir(parents=True,exist_ok=True)
    os.chmod(DATA/'run',0o700)
    config={'data-root':str(DATA/'docker'),'exec-root':str(DATA/'exec'),
            'pidfile':str(DATA/'run/dockerd.pid'),'hosts':['unix://'+str(SOCKET)],
            'storage-driver':'overlay2','bridge':'none','iptables':False,'ip6tables':False,
            'ip-forward':False,'ip-masq':False,'log-driver':'json-file',
            'log-opts':{'max-size':'10m','max-file':'3'},'max-concurrent-downloads':2,
            'max-concurrent-uploads':2,'live-restore':False}
    if CONFIG.exists() and json.loads(CONFIG.read_text())!=config:raise RuntimeError('existing_project_config_differs')
    if not CONFIG.exists():write_json(CONFIG,config)
    before=NAS/'runtime/global-config-before.json'
    if not before.exists():write_json(before,globals_snapshot())
    command(['/usr/bin/dockerd','--validate','--config-file',str(CONFIG)])

def info():
    mounts()
    value=json.loads(command(['/usr/bin/docker','--host','unix://'+str(SOCKET),'info','--format','{{json .}}'],env=environment()))
    if value['DockerRootDir']!=str(DATA/'docker') or value['Driver']!='overlay2':raise RuntimeError('wrong_project_daemon')
    return value

def start():
    prepare()
    pidfile=DATA/'run/dockerd.pid'
    if pidfile.exists():
        pid=int(pidfile.read_text());proc=Path('/proc')/str(pid)/'cmdline'
        if proc.exists():
            if str(CONFIG).encode() not in proc.read_bytes().split(b'\0'):raise RuntimeError('foreign_pid')
            return info()
    log=NAS/'runtime/logs'/('dockerd-'+stamp()+'.log')
    with log.open('ab',buffering=0) as stream:
        proc=subprocess.Popen(['/usr/bin/dockerd','--config-file',str(CONFIG)],
            stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,env=environment(),start_new_session=True,cwd=str(NAS))
    write_json(NAS/'runtime/launch.json',{'pid':proc.pid,'log':str(log),'config':str(CONFIG),'startedUtc':stamp()})
    deadline=time.monotonic()+35
    while time.monotonic()<deadline:
        if proc.poll() is not None:raise RuntimeError('daemon_exit:'+str(proc.returncode)+' log='+str(log))
        try:return info()
        except (subprocess.SubprocessError,FileNotFoundError,ValueError):time.sleep(.5)
    raise TimeoutError('daemon_start_deadline; inspect '+str(log))

def stop():
    pidfile=DATA/'run/dockerd.pid'
    if not pidfile.exists():return {'stopped':True}
    pid=int(pidfile.read_text());proc=Path('/proc')/str(pid)/'cmdline'
    if not proc.exists():return {'stopped':True,'stalePid':pid}
    if str(CONFIG).encode() not in proc.read_bytes().split(b'\0'):raise RuntimeError('foreign_pid')
    os.kill(pid,signal.SIGTERM)
    for unused in range(100):
        if not proc.exists() or not proc.read_bytes():return {'stopped':True,'pid':pid}
        time.sleep(.1)
    raise TimeoutError('daemon_shutdown_deadline')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','start','status','stop']);args=parser.parse_args()
    if args.action=='prepare':prepare();value={'prepared':True}
    elif args.action=='start':value=start()
    elif args.action=='stop':value=stop()
    else:value=info()
    keys=['ServerVersion','DockerRootDir','Driver','CgroupDriver','CgroupVersion','NCPU','MemTotal','stopped','prepared','pid']
    print(json.dumps({k:value[k] for k in keys if k in value},sort_keys=True))

if __name__=='__main__':main()
