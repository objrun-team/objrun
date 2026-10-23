"""Independent SciCode controls from public problem specifications.

No model generation or downloads. --problem resumes only selected controls;
unchanged records are retained only when the fixture checksum still matches.
--negative checks every selected step rejects a wrong return and each problem
rejects malformed syntax. Private-target and process-exit probes are separately
recorded in scicode-selfcheck.json.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[2]
HERE=ROOT/'examples/benchmark/scicode'
sys.path.insert(0,str(HERE))
from controller import score,PROBLEMS
REFERENCES={'5':'lanczos.py','8':'cross_filter.py','9':'weighted_jacobi.py',
            '11':'gadc.py','12':'schrodinger.py','14':'mannella.py',
            '15':'crank_nicolson.py','16':'davidson.py','17':'energy_symbols.py','18':'nurbs.py'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--problem',action='append',choices=list(REFERENCES))
    parser.add_argument('--negative',action='store_true')
    args=parser.parse_args()
    selected=args.problem or list(REFERENCES)
    suffix='negative' if args.negative else 'expanded'
    output_file=ROOT/f'docs/phase1/scicode-{suffix}-controls.json'
    records=json.loads(output_file.read_text(encoding='utf-8')).get('records',[]) if output_file.exists() else []
    records=[r for r in records if r['problem'] not in selected and
             r['sourceSha256']==hashlib.sha256((HERE/'fixtures'/REFERENCES[r['problem']]).read_bytes()).hexdigest()]
    expected={(pid,s['step_number'],'wrong_return' if args.negative else 'independent_reference_from_public_definition')
              for pid in REFERENCES for s in PROBLEMS[pid]['sub_steps']}
    if args.negative:
        expected.update((pid,PROBLEMS[pid]['sub_steps'][0]['step_number'],'syntax_error') for pid in REFERENCES)

    def save():
        seen={(r['problem'],r['step'],r['kind']) for r in records}
        complete=seen==expected
        output={'variant':'SciCode-Verified v2','coverage':'selected 10 whole problems / 39 substeps',
                'allPassed':complete and all(r.get('checkPassed') if args.negative else
                                            r.get('valid') and r.get('passed') for r in records),
                'complete':complete,'expectedChecks':len(expected),'recordedChecks':len(seen),'records':records}
        output_file.write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8')
        return output

    def record(pid,index,kind,code,source):
        result=score(pid,index,code)
        item={'problem':pid,'step':PROBLEMS[pid]['sub_steps'][index]['step_number'],
              'kind':kind,'source':source.name,'sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),**result}
        if args.negative:
            item['checkPassed']=bool(result.get('valid')) and result.get('passed') is False
            if kind=='syntax_error':
                item['checkPassed']=item['checkPassed'] and result.get('errorType')=='SyntaxError'
        records.append(item)
        print(json.dumps(item),flush=True)
        save()

    save()
    for pid in selected:
        file=HERE/'fixtures'/REFERENCES[pid]
        code=PROBLEMS[pid]['required_dependencies']+'\n'+file.read_text(encoding='utf-8')
        for i,step in enumerate(PROBLEMS[pid]['sub_steps']):
            if args.negative:
                function=re.search(r'^def\s+(\w+)\(',step['function_header']).group(1)
                wrong=code+f'\n\ndef {function}(*args, **kwargs):\n    return None\n'
                record(pid,i,'wrong_return',wrong,file)
            else:
                record(pid,i,'independent_reference_from_public_definition',code,file)
        if args.negative:
            record(pid,0,'syntax_error','def broken(',file)
    save()
    checks=[r for r in records if r['problem'] in selected]
    return all(r.get('checkPassed') if args.negative else r.get('valid') and r.get('passed') for r in checks)


if __name__=='__main__':
    raise SystemExit(0 if main() else 1)
