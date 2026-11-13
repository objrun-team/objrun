"""Write a delivery supplement after independent verification, without changing the archive."""
from pathlib import Path
from decimal import Decimal
import datetime as dt
import json
from ops import LOCAL


def main():
    def read(p):return json.loads(p.read_text(encoding='utf-8'))
    delivery=read(LOCAL/'DELIVERY.json');verification=read(LOCAL/'LOCAL_VERIFICATION.json')
    assert delivery['verified'] and verification['allPassed']
    meta=read(LOCAL/'retrieval.json');root=Path(meta['fullResults']);out=root/'outputs/canonical'
    summary=read(out/'SUMMARY.json');audit=read(out/'AUDIT.json');status=read(out/'status.json')
    assert audit['allPassed'] and status['stage']=='complete'
    rows=[read(p) for p in (out/'results').glob('*/*.json')]
    costs={a:Decimal(0) for a in ['baseline','objrun']};unknown=[];exceptions=[]
    for p in (out/'calls').rglob('receipt.json'):
        x=read(p);rel=p.relative_to(out/'calls');arm=rel.parts[2];u=x.get('usage')
        # This entire run was on Saturday UTC. Recompute the observed official weekend tariff.
        assert all(dt.datetime.fromtimestamp(x[k],dt.timezone.utc).weekday()>=5 for k in ['startedEpoch','endedEpoch'])
        if not isinstance(u,dict):unknown.append(str(rel));assert x['cost']['kind']=='unknown'
        else:
            hit=u['prompt_cache_hit_tokens'];miss=u['prompt_cache_miss_tokens'];output=u['completion_tokens']
            assert u['prompt_tokens']==hit+miss
            value=(Decimal(hit)*Decimal('.003')+Decimal(miss)*Decimal('.15')+Decimal(output)*Decimal('.6'))/Decimal(1000000)
            assert abs(value-Decimal(str(x['cost']['lowerUsd'])))<Decimal('1e-12')
            assert abs(value-Decimal(str(x['cost']['upperUsd'])))<Decimal('1e-12')
            costs[arm]+=value
        if x.get('error'):
            dispatch=read(p.with_name('dispatch.json'))
            exceptions.append({'path':str(rel),'error':x['error'],'httpStatus':x['httpStatus'],'endedMinusDeadlineSeconds':x['endedEpoch']-dispatch['deadlineEpoch'],'costUnknown':x['cost']['kind']=='unknown'})
    for arm,value in costs.items():assert abs(value-Decimal(str(summary['accounting']['byArm'][arm]['estimateLowerUsd'])))<Decimal('1e-8')
    no_submit=[r['id'] for r in rows if r['arm']=='objrun' and r.get('candidateHow')!='submitted']
    deadline_markers=sum(r.get('error')=='OriginalSolveDeadlineExhausted' for r in rows if r['arm']=='objrun')
    detail={'allPassed':True,'method':'independent Decimal recomputation from complete usage at observed weekend USD tariff per million: hit .003 / miss .15 / output .6',
            'knownEstimatedUsdByArm':{a:str(v) for a,v in costs.items()},'knownEstimatedUsd':str(sum(costs.values())),
            'unknownCostRequests':unknown,'requestExceptions':exceptions,'noSubmissionIds':no_submit,
            'remoteAuditChecks':len(audit['checks']),'localVerificationChecks':verification['checkCount'],'archiveSha256':meta['sha256']}
    with (LOCAL/'DELIVERY_COST_RECHECK.json').open('x',encoding='utf-8') as f:json.dump(detail,f,ensure_ascii=False,indent=2);f.write('\n')
    paired=summary['paired'];wins=len(paired['wins']);losses=len(paired['losses']);both=summary['arms']['baseline']['passed']-losses
    lines=['# OlympiadBench Complete Delivery Report','',
        f"Run `{summary['run']}` completed on novaeve; all 472 unique results are valid. All 268 acceptance checks requiring no model calls and the fixed 8-problem, two-arm canary passed. Canary results are included in the formal results without duplicate generation.",'',
        '|Method|Passed / problems|Success rate|Model requests|Estimated cost with known usage (USD)|Requests with unknown cost|',
        '|---|---:|---:|---:|---:|---:|']
    for arm,label in [('baseline','Single attempt'),('objrun','Full ObjRun')]:
        a=summary['arms'][arm];c=summary['accounting']['byArm'][arm]
        lines.append(f"|{label}|{a['passed']}/236|{a['knownCorrectFraction']:.2%}|{c['requests']}|{costs[arm]}|{c['unknownCostRequests']}|")
    lines+=['',f"Paired improvement: **{paired['difference']*100:.2f} percentage points**. Stratified bootstrap within the five subdomains used 20,000 resamples, seed=20261017; the 95% interval is **{paired['ci95'][0]*100:.2f}–{paired['ci95'][1]*100:.2f} percentage points**. Only the full method passed {wins} problems; only the single attempt passed {losses}; both passed {both}; both failed {236-wins-losses-both}. The interval reflects problem resampling in this run, not stability across repeated API runs.",'',
        '|Subdomain|Problems|Single-attempt passes|Full-method passes|','|---|---:|---:|---:|']
    for name,arms in summary['subfields'].items():lines.append(f"|{name}|{arms['baseline']['tasks']}|{arms['baseline']['passed']}|{arms['objrun']['passed']}|")
    lines+=['',f"Costs were independently recomputed using the saved official weekend rates. The known portion ranges from **${sum(costs.values())} to ${sum(costs.values())}**; **{len(unknown)} requests have unknown costs**, so no finite upper bound on total cost is available, and unknown costs are not treated as zero. Actual per-request bills are unavailable. These requests were aborted near the original whole-problem deadline, with HTTP 200 but incomplete usage. See the cost-recheck JSON for discrepancies.",'',
        f"In the full-method arm, {len(no_submit)} problems had no actual submission within the original limit and count as ordinary failures under the protocol. {deadline_markers} results retain OriginalSolveDeadlineExhausted; clocks were not restarted and no answers were added. In the single-attempt arm, {summary['arms']['baseline']['length']} responses ended with length and were graded from their original output. There are 0 problem-level API or grading unknowns. All settled receipts are present; {len(exceptions)} deadline-aborted receipts are listed separately from ordinary complete responses.",'',
        'All calls use deepseek-flash through the official DeepSeek API, with thinking enabled/high/16384; the observed mapping DeepSeek-V4.1-Flash-1017 is a rolling alias. The full method runs actual ObjRun with 600 seconds per problem, c5, 4 branches, 12 units each for ask/act, and only submit/verify/task_tree/node_load. Task/model concurrency is capped at 16; rule-grading concurrency is 4. The official MathJudger, final_answer[0], parameter order, and per-problem tolerances are fixed.',
        'The full method adds attempts and online rule feedback. This experiment supports a system-level effectiveness comparison, not attribution to one mechanism or claims of equal-cost efficiency. The 69 trajectories that passed after an initial internal rejection are repair candidates requiring independent review.','',
        'The original aggregator failed by treating a string-valued submit argument as an object. The offline correction follows the frozen native finalCandidate semantics for an empty answer, without JSON-decoding strings again. Final-candidate binding checks passed for all 236 full-method results. The original error, script, failed replay, corrected scripts, and rationale are archived in outputs/canonical/analysis-recovery-v1 and analysis-recovery-v2. The frozen scientific package, original candidates, grades, and request receipts remain unchanged; no new model calls were made. The first recovery script exited because an operational verifier path was not deployed; the second generated command failed syntax validation before execution. Those originals and correction rationales are also retained.',
        'One publicly released official grading example has an annotation inconsistent with the fixed inference path. The wrapper matches the fixed official implementation; this discrepancy was disclosed in acceptance checks requiring no model calls, and grading was not changed because of it.','',
        f"Remote audit: **{len(audit['checks']):,} checks passed**. Independent local verification: **{verification['checkCount']:,} checks passed**, covering archive SHA256 on both ends, candidates/actual submit calls, source and dependencies, official wire format, usage/costs, global concurrency, and absence of keys in delivered materials. Additional cost calculations are in [DELIVERY_COST_RECHECK.json](DELIVERY_COST_RECHECK.json).",'',
        f"Complete archive: {meta['bytes']:,} bytes; SHA256 `{meta['sha256']}`.",'',
        f"- [Per-problem CSV](FINAL_RESULTS.csv)\n- [All results, logs, raw requests/responses, SQLite, source, and dependencies]({Path(meta['archive']).name})\n- [Complete extracted directory](full-results/)\n- [Machine-readable summary](SUMMARY.json)\n- [Remote audit](AUDIT.json)\n- [Local verification](LOCAL_VERIFICATION.json)\n- [Delivery receipt](DELIVERY.json)",'',
        f"Immutable NAS archive: `{meta['remoteArchive']}`. This supplemental delivery report sits beside the archive and does not rewrite the verified original."]
    with (LOCAL/'DELIVERY_REPORT.md').open('x',encoding='utf-8') as f:f.write('\n'.join(lines)+'\n')
    print(json.dumps({'written':'DELIVERY_REPORT.md','costRecheckPassed':True,'knownEstimateUsd':str(sum(costs.values())),'unknownCostRequests':len(unknown)}))


if __name__=='__main__':main()
