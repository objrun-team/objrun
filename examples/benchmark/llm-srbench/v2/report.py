"""Final evaluation after the immutable global candidate freeze; no model calls."""
import concurrent.futures,csv,hashlib,json,pathlib,statistics
import numpy as np
from common import ROOT,OUT,save,accounting,digest
from grader import worker,fit
def evaluate_answer(key,answer):
    f=fit(key,answer);result={'training':f}
    for split in ['id','ood']:
        path=ROOT/'data/private'/(key+'-'+split+'.npz')
        if not path.exists():result[split]=None;continue
        cache=OUT/'evaluation-cache'/digest({'key':key,'split':split,'expression':f.get('expression'),'parameters':f.get('parameters'),'data':hashlib.sha256(path.read_bytes()).hexdigest()})
        if cache.exists():result[split]=json.loads(cache.read_text());continue
        if f.get('expression') and 'parameters' in f:
            with np.load(path,allow_pickle=False) as a:q={'expression':f['expression'],'parameters':f['parameters'],'mode':'predict','X':a['X'].tolist(),'y':a['y'].tolist(),'cpuSeconds':60}
            result[split]=worker(q)
        else:result[split]={'valid':True,'passed':False,'acc01':False,'nmse':None,'errorType':f.get('errorType','InvalidFinalFormula')}
        if result[split].get('valid'):save(cache,result[split])
    return result
