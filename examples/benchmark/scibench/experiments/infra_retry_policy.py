"""One explicitly authorized fresh attempt for confirmed infrastructure failures."""
import hashlib,json,re

ARMS=['baseline','objrun','independent','binary']
SUFFIX='\nSolve the problem. End with one finite numeric answer in the requested unit inside \\boxed{...}. For scientific notation use a\\times 10^{n}.'
EXPERIMENT='scibench-formal-20261016-v1'
REPAIR='scibench-infra-retry-20261016-v1-c32'
PROTOCOL=['model','canonicalModel','provider','maxTokens','temperature','reasoning','arms','checks','solveSeconds','maxBranches','maxDeadSiblings','cyclesMaxUnits','samples','perQuestionDollarCap','pilotBudgetUsd','proxy','toolPolicy','continueIsolatedTransportFaults','maxConsecutiveProviderFaults']

def sha(raw):return hashlib.sha256(raw if isinstance(raw,bytes) else raw.encode()).hexdigest()
def classify(r):
    g=r.get('grade',{})
    if g.get('valid'):return 'valid_pass' if g.get('passed') else 'valid_fail'
    error=str(r.get('error') or '')
    if r.get('arm')=='objrun':
        reason=' '.join(str(r.get(k) or '') for k in ['budgetReason','stoppingReason'])
        verdict=r.get('engineVerdict') or {}
        if verdict.get('expired') or re.search(r'SolveTimeBudget|SolveCheckBudget|CyclesBudget|BranchBudget|over solve_seconds|cycles?_budget|check_budget',reason,re.I):return 'native_budget_exhausted'
        if g.get('outcome')=='no_final_submission' or r.get('candidateHow')=='none':return 'native_no_final_submission'
    if re.search(r'SourceChanged|UnexpectedModel|UnexpectedProvider|IdentityMismatch|GlobalAdmission|InvalidPrivateGrader|InvalidGraderResult|Integrity|UnresolvedDispatch',error):return 'integrity_or_protocol_error'
    if g.get('outcome')=='infrastructure_error' and error:
        if not r.get('modelCalls') and re.search(r'TimeoutError|BalanceHTTP|account.*timeout|credits.*timeout',error,re.I):return 'infra_account_check'
        if re.search(r'ProviderFault:|PinnedProviderFault:|BalanceHTTP|ProviderHTTP[0-9]+|HTTP[ :]*(?:4[0-9]{2}|5[0-9]{2})|TimeoutError|NetworkError|fetch failed|ECONN|EAI_AGAIN|ENETUNREACH|socket|TLS|IncompleteProviderResponse|NonJSONProviderResponse',error,re.I):return 'infra_transport'
    return 'unclassified_invalid'

def make_plan(records,source_root,archive_sha):
    assert len(records)==1664 and len({(r['arm'],r['id']) for r in records})==1664
    attempts=[];classification=[]
    for r in sorted(records,key=lambda x:(x['id'],ARMS.index(x['arm']))):
        kind=classify(r);eligible=kind.startswith('infra_')
        row={'arm':r['arm'],'id':r['id'],'classification':kind,'eligible':eligible,'originalResultPath':source_root+'/outputs/canonical/results/'+r['arm']+'/'+r['id']+'.json','originalPromptSha256':r['promptSha256']}
        classification.append(row)
        if eligible:attempts.append({**row,'attemptId':EXPERIMENT+'/'+r['arm']+'/'+r['id']+'/infra-retry-1','attemptNo':1,'originalExperiment':EXPERIMENT,'isNewFullAttempt':True})
    return {'schema':1,'run':REPAIR,'originalExperiment':EXPERIMENT,'sourceRoot':source_root,'sourceArchiveSha256':archive_sha,'globalSlots':32,'maxNewFullAttemptsPerIdentity':1,'attempts':attempts,'classification':classification,'mergeRule':'Keep all original valid scores and all excluded native budget/no-submit records; replace only eligible infrastructure identities with their one repair outcome, including valid failures. Never best-of. Missing repairs remain original anomalies.','primaryDenominatorPerArm':416,'secondaryDenominator':'valid scored records; invalid outcomes separately reported'}
