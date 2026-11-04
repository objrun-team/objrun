"""Offline positive, negative and protocol controls; never call a model."""
import copy
import json
from pathlib import Path
import tempfile
from fractions import Fraction
from grade import evaluate, load_runtime

ROOT = (Path(__file__).resolve().parents[4] / 'scripts')


def reference(spec):
    if spec['kind'] == 'numeric':
        return spec['answer']
    lines = [line for line in spec['template'].splitlines() if line.strip()]
    for field in spec['fields']:
        lines[field['line_index']] += ' ' + field['answer']
    return '\n'.join(lines) + '\n'


def main():
    catalog = json.loads((ROOT / 'data/catalog.json').read_text())
    checks = []
    for task in catalog:
        for unit in task['units']:
            private = ROOT / 'data/private'
            spec = json.loads((private / unit['id'] / 'grading_spec.json').read_text())
            with tempfile.TemporaryDirectory(prefix='theophyseval-control-') as td:
                output = Path(td)
                answer = output / unit['answer_path']
                answer.parent.mkdir(parents=True, exist_ok=True)
                good = reference(spec)
                answer.write_text(good)
                positive = evaluate(private, unit, output)
                assert positive.get('valid') and positive.get('parsed') and positive.get('passed'), unit['id'] + ':positive_G'
                answer.write_text('UNPARSEABLE_NOT_A_SCIENTIFIC_ANSWER')
                negative = evaluate(private, unit, output)
                assert negative.get('valid') and not negative.get('passed'), unit['id'] + ':negative'
                answer.unlink()
                missing = evaluate(private, unit, output)
                assert missing.get('valid') and not missing.get('passed'), unit['id'] + ':missing'
                numeric_wrong = None
                if spec['kind'] == 'numeric':
                    actual = load_runtime(private / unit['id']).parse_number_tree(good)
                    def perturb(x):
                        return [perturb(v) for v in x] if isinstance(x, list) else float(x) + 1e100
                    answer.write_text(json.dumps(perturb(actual)))
                    numeric_wrong = evaluate(private, unit, output)
                    assert numeric_wrong.get('valid') and not numeric_wrong.get('passed'), unit['id'] + ':numeric_wrong'
                for verdict in [positive, negative, missing, numeric_wrong]:
                    if verdict is not None:
                        assert set(verdict) <= {'valid', 'outcome', 'parsed', 'passed'}
                checks.append({'unit': unit['id'], 'positive': True, 'malformed': True, 'missing': True,
                               'wrong_numeric': numeric_wrong is not None, 'sanitized': True})
    runtime = load_runtime(ROOT / 'data/private' / catalog[0]['units'][0]['id'])
    runtime.compare(Fraction('1.1'), Fraction('1'), Fraction('.1'), Fraction('0'))
    try:
        runtime.compare(Fraction('1.100000001'), Fraction('1'), Fraction('.1'), Fraction('0'))
        raise RuntimeError('ToleranceBoundaryControlFailed')
    except AssertionError:
        pass
    out = ROOT / 'control'
    out.mkdir(exist_ok=True)
    result = {'passed': True, 'units': len(checks), 'parents': len(catalog), 'checks': checks,
              'tolerance_boundary': True, 'manual_excluded': all(t['id'] != 'autonomous-de' for t in catalog)}
    (out / 'grading-controls.json').write_text(json.dumps(result, indent=2) + '\n')
    for task_id in ['dispersion-pi-series', 'iib-euclidean-wormholes']:
        task = next(t for t in catalog if t['id'] == task_id)
        unit = task['units'][0]
        spec = json.loads((ROOT / 'data/private' / unit['id'] / 'grading_spec.json').read_text())
        answer_text = spec['alternative_answers'][0] if 'alternative_answers' in spec else json.dumps([2 * float(v) for v in json.loads(spec['answer'])])
        with tempfile.TemporaryDirectory(prefix='theophyseval-special-') as td:
            path = Path(td) / unit['answer_path']
            path.write_text(answer_text)
            assert evaluate(ROOT / 'data/private', unit, Path(td))['passed'], task_id
    (out / 'special-grading-controls.json').write_text(json.dumps({'passed': True, 'alternate_convention': True, 'common_positive_scale': True}, indent=2) + '\n')
    print(json.dumps({'passed': True, 'units': len(checks), 'parents': len(catalog), 'control_file': str(out / 'grading-controls.json')}))


if __name__ == '__main__':
    main()
