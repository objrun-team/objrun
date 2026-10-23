"""Independent no-Bench actual adopted guard process observation fixture."""
import argparse,concurrent.futures,json,pathlib,subprocess,os,time
from native_process import pin
from adopted_guard_capture import contract,run_guard_bridge
from docker_owned import OwnedDocker
import _bench_original_owned_guard as guard

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);a=parser.parse_args();out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=False)
    assert callable(globals().get('_bench_authorized_history')) and _bench_authorized_history('zero-model-owned-sb-asset') is True
    c=contract();argv=[c['bunPin']['path'],'--smol',c['bridgePin']['path'],c['allowedActivationPaths'][0]]
    kwargs=dict(cwd=pathlib.Path(c['root']),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    def call():
        row=run_guard_bridge(argv,**kwargs);assert row.returncode==0;value=json.loads(row.stdout);assert value['healthy'] and value['secretsPrinted'] is False;return dict(exitCode=row.returncode,healthy=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:positive=list(pool.map(lambda _:call(),range(4)))
    negative=run_guard_bridge([*argv[:3],c['allowedActivationPaths'][1]],**kwargs);assert negative.returncode!=0 and b'canonical_adopted_activation_path_required' in negative.stderr
    # The original guard still rejects a noncanonical supplied path before any
    # new spawn; its fixed canonical bridge decision remains unchanged.
    old=os.environ['NOVAEVE_ACTIVATION_PATH'];os.environ['NOVAEVE_ACTIVATION_PATH']=c['allowedActivationPaths'][1]
    try:
        try:guard.verify_activation();raise AssertionError('original_path_guard_not_enforced')
        except RuntimeError as error:assert str(error)=='explicit_adopted_path_required'
    finally:os.environ['NOVAEVE_ACTIVATION_PATH']=old
    guard.guard();native=OwnedDocker(out/'native');cid=None
    try:
        cid,initial,create=native.create('neutral-actual-adopted-guard','sha256:69f919497cada9a8611f3de61df902d9f94bf20f84552ef5bd93125c38608ef9','/bin/sh',['-c','printf neutral-guard-observed'],network='none',memory_mb=2048,cpus=1)
        started=native.start(cid,attach=True,timeout=30);assert native.text(started)=='neutral-guard-observed';final=native.assert_actor(cid);assert final['State']['Status']=='exited' and final['State']['ExitCode']==0
        removal,absence=native.remove(cid);cid=None
    finally:
        for actor,role,name in native.open_actors():native.remove(actor)
        native.close()
    receipts=[]
    for p in sorted(pathlib.Path(c['directory']).glob('*.json')):
        if p.name.endswith('.spawn.json'):continue
        x=json.loads(p.read_bytes());assert x['closeObserved'] and not x['timedOut'] and x['error'] is None and x['pid'] and x['incarnation'];assert pin(x['stdoutPin']['path'])==x['stdoutPin'] and pin(x['stderrPin']['path'])==x['stderrPin'];receipts.append(pin(p))
    assert len(receipts)>=5 and any(json.loads(pathlib.Path(p['path']).read_bytes())['exitCode']!=0 for p in receipts)
    result=dict(complete=True,actualGuardDecisionUnchanged=True,actualConcurrentHealthyBridgeReads=positive,actualFailedBridgeExit=negative.returncode,actualFailedBridgeRawPreserved=True,actualOriginalNoncanonicalGuardRejected=True,actualOwnedActorRemoved=True,guardReceiptPins=receipts,initial=initial,create=create,start=started,final=final,removal=removal,absence=absence,modelCalls=0,gradeCalls=0,referenceCalls=0,feeAllocationUsd=0,noBenchContent=True,pastFailureRootCauseClaimed=False)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':main()
