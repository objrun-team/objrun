"""Zero-provider controls for retry selection, clocks, isolation and native submit."""
from pathlib import Path
import sys
import sqlite3
from core import *

def main():
    root=Path(sys.argv[1]).resolve();f=root/'frozen';sys.path.insert(0,str(f/'package'))
    import runtime as rt
    import controller as c
    checks=[]
    def check(name,value):checks.append({'name':name,'passed':bool(value)})
    c.frozen(True);check('exact-original-frozen-code-data-and-dependencies',True)
    rt.CFG.pop('canaryTransportRecovery',None)
    check('no-old-time-or-wire-recovery',not rt.CFG.get('canaryTransportRecovery'))
    for label,r,expected in [('wrong',{'solverValid':True,'grade':{'valid':True,'passed':False}},True),('normal-budget-exhaustion',{'solverValid':True,'grade':{'valid':True,'parsed':False}},True),('correct-but-infrastructure',{'solverValid':False,'grade':{'valid':True,'passed':True}},False),('grader-fault',{'solverValid':True,'grade':{'valid':False}},False)]:check(label,valid(r)==expected)
    a=[{'number':1,'valid':False},{'number':2,'valid':True,'passed':False},{'number':3,'valid':True,'passed':True}]
    check('first-valid-wrong-stops-not-best',first_valid(a)['number']==2)
    check('attempt-request-namespaces-distinct',namespaced('q/objrun/native-001',1)!=namespaced('q/objrun/native-001',2))
    check('arm-accounting-position-preserved',namespaced('q/objrun/native-001',1).split('/')[1]=='objrun')
    check('degraded-longer-backoff',cooldown(2,True)>cooldown(2,False));check('backoff-bounded-at-30-minutes',cooldown(99,True)==1800)
    save(root/'control/admission.json',{'modelSlots':2})
    one,two,three=[Lease(root) for _ in range(3)]
    check('slot-one',one.acquire(.1));check('slot-two',two.acquire(.1));check('third-slot-waits',not three.acquire(.1));one.release();check('released-slot-reusable',three.acquire(.1));two.release();three.release()
    fixture=root/'controls/native-fixture';fixture.mkdir(parents=True,exist_ok=False)
    class Server:server_port=1
    result=c.native({'id':'recovery-zero-model','prompt':'Fixture; choose B.','choiceCount':5},fixture,Server(),'fixture',True)
    check('native-reject-then-real-submit',result['answer']=='[ANSWER]B[/ANSWER]' and result['candidateHow']=='submitted')
    inp=read(fixture/'input.json');check('fresh-input-no-priorSolveSeconds',not any(k in inp for k in ['priorSolveSeconds','replayFirstWire']))
    db=sqlite3.connect(fixture/'engine/data/h2h.sqlite');row=db.execute('select solve_seconds,max_branches from task').fetchone();db.close()
    check('real-native-full600-and-four-branches',row==(600,4))
    for k,v in read(fixture/'fixture-assertions.json').items():check('frozen-fixture:'+k,v)
    original=Path(read(root/'recovery.json')['originalRoot']);original_guard(original);check('original-all-files-still-frozen',True)
    save(root/'controls.json',{'allPassed':all(x['passed'] for x in checks),'modelCalls':0,'checkCount':len(checks),'checks':checks,'atUtc':now()},True)
    print(__import__('json').dumps({'allPassed':all(x['passed'] for x in checks),'modelCalls':0,'checks':len(checks)}))
    assert all(x['passed'] for x in checks)

if __name__=='__main__':main()
