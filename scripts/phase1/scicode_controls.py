"""Independent small implementations exercise array and symbolic grading interfaces."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / 'examples/benchmark/scicode'
sys.path.insert(0,str(HERE))
from controller import score, PROBLEMS
records = []
for pid, file in [('8','cross_filter.py'),('17','energy_symbols.py')]:
    code = PROBLEMS[pid]['required_dependencies'] + '\n' + (HERE/'fixtures'/file).read_text(encoding='utf-8')
    result = score(pid,0,code)
    record = {'problem':pid,'step':0,'kind':'independent_reference','source':file,**result}
    records.append(record)
    print(json.dumps(record),flush=True)
(ROOT/'docs/phase1/scicode-additional-controls.json').write_text(json.dumps({'allPassed':all(r.get('valid') and r.get('passed') for r in records),'records':records},indent=2)+'\n',encoding='utf-8')
