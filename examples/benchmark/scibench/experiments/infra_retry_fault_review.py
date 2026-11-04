"""Read captured provider evidence without generating another answer or changing records."""
from pathlib import Path
import collections,hashlib,json,subprocess,sys
from infra_retry_policy import classify

REPO=Path(__file__).resolve().parents[4];local=REPO/'docs/scibench/infra-retry-20261016-v1-c32';root=local/'full-results';out=root/'outputs/canonical'
read=lambda p:json.loads(p.read_text(encoding='utf-8'));sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
records=[read(p) for p in (out/'results').glob('*/*.json')];assert len(records)==47
review=[]
for r in records:
 if r['grade'].get('valid'):continue
 calls=[]
 for p in sorted((out/'calls'/r['arm']/r['id']).rglob('receipt.json')):
  v=read(p);raw=p.with_name('response.raw.txt');response=read(p.with_name('response.json')) if p.with_name('response.json').exists() else None
  wire=read(p.with_name('request.json'))
  assert wire['provider']['only']==['digitalocean'] and not wire['provider']['allow_fallbacks'] and wire['stream'] is False
  calls.append({'path':str(p.relative_to(root)),'httpStatus':v['httpStatus'],'fault':v['fault'],'seconds':v['seconds'],'generationId':v.get('generationId'),'knownCostUsd':v['actualCostUsd'],'unknownCost':v['unknownCost'],'reserveUsd':v['upperBoundUsd'],'rawBytes':raw.stat().st_size if raw.exists() else None,'rawWhitespaceOnly':raw.exists() and not raw.read_text(encoding='utf-8').strip(),'rawSha256':sha(raw) if raw.exists() else None,'finishReason':v.get('finishReason'),'provider':v.get('provider'),'model':v.get('model'),'responseHasSubmitTool':bool(response and any(t.get('function',{}).get('name')=='submit' for c in response.get('choices',[]) for t in c.get('message',{}).get('tool_calls',[])))})
 review.append({'arm':r['arm'],'id':r['id'],'classification':classify(r),'grade':r['grade'],'engineVerdict':r.get('engineVerdict'),'error':r.get('error'),'calls':calls})
# Replay the actual captured whitespace through the production decoder. A failure
# to reject it is red: this command asserts the exact observed transport symptom.
remote=r'''
from pathlib import Path
import json,subprocess
r=Path('/var/tmp/tgengin-scibench-20261016/scibench-infra-retry-20261016-v1-c32')
paths=[p for p in (r/'outputs/canonical/calls').rglob('response.raw.txt') if not p.read_text().strip()]
assert paths,'MissingCapturedWhitespaceEvidence'
code="import {decodeProviderResponse} from "+json.dumps(str(r/'package/transport.ts'))+";import {readFileSync} from 'node:fs';let rejected=0;for(const p of "+json.dumps([str(p) for p in paths])+"){try{decodeProviderResponse(readFileSync(p,'utf8'));throw Error('WhitespaceAccepted');}catch(e){if(!String(e).includes('IncompleteProviderResponse:WhitespaceOnly'))throw e;rejected++;}}console.log(JSON.stringify({allPassed:true,rejectedCapturedWhitespace:rejected,realProviderCalls:0}));"
p=subprocess.run([str(r/'bin/bun'),'-e',code],capture_output=True,text=True,timeout=15);assert p.returncode==0,p.stderr;print(p.stdout)
'''
p=subprocess.run(['ssh','-F','C:/Users/y1252/Documents/Codex/2026-10-15/s-c/work/scicode/ssh-config','novaeve','python3.11','-'],input=remote,capture_output=True,text=True,timeout=30);assert p.returncode==0,p.stderr
replay=json.loads(p.stdout)
v={'allPassed':True,'records':review,'classificationCounts':dict(collections.Counter(x['classification'] for x in review)),'capturedResponseReplay':replay,'findings':['Three initial native calls returned HTTP200 whitespace without JSON; their bounded retry lasted until the original deadline.','A later quan native call timed out before an HTTP response; its earlier calls contain valid DigitalOcean responses.','Two other records explicitly expired without final submit; excluded even where a transport event occurred during their history.','No evidence of wrong provider/model, request duplication, account rejection, or malformed request in these four eligible outcomes.','Captured response replay reproduces the existing decoder rejection; it does not prove current provider health. No model, timeout, retry-chain or dollar-limit change is justified.','Round2 may use only one of the four authorized attempts as a health gate. If it is not valid, stop; do not rotate to another gate or retry it. Gate is within its ordinary600s/c5/3-chain budget, not an extra probe.']}
(local/'FAULT_REVIEW.json').write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'allPassed':True,'classificationCounts':v['classificationCounts'],'capturedResponseReplay':replay,'eligibleIds':[x['id'] for x in review if x['classification'].startswith('infra_')],'excludedIds':[x['id'] for x in review if not x['classification'].startswith('infra_')]}))
