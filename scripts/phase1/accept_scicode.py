"""Reaccept frozen SciCode pilot candidates with explicit identity checksums.

This script never generates candidates or changes their code. Earlier acceptance
is preserved; reacceptance results never enter model context or selection.
"""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[2]
HERE=ROOT/'examples/benchmark/scicode'
sys.path.insert(0,str(HERE))
from controller import PROBLEMS,PILOT_IDS,score
RUN='phase1-scicode-verified-2026-10-07T21-48-09-120Z'
HOME=ROOT/'docs/phase1/pilots'/RUN
OUTPUT=HOME/'whole-problems-reaccepted.json'

def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def main():
    summary=json.loads((HOME/'summary.json').read_text(encoding='utf-8'))
    manifest=json.loads((HOME/'manifest.json').read_text(encoding='utf-8'))
    original=json.loads((HOME/'whole-problems.json').read_text(encoding='utf-8'))
    assert summary['completed'] and manifest['pilotProblemIds']==PILOT_IDS
    by_id={r['officialId']:r for r in summary['results']}
    assert len(by_id)==len(summary['results'])==39
    old={r['problem']:r['finalAcceptance'] for r in original['results']}
    output={'run':RUN,'variant':'SciCode-Verified v2','createdAt':datetime.now(timezone.utc).isoformat(),
            'provenance':'Fresh independent replay of frozen delivered candidates; earlier acceptance retained separately.',
            'gradingSeconds':manifest['gradingSeconds'],'complete':False,'completedProblems':0,'results':[],
            'graderSourceHashes':{name:hashlib.sha256((HERE/name).read_bytes()).hexdigest()
                                  for name in ['controller.py','grade.py','worker.py','codec.py']}}
    for pid in PILOT_IDS:
        codes=[];identities=[]
        for step in PROBLEMS[pid]['sub_steps']:
            official_id='scicode-'+step['step_number']
            answer=by_id[official_id]['answer']
            match=re.search(r'```(?:python)?\s*\n([\s\S]*?)```',answer)
            code=(match[1] if match else answer).strip()
            codes.append(code)
            identities.append({'officialId':official_id,'answerSha256':sha(answer),'extractedCodeSha256':sha(code)})
        cumulative=PROBLEMS[pid]['required_dependencies']+'\n\n'+'\n\n'.join(codes)
        verdicts=[score(pid,i,cumulative,seconds=manifest['gradingSeconds'])
                  for i in range(len(PROBLEMS[pid]['sub_steps']))]
        acceptance={'valid':all(r.get('valid') is True for r in verdicts),
                    'passed':all(r.get('valid') is True and r.get('passed') is True for r in verdicts),
                    'steps':verdicts}
        same=(acceptance['valid']==old[pid]['valid'] and acceptance['passed']==old[pid]['passed'] and
              [(r.get('valid'),r.get('passed')) for r in verdicts]==
              [(r.get('valid'),r.get('passed')) for r in old[pid]['steps']])
        record={'problem':pid,'substeps':len(codes),'candidateIdentities':identities,
                'cumulativeCodeSha256':sha(cumulative),'originalVerdictsMatch':same,'finalAcceptance':acceptance}
        output['results'].append(record);output['completedProblems']=len(output['results'])
        OUTPUT.write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'problem':pid,'passed':acceptance['passed'],'valid':acceptance['valid'],'originalVerdictsMatch':same}),flush=True)
    output['complete']=True
    output['allOriginalVerdictsMatch']=all(r['originalVerdictsMatch'] for r in output['results'])
    OUTPUT.write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8')
    return all(r['finalAcceptance']['valid'] for r in output['results']) and output['allOriginalVerdictsMatch']

if __name__=='__main__':
    raise SystemExit(0 if main() else 1)
