import argparse
import ast
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'_lib'))
from gradelib import serve
from controller import PROBLEMS, IDS, ROOT, score

BOOK={f'humaneval-plus-{tid}':dict(row,id=f'humaneval-plus-{tid}') for tid,row in PROBLEMS.items()}

def extract(text):
    match=re.search(r'```(?:python)?\s*\n(.*?)```',text,re.S)
    return (match[1] if match else text).strip()

def parsed(text,item):
    try:
        return bool(ast.parse(extract(text)).body)
    except SyntaxError: return False

def correct(text,item):
    verdict=score(item['task_id'],extract(text))
    if not verdict.get('valid'): raise RuntimeError(verdict.get('errorType','GraderError'))
    return bool(verdict['passed'])

def view(item):
    return {'id':item['id'],'prompt':item['prompt']+'\nReturn the full completed Python function, with the original signature and docstring. Submit only Python code.'}

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--port',type=int,default=17926)
    ap.add_argument('--selftest',action='store_true')
    args=ap.parse_args()
    if args.selftest:
        records=[]
        for tid in IDS:
            row=PROBLEMS[tid]
            for kind,code in [('reference',row['prompt']+row['canonical_solution']),('wrong',f"def {row['entry_point']}(*args): return None"),('read_hidden_tests',"open('/root/official/evalplus/eval/__init__.py').read()"),('exit_without_tests','import os\nos._exit(0)')]:
                verdict=score(tid,code)
                ok=verdict.get('valid') and (verdict.get('passed') if kind=='reference' else not verdict.get('passed'))
                record={'id':tid,'kind':kind,'checkPassed':bool(ok),**verdict}
                records.append(record)
                print(json.dumps(record),flush=True)
        output={'benchmark':'HumanEval+','release':'v0.1.10','ids':IDS,'allPassed':all(r['checkPassed'] for r in records),'records':records}
        (ROOT/'test/fixtures/phase1/humaneval-plus-selfcheck.json').write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8')
        raise SystemExit(0 if output['allPassed'] else 1)
    serve(BOOK,view,{'parsed':parsed,'correct':correct},args.port,'humaneval-plus')
