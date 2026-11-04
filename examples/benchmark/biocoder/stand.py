import argparse
import ast
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[3]
HOME=ROOT/'.phase1-data/biocoder'
sys.path.insert(0,str(ROOT/'examples/benchmark/_lib'))
from gradelib import serve
from isolated_python import score
SOURCE=json.loads((HOME/'source.json').read_text(encoding='utf-8'))
BOOK={}
for tid in SOURCE['selectedIds']:
    prompt=(HOME/f'Prompts/Rosalind/Prompts/{tid}.txt').read_text(encoding='utf-8')
    BOOK['biocoder-'+tid]={'id':'biocoder-'+tid,'rawId':tid,'prompt':prompt+'\nImplement a complete Python function def solve(text): accepting the input file contents and returning the required output as a string. Return only code. The official BioCoder Rosalind grader compares output strings after stripping surrounding whitespace; do not change internal formatting.'}

def extract(text):
    match=re.search(r'```(?:python)?\s*\n(.*?)```',text,re.S)
    return (match[1] if match else text).strip()

def parsed(text,item):
    try: return any(isinstance(n,ast.FunctionDef) and n.name=='solve' for n in ast.parse(extract(text)).body)
    except SyntaxError: return False

def correct(text,item):
    if not parsed(text,item): return False
    verdict=score('biocoder',{'id':item['rawId'],'code':extract(text)},seconds=60)
    if not verdict.get('valid'): raise RuntimeError(verdict.get('errorType','GraderError'))
    return bool(verdict['passed'])

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--port',type=int,default=17928); ap.add_argument('--selftest',action='store_true'); args=ap.parse_args()
    if args.selftest:
        records=[]
        for item in BOOK.values():
            tid=item['rawId']
            expected=(HOME/f'vendor/biocoder/evaluation/TestRosalind/testcases/rosalind_{tid}sol.txt').read_text(encoding='utf-8')
            # A known-correct output control verifies exact formatting and the real
            # sandbox I/O path. This is not an official reference implementation.
            for kind,code in [('known_correct_output_control','def solve(text): return '+repr(expected)),('wrong','def solve(text): return "definitely not the required output"')]:
                verdict=score('biocoder',{'id':tid,'code':code},seconds=60)
                record={'id':tid,'kind':kind,'checkPassed':bool(verdict.get('valid') and (verdict.get('passed') if kind=='known_correct_output_control' else not verdict.get('passed'))),**verdict}
                records.append(record); print(json.dumps(record),flush=True)
        for kind,code in [('read_hidden_expected_output',"open('/root/oracle/vendor/biocoder/evaluation/TestRosalind/testcases/rosalind_dnasol.txt').read()"),('exit_without_tests','import os\nos._exit(0)')]:
            verdict=score('biocoder',{'id':'dna','code':code})
            records.append({'id':'dna','kind':kind,'checkPassed':bool(verdict.get('valid') and not verdict.get('passed')),**verdict})
        output={'allPassed':all(r['checkPassed'] for r in records),'subset':'official BioCoder Rosalind; GitHub Python/Java fuzz harness pending','positiveControl':'Known-correct output replay; not claimed as a reference program','records':records}
        (ROOT/'test/fixtures/phase1/biocoder-selfcheck.json').write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8')
        raise SystemExit(0 if output['allPassed'] else 1)
    serve(BOOK,lambda item:{'id':item['id'],'prompt':item['prompt']},{'parsed':parsed,'correct':correct},args.port,'biocoder')
