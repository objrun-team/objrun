"""Independent stored-evidence audit; never calls a model, grader or parser.

The source campaign artifacts remain unchanged. A deferred runtime audit is
separate evidence, never an assertion that the original shutdown succeeded.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('stored_gpqa_audit_helpers', HERE/'full-gpqa-inflight-audit.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
ROOT, DOCS = h.ROOT, h.OUT


def audit(run, deferred=None):
    if not re.fullmatch(r'repair-[0-9TZ-]+', run):
        raise ValueError('Invalid scientific campaign name')
    directory = DOCS/'campaigns'/run
    store = ROOT/'.phase1-data/repair'/run
    inputs, values, errors = {}, {}, []
    for name in ['manifest.json', 'source.json', 'frozen-source.json', 'summary.json', 'api-ledger.json']:
        values[name], inputs[name] = h.snapshot(directory/name)
    m, s, frozen, summary, ledger = (values[n] for n in values)
    def check(value, name):
        if not value:
            errors.append(name)
    check(m['campaign'] == summary['campaign'] == ledger['campaign'] == run, 'CampaignIdentity')
    plan = m['taskSchedule']
    plan_map = {x['index']: x for x in plan}
    check(len(plan_map) == len(plan) and set(plan_map) == set(range(len(plan))), 'FixedPlanIndices')
    check(h.sha(h.js_json(plan)) == m['taskScheduleSha256'] == s['taskScheduleSha256'], 'FixedPlanDigest')
    check(summary['plannedTaskRuns'] == len(plan), 'PlannedDenominator')
    source = h.source_audit(directory, s, frozen, m)
    digest_fields = {'sourceDigest': s['sourceDigest'], 'repairFiles': s['repairFiles']}
    for key in ['graderProvenance', 'taskScheduleSha256']:
        if key in s:
            digest_fields[key] = s[key]
    source['recorded_execution_digest_matches'] = h.sha(h.js_json(digest_fields)) == s['executionDigest']
    for key in ['recorded_source_digest_matches_its_file_list', 'recorded_execution_digest_matches', 'execution_digest_agrees_across_source_frozen_manifest', 'all_dependency_paths_in_archive', 'dependency_manifest_digest_matches']:
        check(source[key], 'Source:' + key)
    for key in ['digest_matches', 'bytes_match']:
        check(source['archive'][key], 'Archive:' + key)
    check(not source['executed_source_mismatches'], 'ExecutedSourceChanged')
    check(not source['archive']['member_manifest_mismatches'], 'ArchiveManifestMismatch')
    check(not source['archive']['current_member_mismatches'], 'ExecutedDependencyChanged')
    public = {}
    for slug in m['benchmarks']:
        name = slug + '-public-tasks.json'
        rows, inputs[name] = h.snapshot(directory/name)
        for row in rows:
            public[(slug, row['officialId'])] = row
        check([x['officialId'] for x in rows] == m['datasets'][slug]['selectedTaskIds'], 'PreselectedIds:' + slug)
    rates = m['ratesPeakUsdPerMillion']
    receipts, by_route, receipt_keys = [], {}, set()
    total_cost = 0.0
    expected_routes = {f"{run}/{x['benchmark']}/{x['arm']}/{x['replica']}/{x['officialId']}" for x in plan}
    for seq, call in enumerate(ledger['calls']):
        issues = []
        def rc(ok, name):
            if not ok:
                issues.append(name)
        evidence = {'sequence': seq, 'route': call['route'], 'errors': issues}
        rc(call['route'] in expected_routes, 'UnplannedRoute')
        rate_rejection = call.get('nonGenerationRejection') == 'upstream_rate_limit'
        rc(bool(call.get('finishedAt')) and not call.get('fault') and (call.get('httpStatus') == 200 or rate_rejection), 'UnfinishedOrFaultedProvider')
        try:
            request, raw, req = h.gzip_evidence(call['requestFile'], call['requestSha256'], store)
            response, _, rsp = h.gzip_evidence(call['responseFile'], call['responseSha256'], store)
            evidence.update(request=req, response=rsp)
            rc(req['receipt_digest_matches'] and req['stable_file_read'] and rsp['receipt_digest_matches'] and rsp['stable_file_read'], 'RawCaptureIntegrity')
            wire = {k: request[k] for k in h.WIRE if k in request}
            rc(wire == call['wireParameters'], 'ActualWireMatchesReceipt')
            openrouter = m.get('provider', '').startswith('https://openrouter.ai')
            declared = [('model', m['model']), ('temperature', m['temperature'])]
            if openrouter:
                rc(request.get('provider', {}).get('only') == [m.get('providerSlug', 'deepseek')] and request.get('provider', {}).get('allow_fallbacks') is False, 'PinnedProviderRouting')
                rc(request.get('reasoning') == {'enabled': True, 'effort': 'high', 'exclude': False} and request.get('seed') is None, 'OpenRouterThinkingWire')
                if not rate_rejection:
                    rc(response.get('provider') == m.get('providerName', 'DeepSeek') and response.get('model') in ['deepseek/deepseek-v4.1-flash', 'deepseek/deepseek-v4.1-flash-20260910'], 'PinnedServedModel')
            else:
                declared += [('seed', m['seed']), ('reasoning_effort', m['reasoningEffort'])]
            for key, expected in declared:
                rc(request.get(key) == expected, 'DeclaredWire:' + key)
            limit = request.get('max_tokens', request.get('max_completion_tokens'))
            rc(type(limit) is int and 1 <= limit <= m['maxTokensPerRequest'] and request.get('stream') is not True, 'OutputOrStreamingContract')
            reserve = ((len(raw) + 2048 + len(request.get('messages', []))*256)*rates['input'] + limit*rates['output'])/1e6
            rc(h.close_number(reserve, call['reservationUsd']), 'ReservationMatchesActualRequest')
            rc(response.get('usage') == call.get('usage') and response.get('model') == call.get('servedModel') and response.get('id') == call.get('requestId'), 'ResponseMetadataMatchesReceipt')
            if rate_rejection:
                error = response.get('error', {}); metadata = error.get('metadata', {})
                rc(openrouter and call.get('httpStatus') == error.get('code') == 429 and metadata.get('limit_source') == 'upstream_provider_shared_pool'
                   and metadata.get('provider_name') == m.get('providerName') and 'temporarily rate-limited upstream' in metadata.get('raw', '')
                   and not response.get('id') and not response.get('usage') and not response.get('choices'), 'ExplicitRateRejectionRaw')
                cost = 0
                rc(call.get('costBasis') == 'known_uncharged' and call.get('usdUpperBound') == call.get('accountedUpperBoundUsd') == 0, 'UnchargedRateRejection')
            else:
                cost = response['usage'].get('cost') if openrouter else h.token_cost(response['usage'], rates)
                rc(type(cost) in [int, float] and cost >= 0 and call.get('costBasis') == ('provider_reported_usd' if openrouter else 'reported_usage') and h.close_number(cost, call.get('usdUpperBound')) and h.close_number(cost, call.get('accountedUpperBoundUsd')), 'CostAccounting')
            total_cost += cost
            if not rate_rejection:
                fault = h.completion_fault(response)
                rc(call.get('completionValid') is (fault is None) and call.get('completionFault') == fault, 'CompletionContract')
            names = {x.get('function', {}).get('name') for x in request.get('tools', [])}
            rc(not names-{'submit', 'verify', 'task_tree', 'node_load'}, 'UndeclaredTool')
            if call['route'].split('/')[2] != 'F':
                rc('verify' not in names, 'FeedbackToolInUnaidedArm')
            key = (call['requestFile'], call['requestSha256'])
            rc(key not in receipt_keys, 'DuplicateReceipt')
            receipt_keys.add(key)
            by_route.setdefault(call['route'], []).append(call)
        except Exception as e:
            issues.append(type(e).__name__)
        receipts.append(evidence)
    check(not ledger.get('fatal') or ledger['fatal'] == 'spawnSync docker ETIMEDOUT', 'UnexpectedFatal')
    check(not ledger.get('captureErrors'), 'CapturedIOFailure')
    check(h.close_number(total_cost, ledger['recordedUsageUpperBoundUsd']) and h.close_number(total_cost, summary['recordedUsageUpperBoundUsd']), 'RecordedCostClosure')
    check(h.close_number(ledger['reservedUpperBoundUsd'], 0) and all(v == 0 for v in ledger['pending'].values()), 'ReservationAndPendingClosure')
    check(h.close_number(ledger['priorCampaignCostUpperBoundUsd'], m['priorCampaignCostUpperBoundUsd']), 'PriorCostMatchesManifest')
    check(ledger['capUsd'] == m['capUsd'] and ledger['priorCampaignCostUpperBoundUsd'] + total_cost <= m['capUsd'] + 1e-9, 'CumulativeBudget')
    check(len(list(store.glob('provider-*-request.json.gz'))) == len(receipts) == len(list(store.glob('provider-*-response.json.gz'))), 'RawFileReceiptCardinality')
    tasks, seen = [], set()
    for record in summary['records']:
        issues = []
        evidence = {'index': record['index'], 'benchmark': record['benchmark'], 'arm': record['arm'], 'officialId': record['officialId'], 'errors': issues}
        try:
            a, meta = h.snapshot(directory/f"task-{record['index']}.json")
            evidence['artifact'] = meta
            expected = plan_map[a['index']]
            if a['index'] in seen:
                issues.append('DuplicateTaskIndex')
            seen.add(a['index'])
            if any(a.get(k) != expected.get(k) for k in ['index', 'benchmark', 'arm', 'replica', 'officialId', 'promptSha256']):
                issues.append('TaskPlanMismatch')
            if a['promptSha256'] != public[(a['benchmark'], a['officialId'])]['promptSha256']:
                issues.append('PreselectedPromptMismatch')
            if h.sha(a['answer'].encode()) != a['candidateSha256'] or a['acceptance'].get('candidateSha256') != a['candidateSha256']:
                issues.append('FixedCandidateMismatch')
            if h.sha(h.js_json(a['trace'])) != a['traceSha256']:
                issues.append('TraceDigestMismatch')
            if any(a.get(k) != v for k, v in record.items()):
                issues.append('SummaryTaskArtifactMismatch')
            route = f"{run}/{a['benchmark']}/{a['arm']}/{a['replica']}/{a['officialId']}"
            if a['apiCalls'] != by_route.get(route, []):
                issues.append('TaskReceiptLedgerMismatch')
            accept = a['acceptance']
            if a['generationValid'] is not True or a['generationClassification'].get('valid') is not True:
                issues.append('GenerationInfrastructureInvalid')
            if accept.get('valid') is not True or type(accept.get('passed')) is not bool or accept.get('outcome') not in ['passed', 'rejected', 'budget_exhausted', 'no_candidate'] or accept['passed'] != (accept['outcome'] == 'passed'):
                issues.append('FinalAcceptanceInvalid')
            evidence.update(acceptanceOutcome=accept['outcome'], passed=accept.get('passed'))
        except Exception as e:
            issues.append(type(e).__name__)
        tasks.append(evidence)
    check(seen == set(plan_map) and summary['recordedTaskRuns'] == len(tasks) == len(plan), 'CompleteFixedTaskKeyset')
    runtime = {}
    for slug, proof in s.get('graderProvenance', {}).items():
        copied = Path(proof['runProvenanceCopy'])
        copied_bytes = copied.read_bytes()
        provenance = json.loads(copied_bytes)
        check(h.sha(copied_bytes) == proof['sha256'], 'GraderProvenanceCopy:' + slug)
        check(h.sha(Path(proof['publicArchive']['runCopy']).read_bytes()) == proof['publicArchive']['sha256'], 'PublicGraderArchive:' + slug)
        folder = copied.parent
        for stage in ['startup', 'shutdown']:
            path = folder/(stage + '-runtime-audit.json')
            if stage == 'shutdown' and deferred:
                path = Path(deferred)
            if not path.exists():
                runtime[slug + ':' + stage] = {'present': False}
                continue
            observed, meta = h.snapshot(path)
            valid = observed.get('valid') is True and observed.get('provenanceSha256') == proof['sha256'] and observed.get('containerId') == proof['actualGraderContainer']['id'] and observed.get('imageId') == proof['actualGraderContainer']['imageId']
            original = provenance['runtime_observed_imports_and_dependencies']
            expected_deps = {x['name']: {'version': x['version'], 'sha256': x['file_manifest_sha256'], 'files': len(x['files'])} for x in original['distributions']}
            actual_deps = {x['name']: {k: x[k] for k in ['version', 'sha256', 'files']} for x in observed.get('dependencyDigests', [])}
            valid = valid and actual_deps == expected_deps and observed.get('publicModules') == {k: v['sha256'] for k, v in original['public_modules'].items()} and observed.get('pythonVersion') == original['python_version'] and observed.get('mounts') == provenance['actual_grader_container']['mounts']
            runtime[slug + ':' + stage] = {'present': True, 'identityValid': valid, 'artifact': meta, 'observedAt': observed.get('observedAt')}
            check(valid, 'RuntimeIdentity:' + slug + ':' + stage)
    if deferred:
        path = Path(deferred)
        owned_root = Path('C:/Users/y1252/.codex/visualizations/2026/10/08/01a119ed-fdf7-7c32-b323-de9bab1290b6/experiment-audits')/run
        check(path.resolve().is_relative_to(owned_root.resolve()), 'DeferredAuditOwnedPath')
        invocation, invocation_meta = h.snapshot(path.parents[2]/'invocation.json')
        expected_contract = next(x['sha256'] for x in s['repairFiles'] if x['path'].endswith('/chemiq-nextwave-contract.ts'))
        check(invocation.get('valid') is True and invocation.get('run') == run and invocation.get('contractSha256') == expected_contract and invocation.get('originalSummarySha256') == inputs['summary.json']['sha256'] and invocation.get('originalLedgerSha256') == inputs['api-ledger.json']['sha256'] and invocation.get('modelCalls') == 0 and invocation.get('candidateGraderCalls') == 0 and invocation.get('originalArtifactsModified') is False and Path(invocation['runtimeAudit']).resolve() == path.resolve(), 'DeferredInvocationBinding')
        check(datetime.fromisoformat(invocation['attemptedAt'].replace('Z', '+00:00')) >= datetime.fromisoformat(summary['generatedAt'].replace('Z', '+00:00')), 'DeferredObservedAfterInterruption')
        runtime['deferredInvocation'] = {'present': True, 'identityValid': True, 'artifact': invocation_meta, 'attemptedAt': invocation['attemptedAt']}
    for name, initial in inputs.items():
        check(h.sha((directory/name).read_bytes()) == initial['sha256'], 'ArtifactChangedDuringAudit:' + name)
    receipt_bad = [x for x in receipts if x['errors']]
    task_bad = [x for x in tasks if x['errors']]
    runtime_closed = all(x.get('present') and x.get('identityValid') for x in runtime.values())
    integrity = not errors and not receipt_bad and not task_bad
    normal_close = summary['completed'] is True and not ledger.get('fatal')
    delayed_close = bool(deferred) and m['benchmarks'] == ['chemiq'] and ledger.get('fatal') == 'spawnSync docker ETIMEDOUT' and runtime_closed
    certified = integrity and runtime_closed and (normal_close or delayed_close)
    report = {'run': run, 'auditedAt': datetime.now(timezone.utc).isoformat(), 'scriptSha256': h.sha(Path(__file__).read_bytes()), 'helperScriptSha256': h.sha((HERE/'full-gpqa-inflight-audit.py').read_bytes()), 'scope': 'Stored evidence only; no model/grader/parser execution; original campaign artifacts unchanged', 'originalCampaignCompleted': summary['completed'], 'originalFatal': ledger.get('fatal'), 'deferredRuntimeAudit': str(deferred) if deferred else None, 'deferredClosingIdentityEvidence': delayed_close, 'limitation': 'A deferred runtime check records its later observation time; it does not rewrite or claim success at the original failed shutdown boundary. Current provider checkpoint and historical protocol equality are not certified.', 'integrityValid': integrity, 'scoreCertificateValid': certified, 'taskRuns': len(tasks), 'plannedTaskRuns': len(plan), 'providerCalls': len(receipts), 'usdUpperBound': total_cost, 'errors': errors, 'receiptErrors': receipt_bad, 'taskErrors': task_bad, 'runtime': runtime, 'source': source, 'inputArtifacts': inputs, 'receiptChecks': receipts, 'taskChecks': tasks}
    path = directory/('independent-deferred-closing-audit.json' if deferred else 'independent-closing-audit.json')
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['run', 'originalCampaignCompleted', 'originalFatal', 'integrityValid', 'scoreCertificateValid', 'taskRuns', 'plannedTaskRuns', 'providerCalls', 'usdUpperBound', 'errors']} | {'receiptErrors': len(receipt_bad), 'taskErrors': len(task_bad), 'audit': str(path)}))
    return certified


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--run', required=True)
    p.add_argument('--deferred-shutdown')
    args = p.parse_args()
    raise SystemExit(0 if audit(args.run, args.deferred_shutdown) else 1)
