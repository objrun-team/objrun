"""Candidate snapshot is used only for UNTRUSTED execution, never grading.

The host retains only bounded JSON return values. Trusted assertions always
run in the separate immutable private image. Actual integration tests pending.
"""
import hashlib
import json
import re
from pathlib import Path
import time
import uuid
from code_values import TASK,SOURCE,source_from_daemon_tar,decode_values
from prepare import public

def evaluate_snapshot(command,cid,nonce,built,missing_source=None,capture_source=None):
    assert built['taskId']==TASK
    began=time.monotonic();limit=built['originalResources']['verifier']['timeout_sec']
    def remaining():
        seconds=limit-(time.monotonic()-began)
        if seconds<=0:raise TimeoutError('original_combined_verifier_budget')
        return seconds
    inspect=json.loads(command(['inspect',cid],timeout=remaining()))[0]
    assert not inspect['State']['Running'] and inspect['Image']==built['candidateImageId']
    labels=inspect['Config']['Labels'];assert labels['objrun.skb.role']=='full-f-solver' and labels['objrun.skb.nonce']==nonce
    assert not inspect['HostConfig'].get('Binds') and not inspect['HostConfig'].get('Mounts') and not inspect['HostConfig'].get('Privileged')
    assert capture_source is not None
    storage_bytes=int(built['originalResources']['environment']['storage_mb']*1024**2)
    captured=capture_source(cid,SOURCE,storage_bytes,remaining());sha=captured['sourceSha256']
    source_present=not captured['sourceAbsent']
    runner=Path(__file__).with_name('candidate_snapshot_exec.py');runner_pin=public.pin(runner);code=runner.read_text()
    execution=None;private=None;snapshot=None;owner=uuid.uuid4().hex
    e=built['originalResources']['environment']
    common=['--pull','never','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges','--memory',str(e['memory_mb']*1024**2),'--memory-swap',str(e['memory_mb']*1024**2),'--cpus',str(e['cpus']),'--workdir',built['workingDirectory']]
    try:
        if not source_present:
            values={'protocol':'skillsbench-wyckoff-untrusted-function-values-v1','candidateSourceSha256':sha,
                'calls':[{'path':path,'inputSha256':pin,'error':'CandidateSourceMissing'} for path,pin in built['publicInputs'].items()]}
        else:
            commit_output=command(['commit','--change','LABEL objrun.skb.role=untrusted-code-snapshot','--change','LABEL objrun.skb.snapshot-owner='+owner,cid],timeout=remaining()).decode()
            identities=[line.strip() for line in commit_output.splitlines() if re.fullmatch(r'sha256:[0-9a-f]{64}',line.strip())]
            assert len(identities)==1
            snapshot=identities[0]
            assert snapshot.startswith('sha256:') and len(snapshot)==71 and all(c in '0123456789abcdef' for c in snapshot[7:]) and snapshot not in (built['candidateImageId'],built['executionImageId'],built['privateImageId'])
            execution=command(['create','-i',*common,'--label','objrun.skb.role=untrusted-code-function','--entrypoint','python3',snapshot,'-I','-B','-c',code],timeout=remaining()).decode().strip()
            assert len(execution)==64 and all(c in '0123456789abcdef' for c in execution)
            incoming={'candidateSourceSha256':sha,'publicInputs':built['publicInputs']}
            raw=command(['start','-a','-i',execution],timeout=remaining(),stdin=json.dumps(incoming).encode(),stdout_limit=2*1024**2)
            values=decode_values(raw,sha,built['publicInputs'])
        assert public.pin(runner)==runner_pin
        private=command(['create','-i','--read-only',*common,'--tmpfs','/logs/verifier:rw,nosuid,nodev,noexec,size=64m','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=64m',built['privateImageId']],timeout=remaining()).decode().strip()
        assert len(private)==64 and all(c in '0123456789abcdef' for c in private)
        p=json.loads(command(['inspect',private],timeout=remaining()))[0];h=p['HostConfig']
        assert p['Image']==built['privateImageId'] and h['ReadonlyRootfs'] and h['NetworkMode']=='none' and not h.get('Binds') and not h.get('Mounts')
        result=json.loads(command(['start','-a','-i',private],timeout=remaining(),stdin=json.dumps(values).encode()))
        assert result['taskId']==TASK and result['complete'] and not result['candidateExecutablesUsed'] and not result['candidateSnapshotUsed']
        return {'result':result,'candidateExecutionSnapshotUsed':snapshot is not None,'sourceCaptureState':'captured' if source_present else 'absent','sourceDigestReceiptPin':captured['receiptPin'],'sourceBytes':captured['sourceBytes'],'originalStorageBytes':storage_bytes,'candidateSnapshotUsedForTrustedGrader':False,'candidateInterpreterUsedForTrustedGrader':False,
            'sourceSha256':sha,'runnerSourcePin':runner_pin,'privateImageId':built['privateImageId'],'elapsedSeconds':time.monotonic()-began}
    finally:
        # Cleanup only exact identities created by this function. If cleanup
        # fails it remains an infrastructure failure; no success is returned.
        cleanup_errors=[]
        for owned in (execution,private):
            if owned:
                try:command(['rm','-f',owned])
                except Exception as error:cleanup_errors.append({'kind':'container','id':owned,'error':type(error).__name__})
        if snapshot:
            try:
                image=json.loads(command(['image','inspect',snapshot]))[0]
                assert image['Config']['Labels']['objrun.skb.snapshot-owner']==owner and image['Config']['Labels']['objrun.skb.role']=='untrusted-code-snapshot'
                command(['image','rm',snapshot])
            except Exception as error:cleanup_errors.append({'kind':'image','id':snapshot,'owner':owner,'error':type(error).__name__})
        if cleanup_errors:
            error=RuntimeError('isolated_snapshot_cleanup_incomplete');error.ownedResourcesRemaining=cleanup_errors;raise error
