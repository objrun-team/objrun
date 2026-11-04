"""Audit a completed four-arm run before opening the full-suite gate."""
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = (Path(__file__).resolve().parents[4] / 'scripts')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def audit(run):
    out = ROOT / 'outputs' / run
    config = read(out / 'frozen-config.json')
    catalog = [t for t in read(ROOT / 'data/catalog.json') if t['id'] in config['taskIds']]
    errors = []
    for manifest_path in [out / 'source-pins.json', ROOT / 'data/engine-origin.json']:
        for p in read(manifest_path)['files']:
            file = Path(p['path']) if manifest_path.name == 'source-pins.json' else ROOT / 'package' / p['path']
            if hashlib.sha256(file.read_bytes()).hexdigest() != p['sha256']:
                errors.append('SourceChanged:' + str(file))
    identities = {}
    for p in (ROOT / 'outputs/snapshots').glob('*/*/manifest.json'):
        m = read(p)
        identities[m['candidate']] = (p, m)
    summary = {}
    missing_candidates = 0
    for arm in config['arms']:
        rows = []
        for task in catalog:
            path = out / 'results' / arm / (task['id'] + '.json')
            if not path.exists():
                errors.append('MissingResult:' + arm + ':' + task['id'])
                continue
            row = read(path)
            rows.append(row)
            if not row['valid']:
                errors.append('InfrastructureException:' + arm + ':' + task['id'])
                continue
            directory = out / 'tasks' / arm / task['id']
            rounds = read(directory / 'rounds.json')
            if not 1 <= len(rounds) <= (1 if arm in {'baseline', 'objrun'} else 5):
                errors.append('RoundLimit:' + arm + ':' + task['id'])
            if any(r['passed'] for r in rounds[:-1]):
                errors.append('FailedEarlyStop:' + arm + ':' + task['id'])
            sessions = [r['session'] for r in rounds]
            if arm == 'independent' and len(set(sessions)) != len(sessions):
                errors.append('IndependentEnvironmentReused:' + task['id'])
            if arm == 'binary' and len(set(sessions)) != 1:
                errors.append('BinaryEnvironmentNotRetained:' + task['id'])
            for r in rounds:
                if [u['id'] for u in r['units']] != [u['id'] for u in task['units']]:
                    errors.append('UnitIdentityMismatch:' + arm + ':' + task['id'])
                for u in r['units']:
                    if not u['grade']['valid'] or u['grade']['candidate'] != u['candidate']:
                        errors.append('GradeBindingMismatch:' + u['id'])
                    candidate = u['candidate']
                    if candidate not in identities:
                        missing_candidates += 1
                        if u['grade']['passed']:
                            errors.append('PassedWithoutFrozenCandidate:' + u['id'])
                    else:
                        p, manifest = identities[candidate]
                        if not candidate.startswith(r['session'] + ':'):
                            errors.append('CandidateSessionMismatch:' + u['id'])
                        for f in manifest['files']:
                            file = p.parent / 'output' / f['path']
                            if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest() != f['sha256']:
                                errors.append('ArtifactChanged:' + str(file))
                for message_file in (directory / ('round-' + str(r['round']))).glob('*/messages.json'):
                    messages = read(message_file)
                    if arm == 'independent':
                        if any(m['role'] == 'user' and m.get('content') in {'passed', 'failed'} for m in messages):
                            errors.append('IndependentFeedbackLeak:' + task['id'])
                        identifiers = re.findall(r'tpe-[a-f0-9]{16}:[a-f0-9]{64}', json.dumps(messages))
                        if any(not identity.startswith(r['session'] + ':') for identity in identifiers):
                            errors.append('IndependentHistoryLeak:' + task['id'])
            if row['units'] != rounds[-1]['units']:
                errors.append('FinalRoundSelectionMismatch:' + arm + ':' + task['id'])
        summary[arm] = {'parents': len(rows), 'valid': sum(bool(r['valid']) for r in rows),
                        'units': sum(len(r['units']) for r in rows),
                        'passedUnits': sum(u.get('grade', {}).get('valid', False) and u.get('grade', {}).get('passed', False) for r in rows for u in r['units']),
                        'knownCostUsd': sum(r.get('actualCostUsd', 0) for r in rows),
                        'unknownCostCount': sum(r.get('unknownCostCount', 0) for r in rows)}
    for p in (out / 'calls').rglob('request.json'):
        req = read(p)
        if not (req['model'] == config['model'] and req['temperature'] == 0 and req['max_tokens'] == 16384 and req['provider']['only'] == ['digitalocean'] and req['provider']['allow_fallbacks'] is False and req['reasoning']['effort'] == 'high'):
            errors.append('ProviderWireMismatch:' + str(p))
    for p in (out / 'tasks/objrun').rglob('feedback.json'):
        for f in read(p):
            if f['node'] == 'correct' and f['exposed']['note'] != '':
                errors.append('PrivateCorrectnessDetailExposed:' + str(p))
            if set(f['exposed']) != {'value', 'note'} or not isinstance(f['exposed']['value'], bool):
                errors.append('InvalidFeedbackShape:' + str(p))
    result = {'passed': not errors, 'run': run, 'parents': len(catalog), 'scientific_units': sum(len(t['units']) for t in catalog),
              'summary': summary, 'invalid_or_missing_submissions': missing_candidates, 'errors': errors,
              'scope': 'Realistic automatic-only; no cost matching; scientific failure does not fail infrastructure acceptance'}
    (out / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
    lines = ['# TheoPhysEval ' + run, '', '状态：' + ('核验通过' if result['passed'] else '需要处理异常'), '',
             '| 组别 | 有效任务 | 科学问题 | 通过 | 已知费用 USD | 未知费用笔数 |', '|---|---:|---:|---:|---:|---:|']
    for arm, s in summary.items():
        lines.append(f"| {arm} | {s['valid']}/{len(catalog)} | {s['units']} | {s['passedUnits']} | {s['knownCostUsd']:.9f} | {s['unknownCostCount']} |")
    lines += ['', '费用及调用量未对齐；四阶段按原顺序运行。人工题 autonomous-de 排除。', '', '评分及接口异常不作为模型答错。', '', '核验异常：' + json.dumps(errors, ensure_ascii=False)]
    (out / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = audit(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 1)
