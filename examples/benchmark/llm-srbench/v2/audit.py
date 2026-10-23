"""Strict v2-only audit; explicitly separate infrastructure exceptions from violations."""
import argparse,hashlib,json,pathlib,sqlite3
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def audit(root,require_complete=False):
    root=pathlib.Path(root);out=root/'outputs';plan=json.loads((root/'package/continuation-plan.json').read_text());issues=[];exceptions=[];rows=[];ids=[]
    allowed={(e['arm'],e['key']) for e in plan['allowedCells']};book={t['key']:t for t in json.loads((root/'data/public/catalog.json').read_text())}
    for p in json.loads((out/'source-pins.json').read_text()):
        if not (root/p['path']).is_file() or sha(root/p['path'])!=p['sha256']:issues.append('SourceHash:'+p['path'])
    for d in (out/'tasks').glob('*/*'):
        pair=(d.parent.name,d.name)
        if pair not in allowed:issues.append('OutsideAllowlist:'+str(pair))
        rp=d/'result.json';r=json.loads(rp.read_text()) if rp.exists() else None
        if r:rows.append(r)
        spent=actual=0;unknown=calls=0
        for dispatch in (d/'calls').rglob('dispatch.json'):
            v=json.loads(dispatch.read_text());q=json.loads((dispatch.parent/'request.json').read_text());receipt=dispatch.parent/'receipt.json';calls+=1
            if q['model']!='deepseek/deepseek-v4.1-flash' or q.get('temperature')!=0 or q.get('max_tokens')!=16384 or q.get('provider',{}).get('only')!=['digitalocean'] or q.get('provider',{}).get('allow_fallbacks') is not False or q.get('reasoning',{}).get('effort')!='high' or 'seed' in q:issues.append('WireProfile:'+str(pair))
            if pair[0]=='independent' and q['messages']!=[{'role':'user','content':book[pair[1]]['prompt']}]:issues.append('IndependentHistory:'+str(pair))
            if r and v['dispatchAtMs']>r['completedAtMs']:issues.append('DispatchAfterResult:'+str(pair))
            a=json.loads(receipt.read_text()) if receipt.exists() else {};usd=a.get('actualCostUsd');actual+=usd or 0;spent+=usd if usd is not None else v['reservedUpperBoundUsd'];unknown+=bool(a.get('unknownCost',not receipt.exists()))
            if a.get('generationId'):ids.append(a['generationId'])
        if spent>(.025 if pair[0]=='baseline' else .1)+1e-7:issues.append('CellDollarCap:'+str(pair))
        if not r:
            if require_complete:issues.append('IncompleteCell:'+str(pair))
            continue
        if r.get('protocolVersion')!='v2' or r['publicInputSha256']!=book[pair[1]]['publicSha256']:issues.append('Identity:'+str(pair))
        if any(abs(v-r[k])>1e-7 for k,v in [('actualCostUsd',actual),('accountedUpperBoundUsd',spent),('unknownCostCount',unknown),('modelCalls',calls)]):issues.append('CellAccounting:'+str(pair))
        if unknown:issues.append('TerminatedUnknownPaidRequest:'+str(pair))
        if not r['valid']:exceptions.append({'arm':pair[0],'key':pair[1],'error':r.get('error')})
        else:
            f=json.loads((d/'candidate-freeze.json').read_text())
            if f['idOodAccessed'] or f['answerSha256']!=hashlib.sha256(r['answer'].encode()).hexdigest():issues.append('CandidateFreeze:'+str(pair))
        if pair[0] in ['baseline','independent']:
            samples=json.loads((d/'samples.json').read_text()) if (d/'samples.json').exists() else []
            if len(samples)>(1 if pair[0]=='baseline' else 5) or any(s['grade']['passed'] for s in samples[:-1]):issues.append('CandidateCeilingOrEarlyStop:'+str(pair))
        else:
            if r['valid'] and not r.get('providerRequestsSettledBeforeFinancialSnapshot'):issues.append('GatewayUnsettled:'+str(pair))
            feedback=json.loads((d/'feedback.json').read_text()) if (d/'feedback.json').exists() else []
            if len(feedback)>5:issues.append('NativeCandidateCeiling:'+str(pair))
            if len(feedback)>=5 and r['answer'] and r['answer'] not in [e['answer'] for e in feedback]:issues.append('UnassessedSixthCandidate:'+str(pair))
            missing=[n for n in ['trace.json','tree.json','task.json','engine/data/h2h.sqlite'] if not (d/'native'/n).exists()]
            if missing and r['valid']:issues.append('NativeEvidence:'+str(pair))
            if pair[0]=='binary':
                if any(set(e['exposed'])!={'value'} for e in feedback):issues.append('BinaryFeedbackLeak:'+str(pair))
                db=d/'native/engine/data/h2h.sqlite'
                if db.exists():
                    with sqlite3.connect('file:'+db.as_posix()+'?mode=ro',uri=True) as c:
                        table=c.execute("select 1 from sqlite_master where type='table' and name='agent_bot_msg'").fetchone()
                        if not table and r['valid']:issues.append('BinaryMessageTableMissing:'+str(pair))
                        if table:
                            for (body,) in c.execute("select body from agent_bot_msg where kind='graded'"):
                                v=json.loads(body).get('value',{})
                                if v.get('valid') is True and 'pass' in v and (v.get('note') or v.get('why') not in ['passed','failed']):issues.append('BinaryNativeLeak:'+str(pair))
    if len(ids)!=len(set(ids)):issues.append('DuplicateGenerationIds')
    if require_complete and ({(r['arm'],r['key']) for r in rows}!=allowed or len(rows)!=483):issues.append('CompleteContinuationMapping')
    if (out/'all-candidates-frozen.json').exists():
        f=json.loads((out/'all-candidates-frozen.json').read_text())
        if f['count']!=483 or len(f['records'])!=483:issues.append('GlobalFreeze')
    return {'allPassed':not issues,'protocolVersion':'v2','expectedRecords':483,'recordCount':len(rows),'issues':issues,'infrastructureExceptions':exceptions,'inheritedV1AuditPassed':False}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default=str(pathlib.Path(__file__).resolve().parents[1]));p.add_argument('--require-complete',action='store_true');a=p.parse_args();v=audit(a.root,a.require_complete)
    (pathlib.Path(a.root)/'outputs/offline-audit.json').write_text(json.dumps(v,indent=2)+'\n',encoding='utf8');print(json.dumps(v));raise SystemExit(0 if v['allPassed'] else 1)
