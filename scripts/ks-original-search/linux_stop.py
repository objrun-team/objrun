"""Stop ONLY bubblewrap namespaces with the exact run-owned workspace mount."""
import os,signal,sys,time,json
from pathlib import Path
target=sys.argv[1];actions=[]
def owned():
    found=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            if (p/'comm').read_text().strip()!='bwrap':continue
            args=(p/'cmdline').read_bytes().split(b'\0')
            if target.encode() not in args:continue
            text=(p/'stat').read_text();stamp=text[text.rindex(')')+2:].split()[19]
            found.append((int(p.name),stamp))
        except (OSError,IndexError):pass
    return found
for sig in [signal.SIGTERM,signal.SIGKILL]:
    for pid,stamp in owned():
        try:
            text=Path(f'/proc/{pid}/stat').read_text()
            if text[text.rindex(')')+2:].split()[19]!=stamp:continue
            os.kill(pid,sig);actions.append({'pid':pid,'start_ticks':stamp,'signal':int(sig)})
        except (OSError,IndexError):pass
    time.sleep(.15)
print(json.dumps({'workspace':target,'actions':actions,'remaining_namespaces':owned()}))
