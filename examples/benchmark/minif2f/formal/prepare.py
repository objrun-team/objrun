"""Freeze all 244 AI-MO test problems; do not select by pilot outcomes."""
from pathlib import Path
import hashlib
import json
import shutil
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ASSETS = REPO / '.phase1-data/minif2f-restoration-public'
SUFFIX = '\n\nWrite a complete Lean 4 proof. Return the entire Lean file in one lean code fence. Keep the theorem statement exactly as supplied. Mathlib is available. Do not use sorry or new axioms.'

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main(out):
    out = Path(out); assert not out.exists(), 'Preserve existing staging'
    lock = json.loads((ASSETS/'public-lock.json').read_text(encoding='utf-8'))
    pinned = {e['file']:e for e in lock['entries']}
    for name in ['minif2f-test.parquet','problems-test-rows.json']:
        assert sha(ASSETS/name)==pinned[name]['sha256']
    assert lock['pins']['AI-MO/minif2f_test']=='5def318348521dfc34875045a9ecddf729a2b49f'
    raw = json.loads((ASSETS/'problems-test-rows.json').read_text(encoding='utf-8'))
    book = [json.loads(s) for s in (ASSETS/'problems.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
    rows = {r['name']:r for r in book if r['split']=='test'}
    assert len(raw)==len(rows)==244 and len({r['name'] for r in raw})==244
    public=[]
    for original in raw:
        r=rows[original['name']]
        assert original['informal_prefix']==r['informal']
        assert original['formal_statement']==r['header']+r['informal']+r['statement']
        q={k:r[k] for k in ['id','name','split','header','informal','statement']}
        assert q['id']=='test/'+q['name'] and q['statement'].lstrip().startswith('theorem '+q['name'])
        q['stratum']=next((x for x in ['amc','aime','imo','mathd_algebra','mathd_numbertheory'] if q['name'].startswith(x)),'other')
        q['prompt']=q['informal']+'\n\n```lean\n'+q['header']+q['statement']+'\n```'+SUFFIX
        q.update({k+'Sha256':hashlib.sha256(q[k].encode()).hexdigest() for k in ['header','statement','prompt']})
        public.append(q)
    (out/'data').mkdir(parents=True);(out/'vendor').mkdir()
    def save(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save(out/'data/public-test.json',public)
    save(out/'data/catalog-manifest.json',{'split':'test','tasks':244,'armTaskRecords':488,
        'dataset':'AI-MO/minif2f_test','revision':lock['pins']['AI-MO/minif2f_test'],
        'parquetSha256':pinned['minif2f-test.parquet']['sha256'],
        'pinnedDecodedRowsSha256':pinned['problems-test-rows.json']['sha256'],
        'decoderImageId':pinned['problems-test-rows.json']['decoder_image_id'],
        'all244HeadersStatementsAndInformalTextsComparedToPinnedDecode':True,
        'bookSha256':sha(ASSETS/'problems.jsonl'),'publicTestSha256':sha(out/'data/public-test.json'),
        'ordering':'Pinned dataset order; arms interleaved and initial arm alternates by task',
        'ids':[r['id'] for r in public],'pilotCandidatesOrHistoricalScoresReused':False,
        'toolchainPins':lock['pins']})
    for src,name in [(REPO/'examples/benchmark/minif2f/stand.py','source_stand.py'),
                     (ASSETS/'kimina-models.py','kimina_models.py'),(ASSETS/'public-lock.json','public-lock.json')]:
        shutil.copy2(src,out/'vendor'/name)
    print(json.dumps({'prepared':str(out),'tasks':len(public),'publicTestSha256':sha(out/'data/public-test.json')}))

if __name__=='__main__':main(sys.argv[1])
