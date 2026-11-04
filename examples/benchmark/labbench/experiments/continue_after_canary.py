"""Owned continuation; refuses inference unless a matching user approval exists."""
from pathlib import Path
import fcntl
import json
import os
import secrets
import sys
import threading
import time
import urllib.error


def main():
    root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root/'package'))
    import controller as c
    import report
    from acceptance_policy import apply_acceptance
    out=c.OUT
    approval=c.read(out/'formal-with-exceptions-approval.json')
    canary=c.read(out/'canary.json')
    apply_acceptance({'checks':[{'name':'canary20x2','passed':False}]},approval,canary)
    lock=(out/'controller.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (out/'continuation-started.json').exists():raise RuntimeError('ExistingContinuationInspectNoDuplicate')
    c.frozen(True)
    # All terminal records, including approved unknowns, are retained without dispatch.
    existing={(r['arm'],r['id']) for r in [c.read(p) for p in (out/'results').glob('*/*.json')]}
    assert len(existing)==40
    c.save(out/'continuation-started.json',{'pid':os.getpid(),'atUtc':c.now(),'retainedResults':40,'approvalSha256':c.digest(approval)},True)

    class ReadRetryRouter(c.OpenRouter):
        def get(self,path):
            for attempt in range(3):
                try:return super().get(path)
                except (urllib.error.URLError,TimeoutError) as error:
                    if isinstance(error,urllib.error.HTTPError) and error.code not in {408,429,500,502,503,504}:raise
                    if attempt==2:raise
                    time.sleep(attempt+1)

    server=None;judge=None
    try:
        c.client=ReadRetryRouter();c.client.observe();judge=c.Judge(c.book);token=secrets.token_hex(32);server=c.broker(c.client,judge,token)
        c.stage='formal';c.save(out/'formal-started.json',{'atUtc':c.now(),'retainedCanaryResults':40,'approvedCanaryExceptions':3,'approvalSha256':c.digest(approval)},True);c.status()
        threading.Thread(target=c.heartbeat,daemon=True).start()
        jobs=[(r,a) for n,r in enumerate(c.public) for a in c.CFG['arms'][n%2:]+c.CFG['arms'][:n%2] if (a,r['id']) not in existing]
        c.run_jobs(jobs,judge,server,token)
        if c.fatal or c.client.stop:raise c.Fault(c.fatal or c.client.stop)
        c.stage='finalizing';c.status()
    except Exception as error:
        c.fatal=type(error).__name__+':'+str(error);c.stage='needs_attention'
    finally:
        if server:server.shutdown()
        if judge:judge.pool.shutdown(wait=True)
        c.status()
    if c.stage=='finalizing':
        original_audit=report.audit
        def approved_audit():
            raw=original_audit();c.save(out/'AUDIT_WITHOUT_GATE_EXCEPTION.json',raw)
            return apply_acceptance(raw,approval,canary)
        report.audit=approved_audit
        try:
            report.main();checked=c.read(out/'AUDIT.json');rows=[c.read(p) for p in (out/'results').glob('*/*.json')]
            c.stage=('complete' if all(r['solverValid'] and r['grade'].get('valid') for r in rows) else 'complete_with_exceptions') if checked['allPassed'] else 'needs_attention'
            c.save(out/'final-freeze.json',{'atUtc':c.now(),'count':len(rows),'auditPassed':checked['allPassed'],'canaryAcceptedWithExceptions':True},True)
        except Exception as error:c.fatal=type(error).__name__+':'+str(error);c.stage='needs_attention'
        c.status()


if __name__=='__main__':main()
