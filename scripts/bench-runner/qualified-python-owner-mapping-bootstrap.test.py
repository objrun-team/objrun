import json,hashlib,tempfile,subprocess,pathlib,sys
root=pathlib.Path(tempfile.mkdtemp(prefix='mapping-local-'))
def pin(p):
 b=p.read_bytes();return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
g=root/'guard.py';g.write_text("def require_activation():return {'dockerHost':'tcp://local-fixture'}\ndef require_lease(*args):return None\ndef load_control():return {'actual':True}\ndef guard():return 'owned'\n")
m=root/'oldgate.py';m.write_text("def activation_control():raise RuntimeError('old owner used')\ndef require_native_lease():raise RuntimeError('old lease used')\n")
s=root/'entry.py';s.write_text("from oldgate import activation_control,require_native_lease\nassert activation_control()=={'actual':True}\nassert require_native_lease()=='owned'\nprint('aliases_real_import_pass')\n")
c={'protocol':'bench-qualified-python-source-mapping-v1','originalStandPin':pin(s),'guardPin':pin(g),'resource':{'memoryMb':4096,'growthBytes':21474836480,'bench':'terminal-bench'},'modules':[{'name':'oldgate','pin':pin(m),'guardAliases':{'activation_control':'actual-adopted-control','require_native_lease':'actual-owned-lease'}}]}
cp=root/'config.json';cp.write_text(json.dumps(c));import os
env=dict(os.environ,DOCKER_HOST='tcp://local-fixture');bootstrap='scripts/bench-runner/qualified-python-owner-mapping-bootstrap.py'
r=subprocess.run([sys.executable,bootstrap,'--config',str(cp),'--original-script',str(s)],env=env,capture_output=True,text=True);assert r.returncode==0,(r.stdout,r.stderr)
c['modules'][0]['guardAliases']['activation_control']='unsupported';cp.write_text(json.dumps(c));r2=subprocess.run([sys.executable,bootstrap,'--config',str(cp),'--original-script',str(s)],env=env,capture_output=True,text=True);assert r2.returncode!=0 and 'guard_alias_unsupported' in r2.stderr
print(json.dumps({'positiveExit':r.returncode,'negativeExit':r2.returncode,'resources':0,'models':0,'nativeActors':0,'actualImportAliasPositive':True,'unsupportedRejected':True}))
