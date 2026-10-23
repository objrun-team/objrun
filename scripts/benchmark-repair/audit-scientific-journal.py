"""Extra journal/source/offset audit; original scientific auditor remains mandatory and unmodified."""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import re
import subprocess
import os

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sha = lambda raw: hashlib.sha256(raw).hexdigest()
def file_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()
def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate_json_key')
        value[key] = item
    return value

def strict_json(raw):
    return json.loads(raw, object_pairs_hook=unique_object,
                      parse_constant=lambda _value: (_ for _ in ()).throw(ValueError('nonfinite_json_number')))

def javascript_canonical(path, command, check):
    # One bounded streaming ECMAScript process; never Python's distinct float spelling.
    child = subprocess.run([*command, str(path)], capture_output=True, timeout=180)
    check(child.returncode == 0, 'canonicalEvent')
    if child.returncode:
        return None
    result = strict_json(child.stdout)
    check(result.get('valid') is True and result.get('fileSha256') == file_sha(path), 'canonicalByteBinding')
    return result

def journal_offsets(path, config_raw, check, canonical_command):
    offsets = {}
    cursor = lines = 0
    previous = sha(config_raw)
    protocol = strict_json(config_raw)['protocol']
    check(protocol in ('campaign-api-journal-v1', 'campaign-api-journal-openrouter-v1'), 'configProtocol')
    canonical = javascript_canonical(path, canonical_command, check)
    starts = set()
    with path.open('rb') as source:
        for raw in source:
            check(raw.endswith(b'\n') and len(raw) <= 65536, 'truncatedOrOversizeEvent')
            event = strict_json(raw)
            check(set(event) == {'protocol', 'eventSeq', 'previousEventSha256', 'kind', 'requestSeq', 'record'}, 'eventSchema')
            check(event['protocol'] == protocol and type(event['eventSeq']) is int and event['eventSeq'] == lines, 'eventSequence')
            check(event['previousEventSha256'] == previous, 'previousEventSha256')
            check(type(event['requestSeq']) is int and event['requestSeq'] >= 0, 'requestSequenceType')
            seq = event['requestSeq']
            previous = sha(raw)
            if event['kind'] == 'start':
                check(seq not in starts and seq == len(starts), 'duplicateOrUnorderedStart')
                starts.add(seq)
            if event['kind'] == 'finish':
                check(seq in starts and seq not in offsets, 'duplicateOrUnknownFinish')
                offsets[seq] = {'callId': seq, 'finishOffset': cursor, 'finishEnd': cursor + len(raw), 'finishLineSha256': sha(raw)}
            check(event['kind'] in ('start', 'finish'), 'eventKind')
            cursor += len(raw); lines += 1
    if canonical is not None:
        check(canonical['bytes'] == cursor and canonical['eventCount'] == lines, 'canonicalPrefixBinding')
    return offsets, {'bytes': cursor, 'eventCount': lines, 'lastSha256': previous}

