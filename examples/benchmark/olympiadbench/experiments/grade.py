"""Private subprocess entry. Uses pinned official extraction and MathJudger, no model."""
from pathlib import Path
import ast
import contextlib
import importlib.util
import io
import json
import re
import sys

VENDOR = Path(__file__).resolve().parent / 'vendor'

def load_official():
    spec = importlib.util.spec_from_file_location('olympiad_official_math_judger', VENDOR/'math_judger.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tree = ast.parse((VENDOR/'judge.py').read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'extract_answer')
    scope = {'re': re}
    exec(compile(ast.Module(body=[function], type_ignores=[]), 'official_extract_answer', 'exec'), scope)
    return module.MathJudger, scope['extract_answer']

def judge(candidate, row):
    if not isinstance(candidate, str):
        raise TypeError('InvalidCandidateType')
    if not candidate.strip():
        return False, ''
    cls, extract = load_official()
    extracted = extract(False, candidate, False)
    scorer = cls()
    # Deliberately identical order and tolerance dispatch to the upstream entry.
    if 'Tuple' in row['answer_type'] or not row.get('error'):
        passed = scorer.judge(extracted, row['final_answer'][0])
    elif ',' in row['error']:
        passed = scorer.judge(extracted, row['final_answer'][0], [float(x) if x else 1e-8 for x in row['error'].split(',')])
    else:
        passed = scorer.judge(extracted, row['final_answer'][0], float(row['error']))
    return bool(passed), extracted

if __name__ == '__main__':
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (10, 11))
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    data = json.load(sys.stdin)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            passed, extracted = judge(data['candidate'], data['row'])
        print(json.dumps({'valid': True, 'passed': passed, 'extracted': extracted}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({'valid': False, 'errorType': type(e).__name__, 'error': str(e)[:500]}))
