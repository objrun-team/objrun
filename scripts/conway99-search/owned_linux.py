"""Read Linux process ownership by this run's unique bwrap mount argument."""
import subprocess
def inspect(run):
    path='/mnt/'+str(run)[0].lower()+str(run)[2:].replace('\\','/')
    proc=subprocess.run(['wsl','-d','Ubuntu','--','ps','-eo','pid=,ppid=,etimes=,time=,pcpu=,rss=,args='],capture_output=True,text=True,timeout=15)
    if proc.returncode:raise RuntimeError(proc.stderr)
    rows={}
    for line in proc.stdout.splitlines():
        f=line.split(None,6)
        if len(f)==7:
            rows[int(f[0])]={'pid':int(f[0]),'ppid':int(f[1]),'elapsed_seconds':int(f[2]),'cpu_time':f[3],'cpu_percent':f[4],'rss_kb':int(f[5]),'command':f[6]}
    roots={pid for pid,r in rows.items() if path+'/work' in r['command'] and 'bwrap ' in r['command']}
    owned=set(roots)
    while True:
        added={pid for pid,r in rows.items() if r['ppid'] in owned}-owned
        if not added:break
        owned.update(added)
    return {'bwrap_root_pids':sorted(roots),'processes':[rows[p] for p in sorted(owned)]}
