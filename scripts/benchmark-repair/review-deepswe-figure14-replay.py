"""Read fixed Figure14 artifacts and AST; never exec the original producer.

Run with the stored replay's CPython 3.13 parser: ast.dump is version-sensitive.
New evidence is written only under this F project's docs directory, with xb.
"""
from pathlib import Path
import ast
import csv
import datetime
import hashlib
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs/repair-2026-10-08'
BASE = DOCS / 'deepswe-figure14-data-replay-43ae37adfedf4e7fb0c68c42e7337c48'
OUT_JSON = DOCS / 'deepswe-figure14-data-replay-independent-review.json'
OUT_MD = DOCS / 'deepswe-figure14-data-replay-independent-review.md'


def pin(path):
    path = Path(path)
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def verify(value):
    actual = pin(value['path'])
    assert actual == value, (actual, value)
    return actual


def rows(path):
    with path.open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


def new_file(path, raw):
    assert path.is_relative_to(ROOT) and path.drive.upper() == 'F:'
    with path.open('xb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    assert path.read_bytes() == raw
    return pin(path)


def main():
    assert not OUT_JSON.exists() and not OUT_MD.exists()
    assert sys.version_info[:2] == (3, 13), 'Use the stored replay CPython3.13 AST formatting; do not execute producer.'
    report_pin = pin(BASE / 'replay.json')
    assert report_pin['bytes'] == 10270 and report_pin['sha256'] == '236a0869822b8b9b76e6a4645a9c72a563d31363b2d28ec1d6cc02cdd1f9f4b9'
    report = json.loads((BASE / 'replay.json').read_bytes())
    assert report['inputPins'] == report['inputPinsAfter']
    before = [verify(value) for value in report['inputPins']]
    outputs = [verify(value) for value in report['outputPins']]
    replay_script = verify(report['scriptPin'])

    producer = ROOT / 'latex/reports/monkeys-2026-09-29/scripts/data-producers/14-dsw-verdict-content-data.py'
    tree = ast.parse(producer.read_text(encoding='utf-8'))
    selected, adaptations, cut = [], [], None
    for node in tree.body:
        if isinstance(node, ast.Import) and any(value.name == 'matplotlib.patheffects' for value in node.names):
            cut = node.lineno
            break
        if isinstance(node, ast.Import) and any(value.name.startswith(('style', 'numpy', 'matplotlib')) for value in node.names):
            adaptations.append({'line': node.lineno, 'action': 'omit graphics-only import'})
            continue
        if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('matplotlib'):
            adaptations.append({'line': node.lineno, 'action': 'omit graphics-only import'})
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and ast.unparse(node.value.func) in ['sys.path.insert', 'S.apply']:
            adaptations.append({'line': node.lineno, 'action': 'omit graphics import path/style initialization'})
            continue
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in ['EXP', 'OLD'] for target in node.targets):
            name = node.targets[0].id
            path = ROOT / '.local-evidence/repository/examples/benchmark/dsw-full-export/csv' if name == 'EXP' else ROOT / 'latex/data'
            node.value = ast.Constant(str(path))
            adaptations.append({'line': node.lineno, 'action': 'bind existing project mirror read path', 'variable': name, 'path': str(path)})
        selected.append(node)
    module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    selection_sha = hashlib.sha256(ast.dump(module).encode()).hexdigest()
    assert selection_sha == report['originalProducerAstSelectionSha256']
    assert adaptations == report['explicitPathAndGraphicsAdaptations']
    assert max(node.end_lineno for node in selected) == 252 and cut == 256
    assert_lines = sorted(node.lineno for node in ast.walk(module) if isinstance(node, ast.Assert))
    np_names = [node.lineno for node in ast.walk(module) if isinstance(node, ast.Name) and node.id == 'np']
    assert not np_names

    stored = ROOT / 'latex/reports/monkeys-2026-09-29/data'
    comparisons = {
        'figureCsvExactParsedRows': rows(BASE / 'data/14-dsw-verdict-content.csv') == rows(stored / '14-dsw-verdict-content.csv'),
        'figureJsonExactValue': json.loads((BASE / 'data/14-dsw-verdict-content.json').read_bytes()) == json.loads((stored / '14-dsw-verdict-content.json').read_bytes()),
        'transitionsCsvExactParsedRows': rows(BASE / 'data/14-dsw-verdict-content-transitions.csv') == rows(stored / '14-dsw-verdict-content-transitions.csv'),
    }
    assert comparisons == report['comparisons'] and all(comparisons.values())
    tasks = rows(ROOT / '.local-evidence/repository/examples/benchmark/dsw-full-export/csv/tasks.csv')
    checks = rows(ROOT / '.local-evidence/repository/examples/benchmark/dsw-full-export/csv/checks.csv')
    task_map = {value['task']: value['pass'] for value in tasks}
    assert len(task_map) == 112 and sum(value == '1' for value in task_map.values()) == 91 and len(checks) == 642
    stdout_pin = pin(BASE / 'producer.stdout.log')
    assert stdout_pin['sha256'] == report['producerStdoutSha256']
    after = [verify(value) for value in report['inputPins']]
    result = {
        'protocol': 'deepswe-figure14-independent-static-review-v1',
        'atUtc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'validated': True, 'scoreCertificateValid': False, 'oldRuntimeCertified': False,
        'rootReplay': report_pin, 'rootReplayScript': replay_script,
        'inputPins': before, 'inputsUnchangedAfterReview': before == after,
        'outputPins': outputs, 'stdoutPin': stdout_pin,
        'astSelection': {
            'originalProducerPin': pin(producer), 'reconstructedAstSha256': selection_sha,
            'lastOriginalExecutedLine': 252, 'firstGraphicsBoundaryLine': 256,
            'allSelectedAssertLines': assert_lines, 'assertCount': len(assert_lines),
            'numpyNameLoadsInSelectedAst': np_names, 'adaptationsExactlyMatchReport': True,
            'adaptations': adaptations, 'reviewerExecCompileOrProducerRun': False,
        },
        'comparisons': comparisons,
        'preservedDataCounts': {
            'taskRows': len(tasks), 'distinctTaskKeys': len(task_map),
            'storedPassCount': sum(value == '1' for value in task_map.values()),
            'checkRows': len(checks), 'transitionRows': len(rows(BASE / 'data/14-dsw-verdict-content-transitions.csv')),
            'rootRecordedAcceptedNextChecks': report['acceptedNextChecks'],
            'rootRecordedTasksWithTransitions': report['tasksWithTransitions'],
        },
        'runtimeEvidence': {
            'rootReportPython': report['python'], 'rootReportScipyVersion': report['scipyVersion'],
            'numpyVersionNotRecordedInReplayJson': True, 'reviewAstParserVersion': sys.version.split()[0],
            'independentScipyNumpyPackageProbeRun': False, 'historicalInterpreterEnvironmentCertified': False,
        },
        'firstStaticReviewAttempt': {
            'exitCode': 1, 'fileWrites': 0, 'producerExecutions': 0,
            'reason': 'CPython3.12.7 ast.dump includes empty fields; CPython3.13.5 omits them by default. Hash representation differs while original source and selected statements remain the same.',
            'python312AstDumpSha256': 'cc72a163659235669533cdef884d87bd2d2b536992e51bc78f29675f51561441',
            'python313AstDumpSha256': 'e289083bdf09d9a7a18097e1abc55452e8d9dc01991f563763797542ec49f201',
            'bothDiagnosticsUsedAstParsingOnly': True,
        },
        'conclusion': 'The preserved CSV/.dat/figure-data relation is reproducible with original computation and assertions retained through line252. Three stored/replayed data objects match under the stated parsed-row/JSON-value comparisons. This does not prove 91 historical official graders, historical system identity, original scorer/environment, or the 113-versus112 task discrepancy.',
        'remaining': [
            'Historical grader/run/image/version and trace provenance still need independent evidence.',
            'Task table stores112 distinct keys and91 pass flags; this data-producer consistency does not resolve a paper claim with113 denominator.',
            'Figure PNG/PDF Pins were checked for unchanged bytes; no visual rendering or figure validity review was performed.',
            'The original Anaconda ABI failure and successful auto_paper runtime are separate root evidence. This review does not replace the historical failure or infer the missing NumPy version.',
            'The stored AST hash depends on CPython AST dump formatting; compare with the recorded3.13 parser or an explicitly reviewed canonical representation.',
        ],
        'scope': {
            'FOnlyNewReportWrites': True, 'producerReruns': 0, 'gradingCalls': 0,
            'modelCalls': 0, 'networkQueries': 0, 'DockerOperations': 0,
            'originalFileWrites': 0, 'manuscriptWrites': 0, 'CDEWrites': 0,
        },
        'reviewerScript': pin(Path(__file__)),
    }
    json_pin = new_file(OUT_JSON, (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    text = ('Independent static review passed: original data calculations and assertions are retained through line 252; graphics from line 256 onward were not executed. Only style/graphics initialization and EXP/OLD mirror-path adaptations differ. Three CSV/JSON/conversion tables match exactly under the declared parsed-row/JSON-value comparison; 14 original input/figure-output pins and the original replay-script pin all currently match.\n\n'
            'This review did not rerun the producer, plot, grade, call APIs, or modify the paper. Saved tables contain 112 distinct task keys, 91 pass flags, and 642 checks. This consistency does not certify 91 historical grades or resolve the 113/112 denominator and old system/environment provenance. The report records Py3.13.5 and SciPy1.16.1 but no NumPy version; no additional probes of those packages were run.\n\n'
            'The first static AST check failed on Py3.12.7 because ast.dump retains empty fields. Using 3.13.5, matching the report, for AST parsing only reproduced e289083b… exactly without repeating the original calculation. This version dependency and failure are retained in independent JSON.\n\n'
            '[Independent JSON](' + str(OUT_JSON).replace(chr(92), '/') + '), SHA `' + json_pin['sha256'] + '`. Financial-abort review still takes priority while awaiting the final source pin.\n')
    md_pin = new_file(OUT_MD, text.encode('utf-8'))
    print(json.dumps({'outputs': [json_pin, md_pin], 'validated': True, 'scoreCertificateValid': False, 'comparisons': comparisons, 'assertCount': len(assert_lines)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
