"""Independent acceptance after generation; records all tasks, including invalid ones."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[2]
PORTS={'gpqa':17903,'cmt':17901,'aime':17905,'chembench':17906,'chemiq':17907,'atmossci-bench':17924,'lab-bench':17925,'humaneval-plus':17926,'atomworld':17927,'biocoder':17928,'llm-srbench':17929}

def accept(directory):
    home=Path(directory)
    if not home.is_absolute(): home=ROOT/'docs/phase1/pilots'/home
    manifest=json.loads((home/'manifest.json').read_text(encoding='utf-8'))
    summary=json.loads((home/'summary.json').read_text(encoding='utf-8'))
    if not summary['completed']: raise ValueError('Generation did not complete; not an acceptance-eligible run')
    slug=manifest['benchmark']
    nodes=['parsed','accept' if slug=='llm-srbench' else 'equiv' if slug=='cmt' else 'correct']
    records=[]
    for task in summary['results']:
        values=[]
        valid=True
        error=None
        final_details=None
        for node in nodes:
            body={'input':{'task':{'id':task['id'],'result':task['answer']}}}
            request=urllib.request.Request(f'http://127.0.0.1:{PORTS[slug]}/{node}',json.dumps(body).encode(),{'content-type':'application/json'})
            try:
                with urllib.request.urlopen(request,timeout=240) as response: result=json.load(response)
                if node=='accept':
                    if isinstance(result,dict):
                        final_details={key:result[key] for key in ['valid','passed','split','points','metrics','errorType'] if key in result}
                    if not isinstance(result,dict) or type(result.get('valid')) is not bool or type(result.get('passed')) is not bool:
                        raise ValueError('invalid final-test verdict')
                    if not result['valid']:
                        valid=False
                        error=result.get('errorType','GraderError')
                        break
                    value=result['passed']
                else:
                    value=result.get('value') if isinstance(result,dict) else result
                if type(value) is not bool: raise ValueError('invalid boolean result')
                values.append({'node':node,'value':value})
            except Exception as fault:
                valid=False
                error=type(fault).__name__
                break
        records.append({'officialId':task['officialId'],'candidateSha256':hashlib.sha256(task['answer'].encode()).hexdigest(),'valid':valid,'passed':valid and all(r['value'] for r in values),'outcome':'grader_error' if not valid else 'passed' if all(r['value'] for r in values) else 'rejected','nodes':values,'errorType':error,'finalVerdict':final_details})
    separation='All generation ended before this evaluation. Results never entered model context or affected selection/revision/stopping. Same immutable text candidate; official grading data.'
    if slug=='llm-srbench':
        separation+=' Generation feedback used training points only; this acceptance uses all held-out test points via /accept, never /correct.'
    output={'run':summary['run'],'benchmark':slug,'acceptedAt':datetime.now(timezone.utc).isoformat(),'separation':separation,'generationSourceDigest':manifest.get('sourceDigest'),'tasks':len(records),'passed':sum(r['passed'] for r in records),'valid':sum(r['valid'] for r in records),'records':records}
    (home/'acceptance.json').write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:output[k] for k in ['run','benchmark','tasks','passed','valid']}),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('runs',nargs='+')
    args=ap.parse_args()
    for run in args.runs: accept(run)
