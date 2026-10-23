"""Offline audit of a remote run or extracted local archive. Never invokes models."""
import argparse,hashlib,json,pathlib,sqlite3
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def audit(root):
    root=pathlib.Path(root);out=root/'outputs';issues=[];state=json.loads((out/'status.json').read_text());records=[];actual=0.0;unknown=0;ids=[]
    manifest=json.loads((root/'data/manifest.json').read_text());catalog=json.loads((root/'data/public/catalog.json').read_text());book={t['key']:t for t in catalog}
    if manifest['tasks']!=240 or len(book)!=240:issues.append('ReleaseTaskCount')
    pins=json.loads((out/'source-pins.json').read_text())
    for p in pins:
        path=root/p['path']
        if not path.exists() or sha(path)!=p['sha256']:issues.append('SourceHash:'+p['path'])
    for rp in sorted((out/'tasks').glob('*/*/result.json')):
        r=json.loads(rp.read_text());d=rp.parent;records.append(r)
        if r['publicInputSha256']!=book[r['key']]['publicSha256']:issues.append('PublicInputChanged:'+r['key'])
        cap=.025 if r['arm']=='baseline' else .1;spent=0;cellunknown=0
        for p in (d/'calls').rglob('dispatch.json'):
            q=json.loads((p.parent/'request.json').read_text());receipt=p.parent/'receipt.json';dispatch=json.loads(p.read_text())
            if q['model']!='deepseek/deepseek-v4.1-flash' or q.get('temperature')!=0 or q.get('max_tokens')!=16384 or q.get('provider',{}).get('only')!=['digitalocean'] or q.get('provider',{}).get('allow_fallbacks') is not False or q.get('reasoning',{}).get('effort')!='high' or 'seed' in q:issues.append('WireProfile:'+str(p.relative_to(root)))
            if r['arm']=='independent' and q['messages']!=[{'role':'user','content':book[r['key']]['prompt']}]:issues.append('IndependentHistory:'+r['key'])
            if receipt.exists():
                a=json.loads(receipt.read_text());usd=a.get('actualCostUsd');actual+=usd or 0;spent+=usd if usd is not None else a['reservedUpperBoundUsd'];cellunknown+=a.get('unknownCost',False)
                if a.get('generationId'):ids.append(a['generationId'])
            else:spent+=dispatch['reservedUpperBoundUsd'];cellunknown+=1
        unknown+=cellunknown
        if spent>cap+1e-7 or abs(spent-r['accountedUpperBoundUsd'])>1e-7 or cellunknown!=r['unknownCostCount']:issues.append('CellAccounting:'+r['key']+':'+r['arm'])
        if r['valid']:
            fr=json.loads((d/'candidate-freeze.json').read_text())
            if hashlib.sha256(r['answer'].encode()).hexdigest()!=fr['answerSha256'] or fr['idOodAccessed']:issues.append('FinalFreeze:'+r['key'])
        if r['arm'] in ['baseline','independent']:
            samples=json.loads((d/'samples.json').read_text()) if (d/'samples.json').exists() else []
            if len(samples)>(1 if r['arm']=='baseline' else 5):issues.append('SampleCeiling:'+r['key'])
            if any(s['grade']['passed'] for s in samples[:-1]):issues.append('EarlyStopViolation:'+r['key'])
        else:
            if not all((d/'native'/p).exists() for p in ['tree.json','trace.json','task.json','engine/data/h2h.sqlite']):issues.append('NativeEvidence:'+r['key'])
            feedback=json.loads((d/'feedback.json').read_text()) if (d/'feedback.json').exists() else []
            if len(feedback)>5:issues.append('NativeCandidateCeiling:'+r['key'])
            if len(feedback)>=5 and r.get('answer') and r['answer'] not in [x['answer'] for x in feedback]:issues.append('UnassessedSixthCandidate:'+r['key'])
            if r['arm']=='binary':
                if any(set(v['exposed'])!={'value'} for v in feedback):issues.append('BinaryFeedbackProjection:'+r['key'])
                db=d/'native/engine/data/h2h.sqlite'
                if db.exists():
                    with sqlite3.connect('file:'+db.as_posix()+'?mode=ro',uri=True) as connection:
                        for (body,) in connection.execute("select body from agent_bot_msg where kind='graded'"):
                            v=json.loads(body).get('value',{})
                            if v.get('valid') is True and 'pass' in v and (v.get('note') or v.get('why') not in ['passed','failed']):issues.append('BinaryNativeVerdictLeak:'+r['key'])
    if len(ids)!=len(set(ids)):issues.append('DuplicateGenerationIds')
    if abs(actual-state['actualCostUsd'])>1e-7 or unknown!=state['unknownCostCount']:issues.append('GlobalAccounting')
    if state['stage'] in ['complete','complete_with_exceptions']:
        if len(records)!=960 or any(sum(r['arm']==a for r in records)!=240 for a in ['baseline','objrun','independent','binary']):issues.append('CompleteMapping')
        if any(not (out/'tasks'/r['arm']/r['key']/'final-evaluation.json').exists() for r in records):issues.append('MissingFinalEvaluation')
    result={'allPassed':not issues,'stage':state['stage'],'recordCount':len(records),'actualCostUsd':actual,'unknownCostCount':unknown,'issues':issues,'arms':{a:sum(r['arm']==a for r in records) for a in ['baseline','objrun','independent','binary']}}
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default=str(pathlib.Path(__file__).resolve().parents[1]));args=p.parse_args();r=audit(args.root)
    target=pathlib.Path(args.root)/'outputs/offline-audit.json';target.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if r['allPassed'] else 1)
