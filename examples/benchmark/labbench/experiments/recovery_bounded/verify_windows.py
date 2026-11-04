"""Run the pinned verifier on Windows without importing the Linux scheduler."""
from pathlib import Path
import ast
import hashlib
import json
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'recovery'))
from ops_recovery import LOCAL
from core import read, save, sha

root = Path(read(LOCAL / 'retrieval.json')['fullResults'])
source = root / 'operations-bounded/run_bounded.py'
assert sha(source) == read(root / 'bounded-operations-pins.json')['operations-bounded/run_bounded.py']
tree = ast.parse(source.read_text(encoding='utf-8'))
functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'final_classification']
assert len(functions) == 1
# Only the identical pure classifier is needed by the report; no Linux locking,
# process launch, budget, score, validity or provider behavior is emulated.
module = types.ModuleType('run_bounded')
exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), module.__dict__)
sys.modules['run_bounded'] = module
for name in ['report_bounded.py', 'verify_bounded.py']:
    assert sha(Path(__file__).with_name(name)) == sha(root / 'operations-bounded' / name)
import verify_bounded
verify_bounded.main()
proof = read(LOCAL / 'LOCAL_VERIFICATION.json')
assert proof['allPassed']
adapter = {'purpose': 'Windows cannot import fcntl. Extract only the byte-pinned original pure final_classification function AST; all original report and verifier checks execute unchanged.', 'modelCalls': 0, 'linuxSchedulerSourceSha256': sha(source), 'adapterSourceSha256': sha(__file__), 'originalVerifierSourceSha256': sha(root / 'operations-bounded/verify_bounded.py'), 'allOriginalChecksPassed': True}
save(LOCAL / 'LOCAL_VERIFICATION_ADAPTER.json', adapter)
print(json.dumps({'windowsAdapterVerified': True, 'allOriginalChecksPassed': True, 'adapter': adapter}), flush=True)
