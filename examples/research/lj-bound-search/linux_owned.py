"""Inspect/stop only bwrap processes whose argv binds this exact run directory."""
from pathlib import Path
import os,sys,json,signal,time
run=str(Path(sys.argv[1]).resolve());stop='--stop' in sys.argv
assert run.startswith('/mnt/f/git/TgEngin-handoff-2026-10-07/objrun/data/lj-bound-search/run-')
markers={run+'/work',run+'/reference'}
def identity(pid):
    p=Path('/proc')/str(pid);cmd=p.joinpath('cmdline').read_bytes().split(b'\0')
    args=[a.decode(errors='replace') for a in cmd if a]
    stat=p.joinpath('stat').read_text();fields=stat[stat.rindex(')')+2:].split()
    return args,fields[19],int(fields[11])+int(fields[12]),int(fields[1])
anchors=[]
processes={}
for p in Path('/proc').iterdir():
    if not p.name.isdigit():continue
    try:
        args,born,cpu,parent=identity(p.name)
        processes[int(p.name)]={'pid':int(p.name),'parent':parent,'start_ticks':born,'cpu_ticks':cpu,'argv0':args[0] if args else ''}
        if args and Path(args[0]).name=='bwrap' and markers.issubset(set(args)):
            anchors.append({'pid':int(p.name),'start_ticks':born,'cpu_ticks':cpu,'namespace':os.readlink(p/'ns/pid')})
    except (FileNotFoundError,PermissionError,ProcessLookupError,ValueError):pass
actions=[]
for item in anchors:
    if stop:
        try:
            args,born,cpu,parent=identity(item['pid'])
            if born==item['start_ticks'] and markers.issubset(set(args)) and Path(args[0]).name=='bwrap':
                os.kill(item['pid'],signal.SIGKILL);actions.append(item['pid'])
        except (FileNotFoundError,ProcessLookupError,PermissionError):pass
owned={a['pid'] for a in anchors}
while True:
    more={p for p,v in processes.items() if v['parent'] in owned}-owned
    if not more:break
    owned.update(more)
print(json.dumps({'run':run,'owned_bwrap':anchors,'owned_processes':[processes[p] for p in sorted(owned)],'stopped_pids':actions,'stop_requested':stop}))
