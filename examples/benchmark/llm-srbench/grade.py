import ast
import json
from pathlib import Path
import sys
sys.path[:0]=['/extras','/material-extras','/worker']
import numpy as np
from scipy.stats import kendalltau
from sklearn.metrics import mean_absolute_percentage_error
from function_proxy import FunctionProxy, CandidateError

source=Path('/root/oracle/vendor/llm-srbench/bench/pipelines.py').read_text(encoding='utf-8')
node=next(x for x in ast.parse(source).body if isinstance(x,ast.FunctionDef) and x.name=='compute_output_base_metrics')
exec(compile(ast.Module(body=[node],type_ignores=[]),'official_metrics.py','exec'))

def grade(request):
    row=None
    for line in Path('/root/oracle/pilot.jsonl').open(encoding='utf-8'):
        candidate=json.loads(line)
        if candidate['instance_id']==request['id']:
            row=candidate
            break
    if row is None: raise LookupError('UnknownTask')
    group='test' if request.get('final') else 'train'
    # The first 30 training examples appear in the public preparation prompt.
    # All remaining training points are feedback data; test data is acceptance-only.
    start=0 if group=='test' else 30
    X=np.asarray(row[group+'_input'][start:],dtype=float)
    y=np.asarray(row[group+'_output'][start:],dtype=float).reshape(-1)
    try:
        with FunctionProxy(request['code']) as function: out=function.call('predict',X)
        pred=np.asarray(out,dtype=float).reshape(-1)
        if pred.shape!=y.shape or not np.all(np.isfinite(pred)):
            return {'valid':True,'passed':False,'errorType':'IncompletePrediction','points':len(y)}
        metrics=compute_output_base_metrics(pred,y)
        reported={key:float(value) if np.isfinite(float(value)) else None for key,value in metrics.items()}
        passed=reported['nmse'] is not None and reported['nmse']<=.01
        return {'valid':True,'passed':bool(passed),'split':group,'points':len(y),'metrics':reported}
    except (CandidateError,SyntaxError,TypeError,ValueError) as error:
        return {'valid':True,'passed':False,'errorType':type(error).__name__}

if __name__=='__main__':
    try: result=grade(json.load(sys.stdin))
    except Exception as error: result={'valid':False,'passed':False,'errorType':type(error).__name__}
    print(json.dumps(result),flush=True)
