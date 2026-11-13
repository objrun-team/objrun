"""Readable local delivery summary from verified artifacts; no model operations."""
from collections import Counter
from pathlib import Path
import csv
import json
from ops import LOCAL
from protocol import DEFECT, digest


def main():
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    verification=read(LOCAL/'LOCAL_VERIFICATION.json');delivery=read(LOCAL/'DELIVERY.json')
    assert verification['allPassed'] and delivery['verified'] and delivery['delivered']
    summary=read(LOCAL/'SUMMARY.json');root=Path(delivery['retrieval']['fullResults']);out=root/'outputs/canonical'
    server_checks=len(read(LOCAL/'AUDIT.json')['checks'])
    with (LOCAL/'FINAL_RESULTS.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    assert len(rows)==1416
    def counts(items):
        valid=[r for r in items if r['solverValid']=='True' and r['gradeValid']=='True']
        passed=sum(r['passed']=='True' for r in valid);n=len(items);unknown=n-len(valid)
        return {'tasks':n,'valid':len(valid),'passed':passed,'unknown':unknown,'accuracyBounds':[passed/n,(passed+unknown)/n]}
    for arm in summary['arms']:
        observed=counts([r for r in rows if r['arm']==arm])
        assert all(observed[k]==summary['arms'][arm][k] for k in observed)
    seq_sensitivity={a:counts([r for r in rows if r['arm']==a and r['category']=='SeqQA' and r['id']!=DEFECT]) for a in summary['arms']}
    trace=[r for r in read(LOCAL/'TRAJECTORY_ANALYSIS.json') if r['arm']=='objrun']
    labels=Counter(len(r['distinctEvaluatedLabels']) for r in trace)
    trajectory={'firstCandidatePassed':sum(bool(r['firstCandidateGrade']['passed']) for r in trace),'firstCandidatePresent':sum(r['firstCandidate'] is not None for r in trace),
                'denominator':708,'distinctEvaluatedLabelsHistogram':dict(sorted(labels.items())),
                'multipleEvaluatedLabels':sum(v for k,v in labels.items() if k>1),'firstCorrectnessFeedbackFalseThenSubmittedPass':sum(r.get('realRepairCandidate',False) for r in trace)}
    assert trajectory['firstCandidatePassed']==summary['firstCandidate']['objrunPassed']
    costs=summary['accounting']['byArm'];total_cost=sum(c['knownActualCostUsd'] for c in costs.values());unknown_cost=sum(c['unknownCostRequests'] for c in costs.values())
    recovery_archive=read(LOCAL/'v2-pilot-recovery-archive.json')
    assert recovery_archive['twoEndsSha256Verified'] and digest(Path(recovery_archive['localArchive']).read_bytes())==recovery_archive['sha256']
    results={'verified':True,'parameters':summary['parameters'],'oracleFeedback':True,'arms':summary['arms'],'categories':summary['categories'],'subtasks':summary['subtasks'],
             'paired':summary['paired'],'knownDuplicateChoiceSensitivity':summary['knownDuplicateChoiceSensitivity'],'seq599Sensitivity':seq_sensitivity,'trajectory':trajectory,
             'accounting':summary['accounting'],'knownActualCostUsd':total_cost,'unknownCostRequests':unknown_cost,'recoveryTiming':delivery['recoveryTiming'],
             'views':delivery['views'],'retrieval':delivery['retrieval'],'localVerificationCheckCount':verification['checkCount'],
             'originalPilotArchive':delivery['originalPilotArchive'],'recoveryPilotArchive':recovery_archive,
             'sourceSha256':digest(Path(__file__).read_bytes()),'summarySha256':digest((LOCAL/'SUMMARY.json').read_bytes()),'verificationSha256':digest((LOCAL/'LOCAL_VERIFICATION.json').read_bytes())}
    normalization=LOCAL/'verification-history/approval-line-ending-normalization.json'
    if normalization.exists():results['approvalLineEndingNormalization']=read(normalization)
    (LOCAL/'RESULTS.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def bounds(s):return f"{s['accuracyBounds'][0]*100:.2f}%–{s['accuracyBounds'][1]*100:.2f}%"
    def link(name,path):return f'[{name}]({Path(path).as_posix()})'
    lines=['# LAB-Bench results and delivery','','708 tasks × single-shot / full ObjRun, totaling 1416 terminal states. Eight infrastructure unknowns are retained; full archive retrieval and local verification passed.',
           '','|Task set|Arm|Valid/total|Known passes|Infrastructure unknowns|Full-denominator accuracy bounds|','|---|---|---:|---:|---:|---|']
    for category,arms in list(summary['categories'].items())+[('All',summary['arms'])]:
        for arm,s in arms.items():lines.append(f"|{category}|{arm}|{s['valid']}/{s['tasks']}|{s['passed']}|{s['unknown']}|{bounds(s)}|")
    lines+=['','Unknowns are not forced into wrong-answer counts. Bounds reflect only their worst/best possible outcomes. Normal format failures are known method failures.',
            '', '|Arm|Valid-answer precision|Full-denominator coverage|Invalid format|Length truncation|','|---|---:|---:|---:|---:|']
    for arm,s in summary['arms'].items():lines.append(f"|{arm}|{s['precision']*100:.2f}%|{s['coverage']*100:.2f}%|{s['formatInvalid']}|{s['length']}|")
    paired=summary['paired']
    lines+=['',f"There are {paired['validPairs']} fully valid task pairs. Paired accuracy difference: {paired['differenceOnValidPairs']*100:.2f} percentage points; stratified task-bootstrap 95% interval: [{paired['ci95ConditionalOnValidPairs'][0]*100:.2f}, {paired['ci95ConditionalOnValidPairs'][1]*100:.2f}]. This describes task-resampling uncertainty for this API run, not variation across repeated experiments.",
            '', '**Interpretation limits:** The single-shot arm has 391 invalid-format tasks, including 356 length-truncated responses without parseable answers. The full arm receives online ground-truth correctness feedback and can repeatedly verify choices within budget. Its high final score includes benefits from output formatting, tool execution, and option elimination; it cannot directly be interpreted as repaired biological reasoning.',
            '',f"Within the same full-method trajectories, first candidates have {trajectory['firstCandidatePassed']}/708 known passes; {trajectory['multipleEvaluatedLabels']} tasks evaluated multiple labels; and {trajectory['firstCorrectnessFeedbackFalseThenSubmittedPass']} records received false as their first correctness feedback but passed on actual final submission. These are trajectory statistics, not a third experimental arm.",
            '', '|Arm|Known actual cost USD|Unknown-cost requests|All transport attempts|','|---|---:|---:|---:|']
    for arm,c in costs.items():lines.append(f"|{arm}|{c['knownActualCostUsd']:.9f}|{c['unknownCostRequests']}|{c['requests']}|")
    lines+=[ '',f"Known actual costs total ${total_cost:.9f}, with {unknown_cost} unknown charges and no unsettled in-flight requests. Costs use OpenRouter usage.cost; the v2 ledger already includes every v1 receipt, so pilot charges are not added twice. Unknown costs are not zero, and reservations are not actual costs.",
             '',f'The prespecified identical-text-option task {DEFECT} remains in the main result. See RESULTS.json for the 707-task result excluding it; SeqQA sensitivity results for 599 tasks follow:',
             '', '|Arm|Valid/599|Known passes|Unknowns|Accuracy bounds|','|---|---:|---:|---:|---|']
    for arm,s in seq_sensitivity.items():lines.append(f"|{arm}|{s['valid']}|{s['passed']}|{s['unknown']}|{bounds(s)}|")
    lines+=['','The 3 pilot recoveries used only the original remaining approximately 297 seconds, unchanged first logical-request wire payloads, and two cumulative transports each. Repair downtime of about 324 seconds is recorded separately, so these were not continuous 600-second wall-clock experiments. Original interrupted, recovered, and paired views excluding these 3 tasks are in DELIVERY.json. The original all-valid pilot gate failed; the user explicitly approved continuing with 3 unknowns preserved, while retaining all other audit requirements.',
            '', f"Passed {server_checks} server audit checks and {verification['checkCount']} local checks. Archive SHA256: {delivery['retrieval']['sha256']}.",
            '',link('Complete extracted materials',root)+'; '+link('Complete archive',delivery['retrieval']['archive'])+'.',
            '',link('Per-task CSV',LOCAL/'FINAL_RESULTS.csv')+'; '+link('Full statistics and subtasks',LOCAL/'SUMMARY.json')+'; '+link('Candidate and feedback trajectory index',LOCAL/'TRAJECTORY_ANALYSIS.json')+'; '+link('Local verification',LOCAL/'LOCAL_VERIFICATION.json')+'.',
            '', 'Complete extracted materials include source data, private grading mappings, frozen source/dependencies, every model request/response/generation ID/usage record, candidates, grades, anomalies, SQLite/task trees, and logs. File inventory: full-results/outputs/canonical/file-inventory.json.']
    if normalization.exists():lines+=['','Verification initially stopped because local approval records used Windows CRLF while the archive used LF. After normalizing only local line endings, the original checks were rerun; JSON content, archives, and experiment data remain unchanged. Original files and conversion-hash evidence: '+link('Line-ending normalization record',normalization)+'.']
    (LOCAL/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    source=LOCAL/'delivery-analysis-source';source.mkdir(exist_ok=True);(source/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    manifest={p.name:digest(p.read_bytes()) for p in [LOCAL/'RESULTS.md',LOCAL/'RESULTS.json',source/Path(__file__).name]}
    (LOCAL/'RESULTS_PROVENANCE.json').write_text(json.dumps({'files':manifest,'scope':'local postprocessing of verified delivery; frozen archive unmodified'},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'report':str(LOCAL/'RESULTS.md'),'knownActualCostUsd':total_cost,'unknownCostRequests':unknown_cost,'seq599Sensitivity':seq_sensitivity}))


if __name__=='__main__':main()
