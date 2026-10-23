"""Post-release, read-only import boundary for original SB receipt derivation.

This is deliberately not python_child_entry: that command-forwarding bootstrap
requires an active resource lease. Here original modules are imported from exact
reviewed source pins, and no guard forwarding/resource function is invoked.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def pin(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def load(p, name):
    assert pin(p['path']) == p, 'readonly_original_source_pin'
    assert Path(p['path']).suffix == '.py', 'readonly_python_module'
    spec = importlib.util.spec_from_file_location(name, p['path'])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def initialise(request):
    assert request['protocol'] == 'bench-original-sb-native-closure-request-v1'
    pins = request['namedModulePins']
    assert set(pins) == {'processes', 'native_process', 'observed_owned_spawn'}, 'exact_original_readonly_dependencies'
    assert pins['processes'] == request['processesPin'], 'original_process_source_binding'
    for name in ('processes', 'native_process', 'observed_owned_spawn'):
        load(pins[name], name)
    load(request['guardPin'], '_bench_original_owned_guard')
    helper = request['helperPin']
    assert helper['sha256'] in {'4416bc33034564b54229afb1ae8c4311efa195deb904de0de23693df1b03d952', '3f17b2e58fc15fec8345172dba66e2f08885be98607affa8c50b2a02c031ed78'}, 'accepted_original_derivation_helper'
    return load(helper, '_original_sb_readonly_derivation')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_bytes())
    helper = initialise(request)
    result = helper.derive(request)
    result['requestPin'] = pin(args.request)
    result['standaloneSourcePin'] = pin(__file__)
    result['executionBoundary'] = 'Plain Python with original observed native capture; imports exact original guard but invokes no forwarding/lease/resource function.'
    target = Path(args.output).resolve()
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(complete=True, outputPin=pin(target))))


if __name__ == '__main__':
    main()
