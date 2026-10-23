"""Free protocol, equation, isolation and native-feedback controls before any API use."""
import concurrent.futures,json,os,pathlib,re,signal,subprocess,sys,tempfile,time,threading
import numpy as np
import sympy as sp
from common import ROOT,OUT,save,CFG
from grader import worker,fit,project
def main():
    checks=[]
    def check(name,ok,detail=None):checks.append({'name':name,'passed':bool(ok),'detail':detail})
    import hashlib,scipy,h5py,pyarrow,sys
    modules=[np,scipy,sp,h5py,pyarrow];versions={m.__name__:m.__version__ for m in modules}
    pins={'python':sys.version,'packages':versions,'sharedReadOnlyRuntime':'scicode-original-20261015 frozen dependencies','files':[{'path':m.__file__,'sha256':hashlib.sha256(pathlib.Path(m.__file__).read_bytes()).hexdigest()} for m in modules]}
    save(OUT/'runtime-pins.json',pins)
    check('scientific_dependency_versions',versions=={'numpy':'1.26.4','scipy':'1.11.4','sympy':'1.13.3','h5py':'3.12.1','pyarrow':'17.0.0'},versions)
    refs=json.loads((ROOT/'data/private/references.json').read_text());catalog=json.loads((ROOT/'data/public/catalog.json').read_text())
    def reference(r):
        try:
            text=r['expression'];changes=[]
            for name in r['variables']:
                normalized=re.sub(r'\b'+re.escape(name)+r'\(t\)',name,text)
                if normalized!=text:changes.append('state_function_notation');text=normalized
            normalized=re.sub(r'(?<![\w.])(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?_([A-Za-z]\w*)',r'coefficient_\1',text)
            if normalized!=text:changes.append('published_numeric_parameter_suffix');text=normalized
            from fit_worker import FUN
            names=set(re.findall(r'\b[A-Za-z_]\w*\b',text))-set(FUN)-{'pi','E'}
            symbols={n:sp.Symbol(n) for n in names|set(r['variables'])};e=sp.sympify(text,locals=symbols)
            e=e.xreplace({symbols[n]:sp.Symbol('x'+str(i)) for i,n in enumerate(r['variables'])})
            free=sorted([s for s in e.free_symbols if str(s) not in {'x'+str(i) for i in range(len(r['variables']))}],key=str)
            if free:changes.append('uninstantiated_parameters');e=e.xreplace({s:sp.Symbol('p'+str(i)) for i,s in enumerate(free)})
            from fit_worker import expression
            expression(str(e),len(r['variables']))
            out=worker({'data':str(ROOT/'data/public'/(r['key']+'.npz')),'expression':str(e),**({'initial':[1]*len(free)} if free else {'mode':'predict','parameters':[]}),'cpuSeconds':30 if free else 60})
            return {'id':r['id'],'publishedExpression':r['expression'],'expression':str(e),'metadataConversions':changes,'structureSupported':True,'result':out}
        except Exception as e:return {'id':r['id'],'result':{'valid':False,'passed':False,'errorType':type(e).__name__,'diagnostic':str(e)}}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:gold=list(pool.map(reference,refs))
    save(OUT/'controls/reference-training.json',gold)
    check('240_reference_structures_supported',len(gold)==240 and all(g.get('structureSupported') for g in gold),[{'id':g['id'],'result':g['result']} for g in gold if not g.get('structureSupported')])
    save(OUT/'controls/reference-metadata-audit.json',{'total':len(gold),'trainingNumericMatches':sum(bool(g['result'].get('passed')) for g in gold),'metadataConversions':sum(bool(g.get('metadataConversions')) for g in gold),'numericMismatches':[{'id':g['id'],'result':g['result']} for g in gold if not g['result'].get('passed')],'policy':'Published ground-truth strings are not used for solver scoring or SA. Original numerical arrays and all 240 tasks remain unchanged. Numeric reference fit failures remain explicit metadata/optimization warnings; required controls verify numerical scoring and supported expression structures.'})
    with tempfile.TemporaryDirectory(prefix='llmsr-free-') as td:
        p=pathlib.Path(td);p.chmod(0o755);x=np.linspace(1,3,100)[:,None];np.savez(p/'train.npz',X=x,y=2*x[:,0]+3);(p/'train.npz').chmod(0o644)
        base={'data':str(p/'train.npz'),'cpuSeconds':30}
        fitted=worker({**base,'expression':'p0*x0+p1','initial':[1,1]})
        check('shared_parameter_fitter',fitted.get('passed') and np.allclose(fitted.get('parameters'),[2,3],atol=1e-5),fitted)
        wrong=worker({**base,'expression':'0','mode':'predict'});check('wrong_constant_rejected',wrong['valid'] and not wrong['passed'])
        nan=worker({**base,'expression':'sqrt(-x0)','mode':'predict'});check('nan_cannot_shrink_denominator',nan['valid'] and not nan['passed'] and nan.get('finiteCoverage')==0)
        attack=worker({**base,'expression':'__import__("os").system("id")','mode':'predict'});check('expression_has_no_arbitrary_execution',attack['valid'] and not attack['passed'] and attack.get('errorType') in ['ForbiddenExpressionSyntax','ForbiddenFunction','UnknownSymbol'])
        secret=ROOT/'data/private/isolation-probe';secret.write_text('PRIVATE');secret.chmod(0o600)
        env={'PATH':'/usr/bin:/bin'}
        code='import os,socket,sys;os.setgroups([]);os.setgid(65534);os.setuid(65534);p=sys.argv[1];\ntry:open(p);print("LEAK")\nexcept PermissionError:print("PRIVATE_DENIED")\ns=socket.socket();print("NETWORK_DENIED" if s.connect_ex(("1.1.1.1",443))!=0 else "LEAK")'
        r=subprocess.run(['unshare','--net',str(ROOT/'runtime/bin/python'),'-c',code,str(secret)],env=env,capture_output=True,text=True,timeout=10)
        check('private_files_and_network_denied',r.returncode==0 and 'PRIVATE_DENIED' in r.stdout and 'NETWORK_DENIED' in r.stdout and 'LEAK' not in r.stdout,r.stdout)
        secret.unlink()
        full=project({'valid':True,'passed':False,'nmse':123,'finiteCoverage':1},'objrun');binary=project({'valid':True,'passed':False,'nmse':123,'finiteCoverage':1},'binary')
        check('binary_projection_only_boolean',binary=={'value':False} and '123' in full['note'])
        a=worker({**base,'expression':'2*x0+3','mode':'predict'})
        xo=np.linspace(10,20,50)[:,None];ood=worker({'X':xo.tolist(),'y':(xo[:,0]**2).tolist(),'expression':'2*x0+3','mode':'predict','cpuSeconds':30})
        check('training_pass_is_distinct_from_ood_success',a['passed'] and ood['valid'] and not ood['passed'])
        cpu=subprocess.run(['unshare','--net',str(ROOT/'runtime/bin/python'),'-c','import resource;resource.setrlimit(resource.RLIMIT_CPU,(1,2))\nwhile True:pass'],capture_output=True,timeout=10)
        check('real_cpu_limit_signal_classification',cpu.returncode==-signal.SIGXCPU,{'exitCode':cpu.returncode})
        import common
        original=common.urllib.request.urlopen;previous_balance=common.ACCOUNT_REMAINING;common.ACCOUNT_REMAINING=1.0
        invocations=[];gate=threading.Event()
        class FakeResponse:
            status=200
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self):
                invocations.append(1);gate.wait(2)
                return json.dumps({'id':'fixture-paid-response','provider':'DigitalOcean','model':CFG['model'],'usage':{'cost':.019},'choices':[{'message':{'role':'assistant','content':'{"expression":"x0"}'},'finish_reason':'stop'}]}).encode()
        common.urllib.request.urlopen=lambda *a,**k:FakeResponse()
        try:
            d=p/'baseline'/'ledger';body={'messages':[{'role':'user','content':'fixture'}]}
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                first=pool.submit(common.call,d,'sample-0',body)
                for _ in range(100):
                    if invocations:break
                    time.sleep(.01)
                blocked=False
                try:common.call(d,'sample-1',body)
                except common.TaskBudgetStop:blocked=True
                gate.set();first.result()
            common.call(d,'sample-0',body)
            check('atomic_task_reservation_and_no_paid_replay',blocked and len(invocations)==1 and common.accounting(d)['modelCalls']==1)
            orphan=p/'independent'/'orphan'/'calls'/'interrupted'/'attempt-0';common.durable(orphan/'dispatch.json',{'reservedUpperBoundUsd':.02})
            blocked=False
            try:common.call(p/'independent'/'orphan','interrupted',body)
            except common.UnknownDispatch:blocked=True
            check('unknown_dispatch_not_redispatched',blocked and len(invocations)==1 and common.accounting(p/'independent'/'orphan')['unknownCostCount']==1)
            common.AccountStop('SyntheticAccountFault');blocked=False
            try:common.call(p/'independent'/'halted','new',body)
            except common.AccountStop:blocked=True
            check('account_fault_stops_new_dispatch',blocked and len(invocations)==1)
        finally:common.urllib.request.urlopen=original;common.ACCOUNT_REMAINING=previous_balance;common.HALT.clear()
    for arm in ['objrun','binary']:
        d=OUT/'controls'/('native-'+arm+'-'+str(int(time.time()*1000)));d.mkdir(parents=True,exist_ok=True)
        q={'task':{'key':'fixture','prompt':'Synthetic control: verify BAD then submit GOOD.'},'arm':arm,'directory':str(d),'model':CFG['model'],'fixture':True}
        env={'PATH':str(ROOT/'bin')+':/usr/bin:/bin','OPENROUTER_API_KEY':'fixture-no-credential'}
        r=subprocess.run([str(ROOT/'bin/bun'),str(ROOT/'package/native.ts')],input=json.dumps(q),capture_output=True,text=True,env=env,cwd=ROOT,timeout=90)
        result=json.loads((d/'native-result.json').read_text()) if (d/'native-result.json').exists() else {}
        check('real_native_'+arm,result.get('fixturePassed'),{'result':result,'stderr':r.stderr[-1200:]})
        if result.get('fixturePassed'):
            snapshots=[]
            for cutoff in [0,int(time.time()*1000)]:
                args={'db':str(d/'engine/data/h2h.sqlite'),'taskId':'llm-srbench-240/fixture','cutoffMs':cutoff}
                p=subprocess.run([str(ROOT/'bin/bun'),str(ROOT/'package/snapshot.ts')],input=json.dumps(args),capture_output=True,text=True,env=env,timeout=20)
                snapshots.append(json.loads(p.stdout) if p.returncode==0 else {'error':p.stderr})
            check('real_cost_selector_'+arm,snapshots[0].get('answer')=='' and snapshots[1].get('answer')=='GOOD',snapshots)
    report=subprocess.run([str(ROOT/'runtime/bin/python'),str(ROOT/'package/report_control.py')],capture_output=True,text=True,timeout=180)
    check('complete_report_and_cost_curve_pipeline',report.returncode==0,{'stdout':report.stdout[-1000:],'stderr':report.stderr[-1000:]})
    summary={'allPassed':all(c['passed'] for c in checks),'checks':checks,'paidCalls':0};save(OUT/'controls/summary.json',summary)
    print(json.dumps({'allPassed':summary['allPassed'],'checks':[{'name':c['name'],'passed':c['passed'],'detail':c['detail'] if not c['passed'] else None} for c in checks],'paidCalls':0},ensure_ascii=False));return 0 if summary['allPassed'] else 1
if __name__=='__main__':raise SystemExit(main())
