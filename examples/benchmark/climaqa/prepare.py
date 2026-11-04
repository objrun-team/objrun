import csv, hashlib, io, json, random, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'docs/climaqa/pilot-20261028-v1'
REV = '3f084a0202c6260e588fb5b681d2e4ec859a3845'
URL = f'https://huggingface.co/datasets/Rose-STL-Lab/ClimaQA/resolve/{REV}/climaqa_gold/mcq/mcq_benchmark.csv'
EXPECTED = 'c05a8babb0fe56d3322344a14e8146a77c84a9882fbaf68a0a6ffd0a74dd3986'

def main():
    data = urllib.request.urlopen(URL, timeout=30).read()
    assert hashlib.sha256(data).hexdigest() == EXPECTED
    rows = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    valid = [x for x in rows if x['Validation'] == 'True']
    assert len(rows) == 292 and len(valid) == 245
    rng = random.Random(20261028)
    selected = []
    for level, count in [('BASE', 10), ('REASONING', 6), ('HYPOTHETICAL', 4)]:
        group = [x for x in valid if x['Complexity'] == level]
        selected.extend(rng.sample(group, count))
    rng.shuffle(selected)
    assert len({x[''] for x in selected}) == 20
    public, private = [], []
    for row in selected:
        import re
        parts = re.split(r'\s*-{20}\s*', row['Options'].strip())
        assert len(parts) == 4 and all(re.match(r'^'+x+r'\)', p.strip(), re.I) for x,p in zip('abcd',parts))
        assert row['Answer'] in 'abcd'
        tid = 'climaqa-gold-mcq-' + row[''].zfill(3)
        prompt = 'Answer the following climate science multiple-choice question. Choose exactly one option. End your response with exactly one line: Answer: X, where X is A, B, C, or D.\n\n' + row['Question'] + '\n\n' + row['Options']
        public.append({'id':tid,'source_row':int(row['']),'complexity':row['Complexity'],'prompt':prompt})
        private.append({'id':tid,'answer':row['Answer'].upper()})
    OUT.mkdir(parents=True, exist_ok=True)
    for name, obj in [('public.json',public),('private.json',private),('source.json',{'url':URL,'revision':REV,'sha256':EXPECTED,'allRows':292,'validated':245,'seed':20261028,'selection':'stratified random sample 10 BASE, 6 REASONING, 4 HYPOTHETICAL; shuffle','ids':[x['id'] for x in public]})]:
        path=OUT/name
        if path.exists(): raise RuntimeError('Refusing to overwrite '+str(path))
        path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'selected':len(public),'sourceSha256':EXPECTED,'revision':REV}))

if __name__ == '__main__': main()
