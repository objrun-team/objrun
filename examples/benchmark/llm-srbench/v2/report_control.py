"""Exercise the production final reporter on a tiny, explicitly synthetic 960-cell ledger."""
import hashlib,json,pathlib,shutil,subprocess,tempfile
import numpy as np
from common import ROOT,OUT,digest,save
def main():
    with tempfile.TemporaryDirectory(prefix='llmsr-report-control-') as td:
        r=pathlib.Path(td);r.chmod(0o755);p=r/'package';p.mkdir();(r/'runtime').symlink_to(ROOT/'runtime',target_is_directory=True)
        for name in ['common.py','fit_worker.py','grader.py','report.py','experiment.json']:shutil.copy2(ROOT/'package'/name,p/name)
        pub=r/'data/public';private=r/'data/private';pub.mkdir(parents=True);private.mkdir();out=r/'outputs';out.mkdir();freezes=[]
        x=np.linspace(1,3,40)[:,None];key='0'*24
        np.savez(pub/(key+'.npz'),X=x,y=2*x[:,0]+3);(pub/(key+'.npz')).chmod(0o644)
        np.savez(private/(key+'-id.npz'),X=x,y=2*x[:,0]+3);np.savez(private/(key+'-ood.npz'),X=x*4,y=2*x[:,0]*4+3)
        answer='{"expression":"2*x0+3"}'
        for arm in ['baseline','objrun','independent','binary']:
            for i in range(240):
                k=f'{i:024x}';d=out/'tasks'/arm/k;d.mkdir(parents=True);valid=i==0;a=answer if valid else ''
                record={'id':'synthetic'+str(i),'key':k,'arm':arm,'subset':'lsr_synth_bio_pop_growth' if i<129 else 'lsr_transform','valid':valid,'answer':a,'finalCandidateSha256':digest(a) if valid else None,'actualCostUsd':0,'unknownCostCount':0,'modelCalls':0,'error':None if valid else 'SyntheticInfrastructureException'}
                points={str(b):{'answer':a,'answerSha256':digest(a),'solverValid':valid} for b in [.025,.05,.1]}
                (d/'result.json').write_text(json.dumps(record));(d/'cost-checkpoints.json').write_text(json.dumps(points));freezes.append({'arm':arm,'key':k,'sha256':record['finalCandidateSha256'],'costCheckpointsSha256':digest(points),'valid':valid})
        (out/'all-candidates-frozen.json').write_text(json.dumps({'count':960,'records':freezes}))
        q=subprocess.run([str(ROOT/'runtime/bin/python'),str(p/'report.py')],capture_output=True,text=True,timeout=180,env={'PATH':str(ROOT/'runtime/bin')+':/usr/bin:/bin','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'})
        if q.returncode:raise RuntimeError(q.stderr[-2500:])
        s=json.loads((out/'summary.json').read_text());a=s['arms']['objrun']['subsets']['all']
        assert a['total']==240 and a['solverValid']==1 and a['id']['success']==1 and a['ood']['success']==1 and a['ood']['total']==129
        assert s['costCurves']['objrun'][0]['idSuccess']==1
        first=json.loads((out/'tasks/objrun'/key/'final-evaluation.json').read_text());assert first['problemId']=='synthetic0' and first['id']['passed'] is True
        assert (out/'results.csv').exists() and (out/'REPORT.md').exists()
        proof={'allPassed':True,'syntheticRecords':960,'paidCalls':0,'solverExceptionsPreserved':956,'idOodAndCostCurvesChecked':True,'reportCodeSha256':hashlib.sha256((ROOT/'package/report.py').read_bytes()).hexdigest()}
        save(OUT/'controls/report-control.json',proof);print(json.dumps(proof))
if __name__=='__main__':main()
