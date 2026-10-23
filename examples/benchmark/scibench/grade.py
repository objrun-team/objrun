"""Pinned SciBench numeric scoring; no model client and no candidate execution."""
import ast
import contextlib
import hashlib
import io
import math
import re
from pathlib import Path


def official_functions(vendor):
    scope = {}
    for filename, names in [('post_process.py', None), ('eval_zero.py', {'equiv'})]:
        tree = ast.parse((Path(vendor) / filename).read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.Import)) and
                 (isinstance(n, ast.FunctionDef) and (names is None or n.name in names) or
                  isinstance(n, ast.Import) and all(a.name in {'re', 'json', 'math'} for a in n.names))]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, 'exec'), scope)
    return scope


class Scorer:
    def __init__(self, vendor):
        self.f = official_functions(vendor)

    def public(self, row):
        unit = self.f['remove_not'](row['unit']) or row['unit']
        return {'id': row['id'], 'source': row['sourceFile'],
                'prompt': row['problem_text'] + ' The unit of the answer is ' + unit + '.'}

    def target(self, row):
        unit = self.f['remove_not'](row['unit']) or row['unit']
        answer = row['answer_number']
        if unit != row['unit']:
            with contextlib.redirect_stdout(io.StringIO()):
                answer = self.f['cal_not']((answer, row['unit']))
        if not isinstance(answer, str) or not math.isfinite(float(answer)):
            raise ValueError('InvalidReferenceNumber')
        return answer, unit

    def judge(self, text, row):
        if not isinstance(text, str):
            raise TypeError('InvalidCandidateType')
        target, unit = self.target(row)
        value = self.f['parse_math_answer'](text)
        if unit != row['unit']:
            with contextlib.redirect_stdout(io.StringIO()):
                value = self.f['cal_not'](self.f['parse_not'](value))
        parsed = False
        if isinstance(value, str):
            cleaned = value.replace(',', '').strip()
            for part in [cleaned, cleaned.split()[0] if cleaned.split() else '']:
                try:
                    if math.isfinite(float(part)):
                        parsed = True
                except (ValueError, OverflowError):
                    pass
        passed = bool(parsed and self.f['equiv'](value, target, row['unit']))
        return {'valid': True, 'passed': passed, 'parsed': parsed,
                'outcome': 'passed' if passed else 'rejected',
                'candidateSha256': hashlib.sha256(text.encode()).hexdigest()}

    def reference_candidate(self, row):
        target, unit = self.target(row)
        if unit != row['unit']:
            exponent = re.search(r'10\^\{?\s*(-?\d+)\s*\}?', row['unit']).group(1)
            return r'\boxed{' + row['answer_number'] + r'\times 10^{' + exponent + '}}'
        return r'\boxed{' + target + '}'
