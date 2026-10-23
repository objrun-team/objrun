"""Exact old executor identity and original ports; read-only, never terminates processes."""
import json,sys,socket,pathlib
from processes import incarnation
import psutil
plan=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf8'))['plan']
try:
 current=incarnation(plan['previousExecutorPid'])
except OSError:
 current=None
assert current!=plan['previousExecutorIncarnation'],'original_financial_executor_still_alive'
for port in [plan['primaryPort'],*plan['aliasPorts']]:
 with socket.socket() as probe:
  probe.bind(('127.0.0.1',port))
print(json.dumps(dict(protocol='bench-exact-old-financial-executor-gone-v1',pid=plan['previousExecutorPid'],originalIncarnation=plan['previousExecutorIncarnation'],currentIncarnation=current,originalGone=True,originalPortsFree=True,processesTerminated=0)))
