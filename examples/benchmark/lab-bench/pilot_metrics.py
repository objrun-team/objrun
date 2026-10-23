"""Record abstention after generation using the official frozen prompt ordering."""
import hashlib
import json
import sys
from stand import BOOK, parsed, correct
request=json.load(sys.stdin)
records=[]
for task in request['results']:
    item=BOOK[task['officialId']]
    answer=task['answer']
    records.append({'officialId':task['officialId'],'candidateSha256':hashlib.sha256(answer.encode()).hexdigest(),'parsed':parsed(answer,item),'abstained':answer==item['unsure'],'correct':correct(answer,item)})
output={'subset':'public ProtocolQA','seed':0,'separation':'Computed after all generation; never used for candidate selection, revision or stopping.','tasks':len(records),'abstentions':sum(r['abstained'] for r in records),'invalidFormat':sum(not r['parsed'] for r in records),'correct':sum(r['correct'] for r in records),'records':records}
print(json.dumps(output))