def audit(run, invoke_original=True, provisional=False, fixture_root=None):
    if not re.fullmatch(r'repair-[0-9TZ-]+', run):
        raise ValueError('invalid campaign')
    use_root = ROOT
    if fixture_root is not None:
        use_root = pathlib.Path(fixture_root).resolve()
        if use_root.parent != ROOT / '.scratch' or not use_root.name.startswith('scientific-native-four-engine-'):
            raise ValueError('strict_F_native_fixture_root_required')
    meta = use_root / 'docs/repair-2026-10-08/campaigns' / run
    store = use_root / '.phase1-data/repair' / run
    manifest = json.loads((meta / 'manifest.json').read_text())
    config = json.loads((store / 'journal-config.json').read_text())
    checkpoint = json.loads((store / 'api-state.json').read_text())
    ledger = json.loads((meta / 'api-ledger.json').read_text())
    exported = json.loads((meta / 'journal-export.json').read_text())
    summary = json.loads((meta / 'summary.json').read_text())
    errors = []
    check = lambda ok, name: errors.append(name) if not ok else None
    if fixture_root is not None:
        check(manifest['mode'] == 'native-local-mock-fixture' and manifest['providerKind'] == 'local-mock' and len(manifest['taskSchedule']) == 4, 'nativeFixtureScope')
    check(summary.get('completed') is (not provisional), 'completionPhase')
    check(manifest['statusEndpoint'] == '/tasks/:id/status', 'statusEndpoint')
    check(config['campaign'] == manifest['campaign'] == ledger['campaign'] == run, 'campaign')
    check(config['capUsd'] == manifest['capUsd'] == ledger['capUsd'], 'cap')
    check(config['priorCampaignCostUpperBoundUsd'] == manifest['priorCampaignCostUpperBoundUsd'] == ledger['priorCampaignCostUpperBoundUsd'], 'prior')
    check(checkpoint.get('error') is None and not (store / 'journal-error.json').exists(), 'poison')
    check(checkpoint['reservedUpperBoundUsd'] == 0 and not any(checkpoint['pending'].values()) and checkpoint['acceptedRequestCount'] == checkpoint['finishedRequestCount'] == len(ledger['calls']), 'closed')
    check(exported['sha256'] == sha((meta / 'api-ledger.json').read_bytes()) and exported['accountingClosed'] is True and exported['eligibleForScoreCertification'] is True, 'legacyExport')
    runtime = manifest['hostExecutors']['bun']
    runtime_path = pathlib.Path(runtime['path'])
    check(runtime_path.is_absolute() and runtime_path.is_file() and file_sha(runtime_path) == runtime['sha256'], 'canonicalRuntimePin')
    offsets, prefix = journal_offsets(store / 'api-events.jsonl', (store / 'journal-config.json').read_bytes(), check,
                                     [str(runtime_path), str(HERE / 'audit-journal-canonical.ts')])
    check(exported['durablePrefix'] == checkpoint['durablePrefix'], 'exportPrefix')
    check(checkpoint['durablePrefix'] == prefix, 'checkpointPrefix')
    seen = set()
    for record in summary['records']:
        task = json.loads((meta / f"task-{record['index']}.json").read_text())
        refs = task['journalRefs']
        check(len(task['callIds']) == len(refs) == len(task['apiCalls']), 'taskCallRefs')
        for seq, reference in zip(task['callIds'], refs):
            check(seq in offsets and reference == offsets.get(seq) and seq not in seen, 'offsetBinding')
            if type(seq) is int and 0 <= seq < len(ledger['calls']):
                check(ledger['calls'][seq] in task['apiCalls'], 'taskLedgerReceipt')
            else:
                errors.append('callIdRange')
            seen.add(seq)
    check(seen == set(range(len(ledger['calls']))), 'receiptSetComplete')
    closure = json.loads((meta / 'worker-closure.json').read_text())
    check(closure['activeEngines'] == 0 and all(x['status'] == 'fulfilled' for x in closure['allSettled']) and all(x['stopReturned'] is True for x in closure['workerClosures']), 'workersClosed')
    check(closure['proxy']['activeHandlers'] == 0, 'transportsClosed')
    cash = json.loads((meta / 'paid-resource-closure.json').read_text())
    check(cash.get('valid') is True and cash.get('accountingClosed') is True, 'cashClosed')
    original_ok = False
    original_integrity = False
    if invoke_original:
        spec = importlib.util.spec_from_file_location('unmodified_scientific_auditor', HERE / 'audit-scientific-campaign.py')
        original = importlib.util.module_from_spec(spec); spec.loader.exec_module(original)
        if fixture_root is not None:
            # Only the fixture evidence location changes. All original source/raw/provider/task assertions remain intact.
            original.ROOT = use_root; original.DOCS = use_root / 'docs/repair-2026-10-08'
        original_ok = original.audit(run)  # No weakened source/provider/G/task assertions.
        original_report = strict_json((meta / 'independent-closing-audit.json').read_bytes())
        original_integrity = original_report.get('integrityValid') is True and all(value.get('present') and value.get('identityValid') for value in original_report['runtime'].values())
        check(original_integrity if provisional else original_ok, 'originalIntegrityAudit' if provisional else 'originalClosingAudit')
    inputs = [{ 'path': str(meta / name), 'bytes': (meta / name).stat().st_size, 'sha256': file_sha(meta / name) }
              for name in ('manifest.json', 'source.json', 'frozen-source.json', 'summary.json', 'api-ledger.json', 'journal-export.json', 'worker-closure.json', 'paid-resource-closure.json', 'independent-closing-audit.json')]
    result = {'campaign': run, 'phase': 'provisional_integrity' if provisional else 'final', 'integrityValid': not errors,
              'scoreCertificateValid': not provisional and not errors and original_ok and manifest.get('providerKind') == 'real-provider',
              'providerKind': manifest.get('providerKind'),
              'localMockIntegrityCertified': fixture_root is not None and not provisional and not errors and original_ok,
              'formalResultsCertified': fixture_root is None and not provisional and not errors and original_ok and manifest.get('providerKind') == 'real-provider',
              'errors': errors, 'offsetsVerified': len(offsets), 'providerCalls': len(ledger['calls']),
              'originalAuditorRequired': True, 'originalIntegrityValid': original_integrity, 'inputArtifacts': inputs,
              'journalFileSha256': file_sha(store / 'api-events.jsonl'), 'journalPrefix': prefix,
              'scriptSha256': sha(pathlib.Path(__file__).read_bytes()), 'modelCalls': 0}
    with (meta / 'independent-journal-closing-audit.json').open('wb') as output:
        output.write((json.dumps(result, indent=2) + '\n').encode()); output.flush(); os.fsync(output.fileno())
    return result

if __name__ == '__main__':
    args = argparse.ArgumentParser(); args.add_argument('--run', required=True); args.add_argument('--provisional', action='store_true'); args.add_argument('--fixture-root'); args.add_argument('--fixture-integrity', action='store_true')
    args = args.parse_args()
    if args.fixture_integrity != bool(args.fixture_root):
        raise ValueError('explicit_fixture_scope_pair_required')
    result = audit(args.run, provisional=args.provisional, fixture_root=args.fixture_root)
    print(json.dumps(result))
    raise SystemExit(0 if (result['integrityValid'] if args.provisional else result['localMockIntegrityCertified'] if args.fixture_integrity else result['scoreCertificateValid']) else 1)
