"""Read Linux process ancestry for only this run; never emit command lines."""
import os,sys,json,time
from pathlib import Path
target=sys.argv[1];data={};roots=[];hz=os.sysconf(os.sysconf_names['SC_CLK_TCK'])
for entry in Path('/proc').iterdir():
    if not entry.name.isdigit():continue
    try:
        raw=(entry/'stat').read_text();name=raw[raw.index('(')+1:raw.rindex(')')];fields=raw[raw.rindex(')')+2:].split();pid=int(entry.name)
        cmd=(entry/'cmdline').read_bytes().split(b'\0')
        data[pid]={'pid':pid,'ppid':int(fields[1]),'name':name,'cpu_seconds':(int(fields[11])+int(fields[12]))/hz,'start_ticks':int(fields[19])}
        if name=='bwrap' and any(c.decode(errors='replace')==target for c in cmd):roots.append(pid)
    except (OSError,ValueError,IndexError):pass
owned=set(roots)
while True:
    more={p for p,d in data.items() if d['ppid'] in owned}-owned
    if not more:break
    owned|=more
print(json.dumps({'timestamp_epoch':time.time(),'roots':roots,'processes':[data[p] for p in sorted(owned)],'total_cpu_seconds':sum(data[p]['cpu_seconds'] for p in owned)}))
