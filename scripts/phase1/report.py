"""Build a phase-1 evidence report; completed pilots require separate acceptance."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs/phase1'
PILOTS = DOCS / 'pilots'
RUNS = {
    'gpqa': 'phase1-gpqa-2026-10-07T21-35-26-479Z',
    'cmt': 'phase1-cmt-2026-10-07T21-35-57-664Z',
    'aime': 'phase1-aime-2026-10-07T21-38-19-542Z',
    'chembench': 'phase1-chembench-2026-10-07T21-39-14-785Z',
    'chemiq': 'phase1-chemiq-2026-10-07T21-39-46-436Z',
    'atmossci-bench': 'phase1-atmossci-bench-2026-10-07T21-34-07-121Z',
    'lab-bench': 'phase1-lab-bench-2026-10-07T21-37-30-940Z',
    'humaneval-plus': 'phase1-humaneval-plus-2026-10-07T21-44-47-134Z',
    'scicode': 'phase1-scicode-verified-2026-10-07T21-48-09-120Z',
    'atomworld': 'phase1-atomworld-2026-10-07T22-03-23-513Z',
    'llm-srbench': 'phase1-llm-srbench-2026-10-07T22-05-05-487Z',
    'biocoder': 'phase1-biocoder-2026-10-07T22-10-01-874Z',
}
SUBSETS = {
    'gpqa': 'Diamond, first 10 tasks; fixed option order',
    'cmt': 'First 10 complete problems in official data',
    'aime': 'First 10 tasks of 2024 I; prepared data includes 60 tasks across 2024/2025',
    'chembench': 'First 10 in seed=0 order after prespecified exclusion of 12 official tasks with defective nonpositive targets; deterministic grading',
    'chemiq': 'Official default first 10 tasks; RDKit/OPSIN, official length limit retained',
    'atmossci-bench': 'First 10 MCQ10 tasks; open-ended tasks awaiting validation',
    'lab-bench': 'First 10 public ProtocolQA tasks; text only, other image categories awaiting validation',
    'humaneval-plus': 'First 10 v0.1.10 tasks, all base+plus tests; isolated RPC adds timing overhead',
    'scicode': 'SciCode-Verified v2: 10 complete problems, 39 substeps; original version awaiting download',
    'atomworld': 'First 10 AddAtomAction tasks; stol=0.5, primitive_cell=false',
    'llm-srbench': 'Author-published LSR-Transform; 30 visible training samples, remaining training points for feedback, all test points for final grading',
    'biocoder': '10 Rosalind tasks; official output comparison; complete GitHub Python/Java fuzz-testing queue awaiting validation',
    'scienceworld': '10 complete action episodes on native test variations; 120 seconds/100 actions',
}
DEFERRED = {
    'minif2f': 'Lean/Mathlib toolchain and build cache; deferred at user request.',
    'putnambench': 'Lean/Mathlib toolchain and build cache; deferred at user request.',
    'deepswe': 'Per-repository images and repair environments; 112/113 and v1/v1.1 still need verification, deferred at user request.',
    'terminal-bench': 'Per-task containers; hidden-test isolation still awaits audit, deferred at user request.',
    'skillsbench': 'Per-task containers; 76/87 scope and reference-environment faults still need verification, deferred at user request.',
    'scienceagentbench': 'Verified data and official container environment; deferred at user request.',
    'astrovisbench': 'Official workflow requires about 100GB free; deferred at user request.',
}
DATASET_COUNTS = {'gpqa': 198, 'cmt': 50, 'aime': 60, 'chembench': 2785, 'chemiq': 816, 'humaneval-plus': 164, 'atomworld': 1000, 'atmossci-bench': 670, 'lab-bench': 108, 'scicode': 64}
DIAGNOSTIC_REASONS = {
    'phase1-gpqa-2026-10-07T20-50-33-704Z': 'Answer-format calibration, not the prespecified 10-task pilot.',
    'phase1-gpqa-2026-10-07T20-52-31-336Z': 'No source snapshot at startup; historical versions are not backfilled.',
    'phase1-cmt-2026-10-07T20-53-10-226Z': 'No source snapshot at startup; historical versions are not backfilled.',
    'phase1-scicode-verified-2026-10-07T21-08-34-504Z': 'First-task preflight, not a 10-task pilot.',
    'phase1-scicode-verified-2026-10-07T21-09-58-497Z': 'Grading adapter had comparison-module/Sympy transport faults; do not advertise a model pass rate for this round.',
    'phase1-atmossci-bench-2026-10-07T21-31-35-133Z': 'Grading route misconfiguration caused 404; retain all 10 tasks and costs.',
    'phase1-lab-bench-2026-10-07T21-33-17-084Z': 'Grading route 404; stopped on task 7 after completing 6; database costs checked separately.',
    'phase1-scienceworld-2026-10-07T22-10-54-693Z': 'Grading and final-grading route matching omitted a slash, returning 404; retain 7 faulty episodes and costs of the interrupted task 8.',
}

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def peak_cost(usage):
    inp, out, cached = [float(x or 0) for x in usage]
    return ((inp - cached) * .3 + cached * .006 + out * 1.2) / 1e6

def scicode_control_evidence(ids):
    expanded=read(DOCS/'scicode-expanded-controls.json')
    negative=read(DOCS/'scicode-negative-controls.json')
    path=ROOT/'.phase1-data/scicode-verified/vendor/scicode-verified/scicode_verified/problems_test.jsonl'
    problems={str(p['problem_id']):p for p in map(json.loads,path.read_text(encoding='utf-8').splitlines())}
    expected={(pid,step['step_number']) for pid in ids for step in problems[pid]['sub_steps']}
    positive=expanded['records']
    wrong=[r for r in negative['records'] if r['kind']=='wrong_return']
    syntax=[r for r in negative['records'] if r['kind']=='syntax_error']
    if not expanded.get('complete') or not expanded.get('allPassed') or not negative.get('complete') or not negative.get('allPassed'):
        raise ValueError('SciCode selected-step grader controls are incomplete or failing')
    if len(positive)!=len(expected) or {(r['problem'],r['step']) for r in positive}!=expected:
        raise ValueError('SciCode positive control task identity mismatch')
    if len(wrong)!=len(expected) or {(r['problem'],r['step']) for r in wrong}!=expected:
        raise ValueError('SciCode wrong-return control task identity mismatch')
    if len(syntax)!=len(ids) or {r['problem'] for r in syntax}!=set(ids):
        raise ValueError('SciCode syntax controls omit a selected problem')
    for record in positive+negative['records']:
        fixture=ROOT/'examples/benchmark/scicode/fixtures'/record['source']
        if not fixture.resolve().is_relative_to((ROOT/'examples/benchmark/scicode/fixtures').resolve()):
            raise ValueError('Invalid reference fixture path')
        if record['sourceSha256']!=hashlib.sha256(fixture.read_bytes()).hexdigest():
            raise ValueError('SciCode reference control source changed')
        if record.get('valid') is not True:
            raise ValueError('SciCode control contains a grader fault')
    if any(r.get('passed') is not True for r in positive) or any(r.get('passed') is not False or r.get('checkPassed') is not True for r in negative['records']):
        raise ValueError('SciCode control verdict mismatch')
    return {'wholeProblems':len(ids),'positiveSteps':len(positive),'wrongReturnSteps':len(wrong),
            'syntaxProblems':len(syntax),'gradingSeconds':90,'coverage':'Selected Verified v2 steps only',
            'correct':'scicode-expanded-controls.json','negative':'scicode-negative-controls.json',
            'privacyAndExit':'scicode-selfcheck.json','canonicalFullProtocolValidated':False}


def completed(slug, run):
    home = PILOTS / run
    summary, manifest = read(home / 'summary.json'), read(home / 'manifest.json')
    if not summary['completed'] or not manifest.get('sourceDigest'):
        raise ValueError(f'{run}: incomplete generation or missing source snapshot')
    if slug == 'scicode':
        acceptance = read(home / 'whole-problems-reaccepted.json')
        if not acceptance.get('complete') or not acceptance.get('allOriginalVerdictsMatch'):
            raise ValueError('SciCode candidate-identified reacceptance is incomplete or changed')
        candidates = {r['officialId']: hashlib.sha256(r['answer'].encode()).hexdigest() for r in summary['results']}
        identities = [identity for r in acceptance['results'] for identity in r['candidateIdentities']]
        if len(identities) != len(candidates) or {i['officialId'] for i in identities} != set(candidates) or any(i['answerSha256'] != candidates.get(i['officialId']) for i in identities):
            raise ValueError('SciCode reacceptance candidate changed')
        problems_path = ROOT / '.phase1-data/scicode-verified/vendor/scicode-verified/scicode_verified/problems_test.jsonl'
        problems = {str(p['problem_id']):p for p in map(json.loads,problems_path.read_text(encoding='utf-8').splitlines())}
        delivered = {r['officialId']:r['answer'] for r in summary['results']}
        for record in acceptance['results']:
            problem = problems[record['problem']]
            expected_ids = ['scicode-'+step['step_number'] for step in problem['sub_steps']]
            if [i['officialId'] for i in record['candidateIdentities']] != expected_ids:
                raise ValueError('SciCode candidate substep order changed')
            codes = []
            for identity in record['candidateIdentities']:
                answer = delivered[identity['officialId']]
                match = re.search(r'```(?:python)?\s*\n([\s\S]*?)```',answer)
                code = (match[1] if match else answer).strip()
                if hashlib.sha256(code.encode()).hexdigest() != identity['extractedCodeSha256']:
                    raise ValueError('SciCode extracted candidate changed')
                codes.append(code)
            cumulative = problem['required_dependencies']+'\n\n'+'\n\n'.join(codes)
            if hashlib.sha256(cumulative.encode()).hexdigest() != record['cumulativeCodeSha256']:
                raise ValueError('SciCode cumulative candidate changed')
        for name in ['controller.py','grade.py','worker.py','codec.py']:
            if acceptance['graderSourceHashes'].get(name) != hashlib.sha256((ROOT/'examples/benchmark/scicode'/name).read_bytes()).hexdigest():
                raise ValueError('SciCode reacceptance grader source changed')
        verdicts = [r['finalAcceptance'] for r in acceptance['results']]
        ids = [r['problem'] for r in acceptance['results']]
    elif slug == 'scienceworld':
        acceptance = read(home / 'acceptance.json')
        verdicts = [r['final'] for r in acceptance['episodes']]
        ids = [r['id'] for r in acceptance['episodes']]
    else:
        acceptance = read(home / 'acceptance.json')
        verdicts = acceptance['records']
        ids = [r['officialId'] for r in verdicts]
        candidates = {r['officialId']: hashlib.sha256(r['answer'].encode()).hexdigest() for r in summary['results']}
        if any(r['candidateSha256'] != candidates.get(r['officialId']) for r in verdicts):
            raise ValueError(f'{run}: acceptance candidate changed')
    if len(verdicts) != 10 or len(set(ids)) != 10:
        raise ValueError(f'{run}: pilot denominator is not ten distinct complete tasks')
    if any(type(r.get('valid')) is not bool or type(r.get('passed')) is not bool for r in verdicts):
        raise ValueError(f'{run}: malformed verdict')
    control_name = 'scicode' if slug == 'scicode' else 'atmossci' if slug == 'atmossci-bench' else 'lab' if slug == 'lab-bench' else slug
    current_control = ROOT / '.scratch/phase1' / f'{control_name}-selfcheck.json'
    controls = read(current_control if current_control.exists() else DOCS / f'{control_name}-selfcheck.json')
    if controls.get('allPassed') is not True:
        raise ValueError(f'{slug}: grader control did not pass')
    row = {'slug': slug, 'run': run, 'tasks': len(verdicts), 'valid': sum(r['valid'] for r in verdicts), 'passed': sum(r['valid'] and r['passed'] for r in verdicts), 'graderErrors': sum(not r['valid'] for r in verdicts), 'generationUnits': summary['tasks'], 'seconds': sum(r['seconds'] for r in summary['results']), 'usdUpperBound': summary['usdUpperBound'], 'sourceDigest': manifest['sourceDigest'], 'taskIds': ids, 'protocol': SUBSETS[slug], 'acceptance': (home / ('whole-problems-reaccepted.json' if slug == 'scicode' else 'acceptance.json')).relative_to(DOCS).as_posix()}
    if slug == 'scicode':
        row['gradingControls'] = scicode_control_evidence(ids)
    return row

def report():
    world = sorted(PILOTS.glob('phase1-scienceworld-*'))
    if world:
        RUNS['scienceworld'] = world[-1].name
    rows = [completed(slug, run) for slug, run in RUNS.items()]
    if len(rows) != 13:
        raise ValueError('All thirteen selected lightweight pilots must finish before final reporting')
    costs = []
    for p in sorted(PILOTS.glob('*/summary.json')):
        summary = read(p)
        amount = float(summary.get('usdUpperBound', 0))
        db = ROOT / '.phase1-data/pilots' / p.parent.name / 'data/h2h.sqlite'
        db_amount = None
        if db.exists():
            with sqlite3.connect(f'file:{db.as_posix()}?mode=ro', uri=True) as conn:
                usage = conn.execute('select sum(prompt_tokens),sum(completion_tokens),sum(cached_tokens) from agent_bot_msg').fetchone()
                db_amount = peak_cost(usage)
        costs.append({'run': p.parent.name, 'classification': 'selected_pilot' if p.parent.name in RUNS.values() else 'diagnostic', 'generationUnitsCompleted': summary['tasks'], 'completed': summary['completed'], 'summaryUpperBoundUsd': amount, 'databaseRecordedUpperBoundUsd': db_amount, 'recordedUpperBoundUsd': max(amount, db_amount or 0), 'reason': DIAGNOSTIC_REASONS.get(p.parent.name)})
    recorded = sum(c['recordedUpperBoundUsd'] for c in costs)
    reserve = read(DOCS / 'cost-reconciliation.json')['unreportedUsageReserveUsd']
    output = {'createdAt': datetime.now(timezone.utc).isoformat(), 'scope': '13 lighter preparation pilots completed; 7 high-storage benchmarks deferred by user. Variants/subsets remain explicit; full 20-benchmark canonical readiness is not claimed.', 'pilotBenchmarks': len(rows), 'pilotWholeTasks': sum(r['tasks'] for r in rows), 'pilotGenerationUnits': sum(r['generationUnits'] for r in rows), 'pilotCostUpperBoundUsd': sum(r['usdUpperBound'] for r in rows), 'allRecordedModelCostUpperBoundUsd': recorded, 'unreportedUsageReserveUsd': reserve, 'budgetAccountedUpperBoundUsd': recorded + reserve, 'budgetUsd': 30, 'providerInvoiceVerified': False, 'pilots': rows, 'deferred': DEFERRED, 'costLedger': costs}
    if output['budgetAccountedUpperBoundUsd'] > 30:
        raise ValueError('Shared pilot cap exceeded')
    (DOCS / 'results.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    registry = read(DOCS / 'benchmarks.json')
    registry['updatedAt'] = output['createdAt']
    registry['executionScope'] = output['scope']
    by_slug = {r['slug']: r for r in rows}
    sources = {}
    for bench in registry['benchmarks']:
        slug = bench['slug']
        source_home = 'scicode-verified' if slug == 'scicode' else slug
        file = ROOT / '.phase1-data' / source_home / 'source.json'
        if file.exists():
            sources[slug] = read(file)
            if sources[slug].get('commit') and slug != 'scicode': bench['sourceCommit'] = sources[slug]['commit']
        if slug in by_slug:
            row = by_slug[slug]
            bench.update(state='pilot_variant_only' if slug == 'scicode' else 'pilot_validated_subset', pilotTasksCompleted=row['tasks'], pilotPassed=row['passed'], pilotValid=row['valid'], pilotRun=row['run'], protocol=row['protocol'], selfCheck='Passed controls; exact coverage and limitations in selfcheck artifact', canonicalFullProtocolValidated=False)
            if slug == 'scicode':
                original = read(ROOT / '.phase1-data/scicode/source.json')
                bench['sourceCommit'] = bench['originalSourceCommit'] = original['commit']
                bench['pilotSourceCommit'] = sources[slug]['commit']
                sources[slug] = {'original': original, 'pilotVariant': sources[slug], 'variantLabel': 'SciCode-Verified v2'}
                bench['pilotVariant'] = 'SciCode-Verified v2'
                bench['gradingControls'] = row['gradingControls']
                bench['selfCheck'] = '39 selected-step correct and wrong-return controls, 10 syntax controls, plus private-target/fixture/exit probes passed.'
                bench['remaining'] = 'Original data quota; canonical multi-environment/1800s; unselected class/helper-dependent tasks remain unvalidated.'
        else:
            bench.update(state='deferred_storage', pilotTasksCompleted=0, deferReason=DEFERRED[slug])
    (DOCS / 'benchmarks.json').write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (DOCS / 'benchmark-sources.json').write_text(json.dumps(sources, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    text = ['# Phase-one lightweight pilot report', '', 'The user requested deferring tasks that require substantial storage. This round completed pilots of restricted subsets/versions of 13 datasets, 10 complete tasks each; 7 datasets were deferred. The original full standards for all 20 datasets remain unmet. The following is integration and grading-readiness evidence and cannot establish gains of ObjRun over baselines.', '', f"Model: DeepSeek-V4.1-Flash. Estimated cost of formally retained pilots is ${output['pilotCostUpperBoundUsd']:.4f}; including diagnostics and additional SQLite usage, total ${recorded:.4f}. Another ${reserve:.2f} is reserved for interrupted requests, totaling ${recorded+reserve:.4f}, below the initial $30 cap. Provider bills have not been reconciled.", '', '| Dataset/subset | Independent final passes/all tasks | Valid final grades | Model cost upper bound (USD) | Mean seconds per task | Evidence |', '|---|---:|---:|---:|---:|---|']
    for r in rows:
        text.append(f"| {r['slug']}: {r['protocol']} | {r['passed']}/{r['tasks']} | {r['valid']}/{r['tasks']} | {r['usdUpperBound']:.6f} | {r['seconds']/r['tasks']:.1f} | [Independent acceptance]({r['acceptance']}) |")
    text += ['', 'ScienceWorld duration includes interaction; SciCode includes all substeps of each complete problem. Rejections and invalid final grades are recorded separately, without deleting tasks to shrink the denominator. Independent correct controls and incorrect-return controls passed for all 39 selected SciCode steps, alongside 10 syntax-error and hidden-target/reference-file/exit controls; the complete original version and standardized multi-environment reproduction remain outstanding. The 39 substeps are not counted as 39 complete problems.', '', '## Costs and subsequent resources', '', 'Table costs are estimated from actually recorded tokens and public peak rates, including retries/revisions. Formal experiments differ in task count, model, timeouts, and groups; these 10 fixed-order tasks cannot be extrapolated directly to full leaderboard results or reliable bills. results.json retains diagnostic costs for each round. An initial budget order of magnitude can use pilot cost ÷ 10 × planned task count × experimental groups per dataset, with a tail allowance. Heavy datasets have not been piloted; costs and durations are not invented. Formal comparison still requires independent-retry, self-improvement, and ObjRun groups under identical conditions, plus the representative controls required by the documentation.', '', '## Deferred list', '']
    text += [f'- {slug}：{reason}' for slug, reason in DEFERRED.items()]
    text += ['', '## Measurement and reproduction', '', 'Each run manifest records model configuration, source digests at startup, task IDs, and data versions. Task files save actually delivered candidates and tool calls; SQLite retains raw usage. Final grading runs independently after task generation ends and is not used to select, revise, or stop generation. Symbolic-regression feedback uses training data only; test data is read only by final-grading /accept. Code candidates execute as UID65534 in read-only containers without networking; numeric targets/hidden tests exist only on the root grading side. ScienceWorld records initial/final state digests and private complete action traces.', '', 'Pinned dependencies and images are in environment.json and examples/benchmark/_lib/requirements-*.txt. Large data and private tests are in git-ignored .phase1-data; public evidence retains only versions, digests, and verdicts. Grading-control coverage is in each *selfcheck.json; unverified protocols are not marked complete.', '', 'Shared fixes passed type checking, 11 actual grading/candidate/fault regressions, and 4 Python grading-service tests. The paper removed 94.4/85.1 and unverified software-leaderboard superiority comparisons, and the PDF was rebuilt; historical sources are in legacy-scores.md.', '']
    lab=read(PILOTS/RUNS['lab-bench']/'abstention.json')
    text += ['', '## Supplemental final-grading metrics', '', f"LAB abstentions this round: {lab['abstentions']}/10; invalid delivery format: {lab['invalidFormat']}/10; total denominator remains 10 tasks. See this run's abstention.json for per-task identity and candidate digests.", '', 'The same frozen symbolic-regression candidates were independently regraded, saving per-task numerical errors including NMSE; boolean final grades agree with all original records. See numerical-metrics.json for the run. Current LSR-Transform release rows do not separately expose ood_input/output, so ordinary test error cannot be claimed as validated extrapolation error.', '', 'All 39 frozen actual SciCode answers received supplemental independent regrading bound to candidate digests; per-step and whole-problem boolean verdicts all agree with original acceptance. Independent correct controls were written from public problem definitions and never entered model context; pre-optimization timeout controls are retained as diagnostics.\n\nSee completion-audit.md for subsequent software/scientific grading-interface fixes and actual HTTP/cache regressions. These are code evidence, not completion of official software-leaderboard pilots.', '']
    (DOCS / 'report.md').write_text('\n'.join(text), encoding='utf-8')
    estimates = ['# Initial estimates for subsequent experiment costs', '', 'Only this round of model-token records is scaled linearly at peak rates; these are not bills, commitments, or sufficient resource budgets. Ten fixed-order tasks are biased in type and difficulty; different three-group protocols, long-tail durations, and models may change costs. Old software leaderboards and heavy datasets have no reliable data from this round and remain unestimated.', '', '| Protocol in this round | Downloaded data/subset task count | 10 tasks × 3 groups (USD) | Full subset × 3 groups, order of magnitude (USD) |', '|---|---:|---:|---:|']
    for r in rows:
        n = DATASET_COUNTS.get(r['slug'])
        estimates.append(f"| {r['slug']} | {n if n else 'full scope TBD'} | {r['usdUpperBound']*3:.4f} | {format(r['usdUpperBound']/10*n*3,'.4f') if n else 'TBD'} |")
    estimates += ['', 'SciCode count is 64 complete Verified v2 problems, including class/helper-function dependency problems not implemented this round; it does not mean all 64 are executable. ChemBench total includes 12 nonpositive-target tasks; formal results retain the full denominator and separately report official metric defects. AtmosSci counts only 670 MCQ10 tasks, LAB only 108 ProtocolQA tasks, and AtomWorld only 1000 AddAtomAction tasks; these subsets are not called complete benchmarks. AIME includes 60 tasks across 2024/2025. The complete BioCoder GitHub test queue, full symbolic-regression discovery protocol, and formal ScienceWorld variation manifest must first be specified.', '', 'Current resources follow lightweight-pilot limits: numeric/code grading containers 2 CPUs/2GB without networking; text grading containers 1GB; ScienceWorld JVM heap 512MB. These are limits for this round, not resource requirements for formal multi-environment/repository-repair protocols. Drive C currently has no headroom and drive F about 1GB; heavy images, Lean/Mathlib, and the roughly 100GB AstroVisBench environment are deferred.', '', 'Before phase two, fix actual task counts for all 20 datasets, conditions for U/self-refine/ObjRun, and documentation-specified A–E controls on 8 representative datasets. Use this table for initial order-of-magnitude estimates, then expand only after sampling costs under each revised formal protocol. Every model call, failure, and request without usage counts toward the shared budget; costs are not calculated by passed-task count.', '']
    (DOCS / 'experiment-estimates.md').write_text('\n'.join(estimates), encoding='utf-8')
    print(json.dumps({k: output[k] for k in ['pilotBenchmarks', 'pilotWholeTasks', 'pilotCostUpperBoundUsd', 'allRecordedModelCostUpperBoundUsd', 'budgetAccountedUpperBoundUsd']}))

if __name__ == '__main__':
    report()
