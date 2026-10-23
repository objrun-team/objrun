import socket,json,psutil,datetime
from pathlib import Path
ports={17889,17895}
root=Path(__file__).resolve().parents[5];snapshot=json.loads((root/'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/broker/adoption-v46/production-first/broker/broker-status.json').read_text());previousLastSeen=datetime.datetime.fromisoformat(snapshot['atUtc'].replace('Z','+00:00')).timestamp();boot=psutil.boot_time()
if not previousLastSeen<boot:raise RuntimeError('current_boot_not_after_previous_live_executor_snapshot')
reused=None
if psutil.pid_exists(1304):
 p=psutil.Process(1304);created=p.create_time();name=p.name()
 if created<boot or name.lower().startswith('bun'):raise RuntimeError('previous_executor_pid_incarnation_unresolved_or_bun_active')
 reused=dict(pid=1304,name=name,createdAtUnix=created,originalIncarnationAbsent=True)
listeners=[c for c in psutil.net_connections(kind='tcp') if c.status==psutil.CONN_LISTEN and c.laddr and c.laddr.port in ports]
if listeners:raise RuntimeError('broker_listener_exists')
held=[]
try:
 for port in sorted(ports):
  s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);s.bind(('127.0.0.1',port));held.append(s)
 print(json.dumps(dict(previousExecutorAbsent=True,previousSnapshotAtUnix=previousLastSeen,currentBootUnix=boot,reusedPID=reused,localTCPListenersAbsent=True,exclusiveBindPassed=sorted(ports),scope='current-Windows-before-production-WX',modelCalls=0)))
finally:
 for s in held:s.close()
