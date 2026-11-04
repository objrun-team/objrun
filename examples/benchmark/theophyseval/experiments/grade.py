"""Private grader: preserve upstream decisions, expose no target or residual."""
import hashlib
import importlib.util
import json
from pathlib import Path


def load_runtime(directory):
    path = Path(directory) / 'grader_runtime.py'
    module = importlib.util.module_from_spec(spec := importlib.util.spec_from_file_location('theophyseval_official_' + hashlib.sha256(str(path).encode()).hexdigest(), path))
    spec.loader.exec_module(module)
    return module


def evaluate(private, unit, output):
    directory = Path(private) / unit['id']
    try:
        spec = json.loads((directory / 'grading_spec.json').read_text())
        if spec['kind'] not in {'numeric', 'sheet'}:
            raise RuntimeError('AutomaticScopeMismatch')
        runtime = load_runtime(directory)
    except Exception as exc:
        return {'valid': False, 'outcome': 'grader_error', 'errorType': type(exc).__name__}
    answer = Path(output) / unit['answer_path']
    parsed = False
    try:
        text = runtime.read_answer(answer)
        if spec['kind'] == 'numeric':
            runtime.parse_number_tree(text)
        else:
            # Only public template labels and syntactic value categories are used here.
            lines = [' '.join(line.split()) for line in text.splitlines() if line.strip()]
            template = [' '.join(line.split()) for line in spec['template'].splitlines() if line.strip()]
            assert len(lines) == len(template)
            fields = {field['line_index'] for field in spec['fields']}
            for index, (line, original) in enumerate(zip(lines, template)):
                if index not in fields:
                    assert line == original
                    continue
                assert line.startswith(original + ' ')
                value = line[len(original):].strip().removeprefix('=').strip()
                if value not in {'NONE', 'YES', 'NO'}:
                    runtime.parse_number_tree('[' + value + ']' if 'poles_' in original else value)
        parsed = True
    except (AssertionError, UnicodeError, OSError):
        pass
    try:
        runtime.grade(spec, Path(output))
        passed = True
    except AssertionError:
        passed = False
    except Exception as exc:
        return {'valid': False, 'outcome': 'grader_error', 'errorType': type(exc).__name__}
    return {'valid': True, 'outcome': 'passed' if passed else 'rejected', 'parsed': parsed, 'passed': passed}
