import json
import subprocess
import sys
import time
from pathlib import Path
import psutil

base=Path(__file__).resolve().parents[3]/'data/rk-search/preparation/guard-test'
base.mkdir(exist_ok=True)
processes=[subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],creationflags=0x08000000) for _ in range(2)]
deadline=time.time()+2
(base/'deadline.json').write_text(json.dumps({'deadline_epoch':deadline}))
(base/'process.json').write_text(json.dumps({k:{'pid':p.pid,'created':psutil.Process(p.pid).create_time()} for k,p in zip(('runner','engine'),processes)}))
guard=subprocess.run([sys.executable,str(Path(__file__).with_name('guard.py')),str(base)],timeout=10)
for p in processes:p.wait(timeout=3)
assert all(p.returncode is not None for p in processes) and guard.returncode==0
print(json.dumps({'guard_test_passed':True,'deadline':deadline,'receipt':json.loads((base/'deadline-guard.json').read_text())}))
