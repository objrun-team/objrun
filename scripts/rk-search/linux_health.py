"""Read only /proc health of bwrap trees containing this exact run path."""
import os,json,sys
from pathlib import Path
needle=sys.argv[1];rows={};roots=[];ticks=os.sysconf(os.sysconf_names['SC_CLK_TCK'])
for p in Path('/proc').glob('[0-9]*'):
    try:
        cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
        stat=(p/'stat').read_text();end=stat.rfind(')');name=stat[stat.find('(')+1:end];v=stat[end+2:].split()
        rows[int(p.name)]={'pid':int(p.name),'ppid':int(v[1]),'name':name,'state':v[0],'cpu_seconds':(int(v[11])+int(v[12]))/ticks,'rss_bytes':int(v[21])*os.sysconf('SC_PAGE_SIZE')}
        if needle in cmd and name=='bwrap':roots.append(int(p.name))
    except (OSError,ValueError,IndexError):pass
owned=set(roots)
while True:
    more={pid for pid,r in rows.items() if r['ppid'] in owned}
    if more<=owned:break
    owned.update(more)
print(json.dumps({'root_pids':roots,'processes':[rows[p] for p in sorted(owned)],'cpu_seconds':sum(rows[p]['cpu_seconds'] for p in owned),'rss_bytes':sum(rows[p]['rss_bytes'] for p in owned)}))
