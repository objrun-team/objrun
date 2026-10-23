"""BioCoder's official Rosalind exact-output check, with candidate code isolated."""
import json
from pathlib import Path
import sys
sys.path[:0]=['/worker']
from function_proxy import FunctionProxy,CandidateError

def grade(request):
    home=Path('/root/oracle/vendor/biocoder/evaluation/TestRosalind/testcases')
    inputs=(home/f"rosalind_{request['id']}.txt").read_text(encoding='utf-8')
    expected=(home/f"rosalind_{request['id']}sol.txt").read_text(encoding='utf-8')
    try:
        with FunctionProxy(request['code'],seconds=60) as function: actual=function.call('solve',inputs)
        if not isinstance(actual,str): return {'valid':True,'passed':False,'errorType':'OutputTypeError'}
        return {'valid':True,'passed':actual.strip()==expected.strip()}
    except (CandidateError,SyntaxError) as error: return {'valid':True,'passed':False,'errorType':type(error).__name__}

if __name__=='__main__':
    try: result=grade(json.load(sys.stdin))
    except Exception as error: result={'valid':False,'passed':False,'errorType':type(error).__name__}
    print(json.dumps(result),flush=True)