def main():
    freeze=json.loads((OUT/'all-candidates-frozen.json').read_text());assert freeze['count']==len(freeze['records'])==960
    assert len({(e['arm'],e['key']) for e in freeze['records']})==960
    def score_entry(entry):
        d=OUT/'tasks'/entry['arm']/entry['key'];r=json.loads((d/'result.json').read_text());answer=r.get('answer','');ledger=accounting(d)
        assert r.get('finalCandidateSha256')==entry['sha256'] if r['valid'] else True
        result={'problemId':r['id'],'key':r['key'],'arm':r['arm'],'subset':r['subset'],'solverValid':r['valid'],'actualCostUsd':ledger['actualCostUsd'],'unknownCostCount':ledger['unknownCostCount'],'modelCalls':ledger['modelCalls'],'protocolVersion':r.get('protocolVersion','v1'),'rawRecordedCostUsd':r['actualCostUsd'],'recordType':r.get('recordType','completed')}
        if r['valid']:
            assert hashlib.sha256(answer.encode()).hexdigest()==entry['sha256']
            result.update(evaluate_answer(entry['key'],answer))
        else:result['error']=r.get('error')
        points=json.loads((d/'cost-checkpoints.json').read_text());assert digest(points)==entry['costCheckpointsSha256'];curve={}
        for budget,p in points.items():
            assert digest(p['answer'])==p['answerSha256']
            curve[budget]={'solverValid':p['solverValid'],**(evaluate_answer(entry['key'],p['answer']) if p['solverValid'] else {})}
        save(d/'cost-checkpoint-evaluations.json',curve);save(d/'final-evaluation.json',result);return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(score_entry,freeze['records']))
    summary={'tasksPerArm':240,'oodTasksPerArm':129,'candidateFreezeSha256':hashlib.sha256((OUT/'all-candidates-frozen.json').read_bytes()).hexdigest(),'arms':{},'accounting':accounting(OUT/'tasks'),'symbolicAccuracy':'not evaluated; numerical fidelity is not SA'}
    for arm in ['baseline','objrun','independent','binary']:
        selected=[r for r in rows if r['arm']==arm];groups={}
        for subset in ['all','lsr_transform','lsr_synth_bio_pop_growth','lsr_synth_chem_react','lsr_synth_matsci','lsr_synth_phys_osc']:
            rr=[r for r in selected if subset=='all' or r['subset']==subset];g={'total':len(rr),'solverValid':sum(r['solverValid'] for r in rr)}
            for split in ['id','ood']:
                scored=[r[split] for r in rr if isinstance(r.get(split),dict) and r[split].get('valid')]
                denom=sum(r['subset']!='lsr_transform' for r in rr) if split=='ood' else len(rr)
                finite=[s['nmse'] for s in scored if s.get('nmse') is not None]
                success=sum(s.get('passed',False) for s in scored);g[split]={'total':denom,'valid':len(scored),'success':success,'acc01Success':sum(s.get('acc01',False) for s in scored),'lowerBoundSuccessRate':success/denom if denom else None,'upperBoundSuccessRate':(success+denom-len(scored))/denom if denom else None,'finiteNmseMedian':statistics.median(finite) if finite else None,'nonFiniteOrInvalidNmse':len(scored)-len(finite)}
            groups[subset]=g
        diversities=[];lengths=0;empty_length=0
        for r in selected:
            d=OUT/'tasks'/arm/r['key'];sample=d/('samples.json' if arm in ['baseline','independent'] else 'feedback.json');events=json.loads(sample.read_text()) if sample.exists() else []
            hashes=[e['candidateSha256'] for e in events]
            diversities.append({'problemId':r['problemId'],'observedCandidates':len(hashes),'uniqueRawCandidates':len(set(hashes)),'duplicateRate':1-len(set(hashes))/len(hashes) if hashes else None})
            for p in (d/'calls').rglob('receipt.json'):
                receipt=json.loads(p.read_text())
                if receipt.get('finishReason')=='length':
                    lengths+=1;response=p.parent/'response.raw.txt'
                    if response.exists():
                        value=json.loads(response.read_text());message=value.get('choices',[{}])[0].get('message',{})
                        empty_length+=not bool(message.get('content') or message.get('tool_calls'))
        summary['arms'][arm]={'subsets':groups,'actualCostUsd':sum(r['actualCostUsd'] for r in selected),'unknownCostCount':sum(r['unknownCostCount'] for r in selected),'candidateDiversity':diversities,'lengthTruncations':lengths,'lengthWithoutDeliverable':empty_length}
    # Cluster paired intervals: all transforms of the same Feynman source stay together.
    by={(r['problemId'],r['arm']):r for r in rows};ids=sorted({r['problemId'] for r in rows});rng=np.random.default_rng(20261019);summary['pairedComparisons']={}
    for other in ['binary','independent','baseline']:
        for split in ['id','ood']:
            pairs=[]
            for tid in ids:
                a=by[tid,'objrun'];b=by[tid,other]
                if a.get(split,{} ) is None or b.get(split,{}) is None:continue
                av=a.get(split,{});bv=b.get(split,{})
                if av.get('valid') and bv.get('valid'):
                    family=tid.rsplit('_',2)[0] if a['subset']=='lsr_transform' else tid
                    pairs.append((family,int(av.get('passed',False))-int(bv.get('passed',False))))
            families=sorted({x[0] for x in pairs});clusters={f:[v for k,v in pairs if k==f] for f in families};boot=[]
            if families:
                for _ in range(2000):
                    v=[x for f in rng.choice(families,len(families),replace=True) for x in clusters[f]];boot.append(float(np.mean(v)))
            summary['pairedComparisons'][other+'_'+split]={'pairedTasks':len(pairs),'clusters':len(families),'difference':float(np.mean([v for _,v in pairs])) if pairs else None,'ci95':np.quantile(boot,[.025,.975]).tolist() if boot else None,'synthFamilyDependence':'task-level resampling; original generation families not available'}
    summary['costCurves']={}
    for arm in ['baseline','objrun','independent','binary']:
        cells=[r for r in rows if r['arm']==arm];curve=[]
        for budget in ['0.025','0.05','0.1']:
            evals=[json.loads((OUT/'tasks'/arm/r['key']/'cost-checkpoint-evaluations.json').read_text())[budget] for r in cells]
            curve.append({'budgetUsd':float(budget),'idSuccess':sum(bool(e.get('id',{}).get('passed')) for e in evals),'oodSuccess':sum(bool((e.get('ood') or {}).get('passed')) for e in evals),'idDenominator':240,'oodDenominator':129})
        summary['costCurves'][arm]=curve
    save(OUT/'summary.json',summary)
    summary['protocolVersions']={v:{'records':sum(r['protocolVersion']==v for r in rows),'completedSolverRecords':sum(r['protocolVersion']==v and r['recordType']=='completed' for r in rows),'solverValid':sum(r['protocolVersion']==v and r['solverValid'] for r in rows),'actualCostUsd':sum(r['actualCostUsd'] for r in rows if r['protocolVersion']==v),'idSuccess':sum(bool((r.get('id') or {}).get('passed')) for r in rows if r['protocolVersion']==v),'oodSuccess':sum(bool((r.get('ood') or {}).get('passed')) for r in rows if r['protocolVersion']==v)} for v in sorted({r['protocolVersion'] for r in rows})}
    summary['inheritedV1IntegrityFailure']=True
    save(OUT/'summary.json',summary)
    with (OUT/'results.csv').open('w',newline='',encoding='utf8') as f:
        fields=['protocolVersion','recordType','id','arm','subset','solverValid','idPassed','oodPassed','idNmse','oodNmse','actualCostUsd','unknownCostCount'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in rows:w.writerow({'protocolVersion':r['protocolVersion'],'recordType':r['recordType'],'id':r['problemId'],**{k:r[k] for k in ['arm','subset','solverValid','actualCostUsd','unknownCostCount']},'idPassed':(r.get('id') or {}).get('passed'),'oodPassed':(r.get('ood') or {}).get('passed'),'idNmse':(r.get('id') or {}).get('nmse'),'oodNmse':(r.get('ood') or {}).get('nmse')})
    lines=['# LLM-SRBench release: 240-task results','', 'Four arms, 960 mappings: v1 completed 475, v2 completed 483, and v1 interrupted 2. Preserve the v1 integrity-audit failure; costs use the complete journal. ID/OOD grading follows freezing of all candidates; numerical metrics are not SA.','', '|Arm|Valid solving records|ID passes|OOD passes|Actual USD|Unknown-cost records|','|---|---:|---:|---:|---:|---:|']
    for arm,a in summary['arms'].items():
        g=a['subsets']['all'];lines.append(f"|{arm}|{g['solverValid']}/240|{g['id']['success']}/240|{g['ood']['success']}/129|{a['actualCostUsd']:.6f}|{a['unknownCostCount']}|")
    lines+=['','Infrastructure anomalies are listed separately. See summary.json for success-rate bounds, commonly valid paired intervals, and subset data. Complete candidates, parameters, fitting records, cost receipts, and ObjRun trajectories remain in tasks/.']
    if (OUT/'controls/reference-metadata-audit.json').exists():
        metadata=json.loads((OUT/'controls/reference-metadata-audit.json').read_text());summary['referenceMetadataAudit']=metadata
        lines+=['','State-function notation, uninstantiated parameters, and anomalous numerical parameter names in release reference strings were audited separately. Grading always uses original numerical arrays, without modifying the task list or test labels or calling numerical scores SA.']
        save(OUT/'summary.json',summary)
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf8');print(json.dumps({'records':len(rows),'cost':summary['accounting']}))
if __name__=='__main__':main()
