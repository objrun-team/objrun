"""Official AddAtomAction test-split structure matching; targets never enter /problems."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
sys.path[:0]=['/extras','/material-extras']
HOME=Path(os.environ.get('TGENGIN_ATOM_HOME','/oracle'))
VENDOR=HOME/'vendor/atomworld'
spec=importlib.util.spec_from_file_location('atomworld_evaluate',VENDOR/'src/atomworld/evaluate.py')
official=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=official
spec.loader.exec_module(official)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'_lib'))
from gradelib import serve
ROWS=json.loads((HOME/'bench/AddAtomAction.json').read_text(encoding='utf-8'))
BOOK={f"atomworld-{row['problem_id']}":dict(row,id=f"atomworld-{row['problem_id']}") for row in ROWS}
TEMPLATE=(HOME/'system_prompt.txt').read_text(encoding='utf-8')

def parsed(text,item):
    cif=official._extract_cif(text)
    return bool(cif is not None and official._parse_cif(cif,primitive=False) is not None)

def correct(text,item):
    return bool(official.evaluate(target_cif=item['output'],generated_output=text,action_name='add_atom_action').correct)

def view(item):
    return {'id':item['id'],'prompt':TEMPLATE.format(action_prompt=item['action_prompt'],input=item['input'])}

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--port',type=int,default=17927)
    ap.add_argument('--selftest',action='store_true')
    args=ap.parse_args()
    if args.selftest:
        records=[]
        for item in list(BOOK.values())[:10]:
            good='<cif>'+item['output']+'</cif>'
            unchanged='<cif>'+item['input']+'</cif>'
            ok=parsed(good,item) and correct(good,item) and not correct(unchanged,item) and not correct('not a CIF',item)
            records.append({'id':item['id'],'passed':ok,'reference':correct(good,item),'unchangedRejected':not correct(unchanged,item),'formatRejected':not parsed('not a CIF',item)})
        print(json.dumps({'benchmark':'AtomWorld','subset':'official bench/AddAtomAction','defaultStructureTolerance':{'stol':.5,'primitive_cell':False},'allPassed':all(r['passed'] for r in records),'records':records}))
        raise SystemExit(0 if all(r['passed'] for r in records) else 1)
    serve(BOOK,view,{'parsed':parsed,'correct':correct},args.port,'atomworld')
