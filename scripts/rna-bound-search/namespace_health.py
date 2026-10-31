"""Identify this run's Linux processes by its mounted, unique /work marker."""
import sys,json,os,time
from pathlib import Path
token=sys.argv[1];items=[]
for proc in Path('/proc').iterdir():
 if not proc.name.isdigit():continue
 try:
  surface=None
  for mount in ('work','audit'):
   try:
    if (proc/f'root/{mount}/RUN_ID').read_text().strip()==token:surface=mount;break
   except OSError:pass
  if surface is None:continue
  raw=(proc/'stat').read_text();tail=raw.rsplit(')',1)[1].split()
  items.append({'pid':int(proc.name),'surface':surface,'name':(proc/'comm').read_text().strip(),'state':tail[0],'parent_pid':int(tail[1]),'cpu_ticks':int(tail[11])+int(tail[12]),'start_ticks':int(tail[19])})
 except (OSError,ValueError,IndexError):pass
print(json.dumps({'epoch':time.time(),'clock_ticks_per_second':os.sysconf('SC_CLK_TCK'),'processes':items}))
