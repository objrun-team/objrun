"""Freeze the first ten author-release LSR-Transform rows without loading the full corpus."""
import hashlib
import json
from pathlib import Path
import pyarrow.parquet as pq
HOME=Path('/data/llm-srbench')
rows=[]
for file in sorted((HOME/'public-release/lsr_transform').glob('*.parquet')):
    for batch in pq.ParquetFile(file).iter_batches(batch_size=1):
        rows.append(batch.to_pylist()[0])
        if len(rows)==10: break
    if len(rows)==10: break
assert len(rows)==10
out=HOME/'pilot.jsonl'
out.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
record=json.loads((HOME/'source.json').read_text(encoding='utf-8'))
record['pilotDataset']={'file':'pilot.jsonl','sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'ids':[r['instance_id'] for r in rows],'selection':'first ten author-release LSR-Transform rows, before generation'}
(HOME/'source.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'fields':list(rows[0]),'tasks':len(rows),'shapes':[{'id':r['instance_id'],'train':len(r['train_input']),'test':len(r['test_input']),'variables':r['input_vars']} for r in rows],'bytes':out.stat().st_size}))
