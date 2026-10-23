import psutil,socket,json
assert not psutil.pid_exists(15548),'old_executor_not_absent'
listeners=[dict(pid=c.pid,port=c.laddr.port) for c in psutil.net_connections(kind='tcp') if c.status==psutil.CONN_LISTEN and c.laddr.port in (17889,17895)]
assert not listeners,'actual_old_ports_still_listening'
rows=[]
for port in (17889,17895):
 s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);s.bind(('127.0.0.1',port));rows.append(port);s.close()
print(json.dumps(dict(exclusiveBindPassed=rows,oldExecutorAbsent=True,localListenersAbsent=True)))
