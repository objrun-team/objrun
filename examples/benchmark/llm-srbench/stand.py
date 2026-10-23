import argparse
import ast
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'examples/benchmark/_lib'))
from isolated_python import score
from grader_status import require_valid_verdict, fault_payload
HOME=ROOT/'.phase1-data/llm-srbench'
BOOK={}
for line in (HOME/'pilot.jsonl').open(encoding='utf-8'):
    row=json.loads(line)
    tid='llm-srbench-'+row['instance_id']
    samples=list(zip(row['train_input'][:30],row['train_output'][:30]))
    BOOK[tid]={'id':tid,'rawId':row['instance_id'],'prompt':row['description']+'\nInput columns: '+str(row['input_vars'])+'\nFirst 30 training samples (input,output):\n'+json.dumps(samples)+'\nWrite a scientific Python function def predict(X) that predicts one output per row of X. Use the input columns in the order given. Submit complete Python code. The preparation success criterion is finite predictions for all points and official NMSE <= 0.01.','expression':row['gt_expression'],'variables':row['input_vars']}
CACHE={}

def extract(text):
    match=re.search(r'```(?:python)?\s*\n(.*?)```',text,re.S)
    return (match[1] if match else text).strip()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_): pass
    def send(self,obj,status=200):
        raw=json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('content-type','application/json')
        self.send_header('content-length',str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_GET(self):
        if self.path=='/health': self.send({'ok':True,'tasks':len(BOOK),'variant':'public author release LSR-Transform','threshold':.01})
        elif self.path.startswith('/problems'): self.send([{'id':r['id'],'prompt':r['prompt']} for r in BOOK.values()])
        else: self.send({'error':'not found'},404)
    def do_POST(self):
        try:
            body=json.loads(self.rfile.read(int(self.headers.get('content-length',0))))
            inp=body.get('input',{}); task=inp.get('task',{})
            tid=str(task.get('id','')).split('/')[-1]
            if tid not in BOOK: self.send({'error':'UnknownTask'},422); return
            candidate=inp.get('result'); text=candidate.get('body') if isinstance(candidate,dict) else candidate
            if text is None: text=task.get('result','')
            code=extract(text)
            try: parsed=any(isinstance(n,ast.FunctionDef) and n.name=='predict' for n in ast.parse(code).body)
            except SyntaxError: parsed=False
            if self.path=='/parsed': self.send({'value':parsed}); return
            if self.path not in ['/correct','/accept']: self.send({'error':'not found'},404); return
            if not parsed: self.send({'value':False} if self.path=='/correct' else {'valid':True,'passed':False,'errorType':'MissingPrediction'}); return
            final=self.path=='/accept'
            key=(tid,code,final)
            if key not in CACHE:
                verdict=require_valid_verdict(score('llm-srbench',{'id':BOOK[tid]['rawId'],'code':code,'final':final}))
                CACHE[key]=verdict
            verdict=require_valid_verdict(CACHE[key])
            if final: self.send(verdict); return
            self.send({'value':verdict['passed']})
        except Exception as error: self.send(fault_payload(error),503)

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--port',type=int,default=17929)
    ap.add_argument('--selftest',action='store_true')
    args=ap.parse_args()
    if args.selftest:
        records=[]
        for item in BOOK.values():
            code='import numpy as np\nimport sympy as sp\ndef predict(X):\n    names='+repr(item['variables'])+'\n    symbols=[sp.Symbol(n) for n in names]\n    expr=sp.sympify('+repr(item['expression'])+',locals=dict(zip(names,symbols)))\n    return sp.lambdify(symbols,expr,modules="numpy")(*[X[:,i] for i in range(len(names))])'
            for kind,program in [('reference',code),('wrong','import numpy as np\ndef predict(X): return np.full(len(X),123456789.)')]:
                verdict=score('llm-srbench',{'id':item['rawId'],'code':program,'final':True})
                record={'id':item['rawId'],'kind':kind,'checkPassed':bool(verdict.get('valid') and (verdict.get('passed') if kind=='reference' else not verdict.get('passed'))),**verdict}
                records.append(record); print(json.dumps(record),flush=True)
        output={'allPassed':all(r['checkPassed'] for r in records),'records':records,'variant':'public author release LSR-Transform','threshold':.01}
        (ROOT/'docs/phase1/llm-srbench-selfcheck.json').write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8')
        raise SystemExit(0 if output['allPassed'] else 1)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
