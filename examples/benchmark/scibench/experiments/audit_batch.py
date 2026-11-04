"""Offline audit for a separate recovery/formal batch; never edits the original pilot."""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import math
import sqlite3
import sys

parser=argparse.ArgumentParser()
parser.add_argument('local',type=Path)
parser.add_argument('--partial',action='store_true')
args=parser.parse_args()
local=args.local.resolve();root=local/'full-results';out=root/'outputs/canonical'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda s:hashlib.sha256(s if isinstance(s,bytes) else s.encode()).hexdigest()
cfg=read(root/'package/experiment.json');catalog=read(root/'data'/cfg['catalog'])
book={r['id']:r for r in read(root/'data/private-tasks.json')}
sys.path.insert(0,str(root/'package'))
from grade import Scorer
scorer=Scorer(root/'package/vendor')
records=[read(p) for p in sorted((out/'results').rglob('*.json'))] if (out/'results').exists() else []
checks=[]
def check(name,ok):checks.append({'name':name,'passed':bool(ok)})
expected={(a,t['id']) for a in cfg['arms'] for t in catalog}
repair_path=root/'package/repair-plan.json'
repair=read(repair_path) if repair_path.exists() else None
if repair:
 expected={(a['arm'],a['id']) for a in repair['attempts']}
 check('repair-unique-attempt-identities',len(expected)==len(repair['attempts'])==len({a['attemptId'] for a in repair['attempts']}))
 round_no=repair.get('attemptNo',1)
 until_zero=repair.get('mode')=='until_zero'
 check('repair-one-new-full-attempt',all((a['attemptNo']>=1 if until_zero else a['attemptNo']==round_no) and a['eligible'] and (a['classification'].startswith('infra_') or (until_zero and repair.get('allInvalidExplicitlyAuthorized') and a['classification'].startswith('native_')) or (round_no==2 and repair.get('allSixRemainingExplicitlyAuthorized') and a.get('nativeRetryExplicitlyAuthorized') and a['classification'].startswith('native_'))) for a in repair['attempts']))
 if until_zero:check('repair-until-zero-scope',repair['roundNo']>=3 and all(a['roundNo']==repair['roundNo'] and a['attemptId'].endswith('/authorized-retry-'+str(a['attemptNo'])) and len(a['previousResultSha256'])==64 for a in repair['attempts']))
 if round_no==2:
  check('repair-second-round-scope',len(expected)==6 and repair['originalSevenNativeExcluded'] and all(a['arm']=='objrun' and a['attemptId'].endswith('/infra-retry-2') and a['previousAttemptId'].endswith('/infra-retry-1') and len(a['previousResultSha256'])==64 for a in repair['attempts']))
 check('repair-original-final-verified',repair['formalVerification']['originalAuditAllPassed'] and repair['formalVerification']['originalRecords']==1664 and repair['formalVerification']['localArchiveSha256Verified'])
 for pin in read(root/'provenance/solver-source-pins.json')['files']:
  check('repair-preserved-solver:'+pin['path'],sha((root/pin['path']).read_bytes())==pin['sha256'])
observed={(r['arm'],r['id']) for r in records}
check('record-identities',len(records)==len(observed) and (observed<=expected if args.partial else observed==expected))
check('catalog-public-whitelist',all(set(t)=={'id','source','prompt'} for t in catalog))
source=read(root/'data/source.json')
check('formal-dev-disjoint',source['promptOverlap']==0 and not ({r['id'] for r in read(root/'data/public-formal.json')} & set(source['pilotIds'])))
check('no-model-controls',read(out/'controls.json')['allPassed'])
prefix=read(out/'launch.json')['root'].rstrip('/')+'/'
for pin in read(out/'source-pins.json')['files']:
 check('source:'+pin['path'].removeprefix(prefix),sha((root/pin['path'].removeprefix(prefix)).read_bytes())==pin['sha256'])
for pin in source['files']:
 check('official-source:'+pin['path'],sha((root/pin['path']).read_bytes())==pin['sha256'])
suffix='\nSolve the problem. End with one finite numeric answer in the requested unit inside \\boxed{...}. For scientific notation use a\\times 10^{n}.'
prompts={r['id']:r['prompt']+suffix for r in catalog}
receipts=[];unsettled=[];dispatches=list((out/'calls').rglob('dispatch.json')) if (out/'calls').exists() else []
for p in sorted(dispatches):
 rel=p.relative_to(out/'calls');arm,tid=rel.parts[:2];request=read(p.with_name('request.json'));dispatch=read(p)
 ident=arm+'/'+tid+'/'+str(rel.parent)
 check('wire:'+ident,request['model']==cfg['model'] and request.get('stream') is False and request['temperature']==0 and request['max_tokens']==16384
       and request['provider']=={'only':['digitalocean'],'allow_fallbacks':False,'max_price':{'prompt':0.3,'completion':1.2}}
       and request['reasoning']=={'enabled':True,'effort':'high','exclude':False} and not any(k in request for k in ['seed','thinking','reasoning_effort','max_completion_tokens']))
 check('dispatch-hash:'+ident,sha(json.dumps(request,ensure_ascii=False,separators=(',',':')))==dispatch['requestSha256'])
 if arm=='objrun':
  check('native-tools:'+ident,all(t['function']['name'] in {'submit','verify','task_tree','node_load'} for t in request.get('tools',[])))
 else:
  index=int(rel.parts[2].split('-')[-1]);messages=[{'role':'user','content':prompts[tid]}]
  if arm=='binary' and index:
   for s in read(out/'tasks'/arm/tid/'samples.json')[:index]:messages.extend([{'role':'assistant','content':s['answer']},{'role':'user','content':'passed' if s['grade']['passed'] else 'failed'}])
  check('feedback-isolation:'+ident,request['messages']==messages)
 rp=p.with_name('receipt.json')
 if not rp.exists():
  unsettled.append(dispatch)
  if not args.partial:check('receipt-present:'+ident,False)
  continue
 receipt=read(rp);receipts.append((arm,tid,receipt))
 check('receipt-hash:'+ident,receipt['requestSha256']==dispatch['requestSha256'])
 check('unknown-cost-retained:'+ident,receipt['actualCostUsd'] is not None or receipt['unknownCost'] is True)
 if not receipt['fault']:
  response=read(p.with_name('response.json'))
  check('provider-model:'+ident,response['provider']=='DigitalOcean' and response['model'] in {cfg['model'],cfg['canonicalModel']})
for r in records:
 label=r['arm']+'/'+r['id'];folder=out/'tasks'/r['arm']/r['id'];answer=(folder/'final-answer.txt').read_text(encoding='utf-8')
 if repair:
  a=next(x for x in repair['attempts'] if (x['arm'],x['id'])==(r['arm'],r['id']))
  check('repair-attempt-link:'+label,r.get('attemptId')==a['attemptId'] and r.get('attemptNo')==(a['attemptNo'] if until_zero else round_no) and r.get('originalResultSha256')==a['originalResultSha256'] and read(folder/'attempt.json')==a)
  if round_no==2 or until_zero:check('repair-previous-link:'+label,r.get('previousAttemptId')==a['previousAttemptId'] and r.get('previousResultSha256')==a['previousResultSha256'])
 check('candidate:'+label,answer==r.get('answer','') and sha(answer)==r['candidateSha256'])
 check('prompt:'+label,r['promptSha256']==sha(prompts[r['id']]))
 if r['grade'].get('valid'):
  g=scorer.judge(answer,book[r['id']]);check('offline-EX:'+label,g==r['grade'])
 if cfg['perQuestionDollarCap'] is not None:check('dollar-cap:'+label,r['budgetSpentUsd']<=cfg['perQuestionDollarCap']+1e-9)
 rr=[x[2] for x in receipts if x[:2]==(r['arm'],r['id'])]
 check('cost-conservation:'+label,math.isclose(sum(x['actualCostUsd'] or 0 for x in rr),r['actualCostUsd'],abs_tol=1e-9)
       and sum(x['unknownCost'] for x in rr)==r['unknownCostCount'] and math.isclose(sum(x['upperBoundUsd'] for x in rr if x['unknownCost']),r['unknownCostUpperBoundUsd'],abs_tol=1e-9))
 if r['arm']!='objrun':
  samples=read(folder/'samples.json') if (folder/'samples.json').exists() else []
  check('sample-ceiling:'+label,len(samples)<=(1 if r['arm']=='baseline' else 5))
  check('EX-early-stop:'+label,not any(s['grade']['passed'] for s in samples[:-1]))
  if samples:
   check('last-delivery:'+label,samples[-1]['answer']==answer)
   for s in samples:check('sample-grade:'+label+'/'+str(s['index']),scorer.judge(s['answer'],book[r['id']])==s['grade'])
 else:
  check('native-evidence:'+label,all((folder/n).exists() for n in ['trace.json','tree.json','tool-permissions.json','engine/data/h2h.sqlite']))
  for f in read(folder/'feedback.json') if (folder/'feedback.json').exists() else []:
   e=f['exposed'];check('native-feedback:'+label+'/'+f['candidateSha256'],set(e)=={'value','note'} and type(e['value']) is bool and e['note'] in ['', 'End with a boxed finite numeric answer in the requested unit.'] and (f['node']=='parsed' or e['note']==''))
  if r['grade'].get('valid'):
   db=sqlite3.connect((folder/'engine/data/h2h.sqlite').as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
   t=db.execute('select * from task').fetchone();deadline=t['created_at']+t['solve_seconds']*1000;candidate=None
   for unit in db.execute('select * from task_repair order by unit desc'):
    for msg in db.execute("select body from agent_bot_msg where instance=? and unit=? and kind='call' and at<=? order by seq desc",(unit['instance'],unit['unit'],deadline)):
     for call in reversed(json.loads(msg['body']).get('calls',[])):
      if call.get('name')=='submit':candidate=call.get('input',{}).get('answer','');break
     if candidate is not None:break
    if candidate is not None:break
   db.close();check('real-submit-before-deadline:'+label,candidate==answer)
  if cfg.get('recoveryFrom'):
   p=read(folder/'recovery-provenance.json')
   check('one-bounded-native-continuation:'+label,p['recoverySessionsAllowed']==1 and p['usedSolveMilliseconds']+p['remainingSolveMilliseconds']==600000)
   first=read(out/'calls'/r['arm']/r['id']/'native-001/attempt-0/request.json')
   check('exact-interrupted-wire-replay:'+label,sha(json.dumps(first,ensure_ascii=False,separators=(',',':')))==p['interruptedRequestSha256'])
actual=sum(r['actualCostUsd'] or 0 for _,_,r in receipts);unknown=sum(r['unknownCost'] for _,_,r in receipts)+len(unsettled);reserve=sum(r['upperBoundUsd'] for _,_,r in receipts if r['unknownCost'])+sum(d['reserveUsd'] for d in unsettled)
stats={a:{'expected':len(catalog),'completed':sum(r['arm']==a for r in records),'valid':sum(r['arm']==a and bool(r['grade'].get('valid')) for r in records),'passed':sum(r['arm']==a and bool(r['grade'].get('valid') and r['grade']['passed']) for r in records),'actualCostUsd':sum(r['actualCostUsd'] or 0 for arm,_,r in receipts if arm==a)} for a in cfg['arms']}
if repair:
 for arm in cfg['arms']:stats[arm]['expected']=sum(a==arm for a,_ in expected)
def record_status(r):
 if r['grade'].get('valid'):return 'valid'
 if r.get('error') or r['grade'].get('outcome')=='infrastructure_error':return 'infrastructure_error'
 if r['grade'].get('outcome')=='no_final_submission':return 'native_no_final_submission'
 return 'other_invalid'
record_status_counts={k:sum(record_status(r)==k for r in records) for k in ['valid','infrastructure_error','native_no_final_submission','other_invalid']}
audit={'allPassed':all(c['passed'] for c in checks),'partial':args.partial,'run':cfg['run'],'checks':len(checks),'failures':[c for c in checks if not c['passed']],'arms':stats,'actualCostUsd':actual,'unknownCostCount':unknown,'unknownCostUpperBoundUsd':reserve,'modelCalls':len(dispatches),'activeUnreceiptedDispatches':len(unsettled),'details':checks}
audit['recordStatusCounts']=record_status_counts
continuation_path=root/'package/continuation.json'
if continuation_path.exists():
 inherited=read(continuation_path)
 audit['continuationAccounting']={'inheritedRecords':inherited['inheritedRecords'],'inheritedKnownUsd':inherited['inheritedKnownUsd'],'inheritedUnknownCount':inherited['inheritedUnknownCount'],'inheritedUnknownReserveUsd':inherited['inheritedUnknownReserveUsd'],'inheritedModelCalls':inherited['inheritedModelCalls'],'newKnownUsd':actual-inherited['inheritedKnownUsd'],'newUnknownCountIncludingActive':unknown-inherited['inheritedUnknownCount'],'newUnknownReserveUsdIncludingActive':reserve-inherited['inheritedUnknownReserveUsd'],'newModelCalls':len(dispatches)-inherited['inheritedModelCalls'],'historicalFeesAlreadyIncludedOnce':True}
name='PROGRESS_AUDIT.json' if args.partial else 'AUDIT.json'
(local/name).write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
with (local/'RESULTS.csv').open('w',newline='',encoding='utf-8-sig') as f:
 fields=['arm','id','valid','passed','outcome','recordStatus','error','actualCostUsd','unknownCostCount','unknownCostUpperBoundUsd','seconds','stoppingReason']
 writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
 for r in records:writer.writerow({k:(r['grade'].get(k) if k in {'valid','passed','outcome'} else record_status(r) if k=='recordStatus' else r.get(k,'')) for k in fields})
lines=[f"# SciBench {cfg['run']}",'',f"状态：{'进行中快照' if args.partial else '完整批次审计'}。",'', '| 组别 | 已完成 | 有效评分 | EX通过 | 已知费用 USD |','|---|---:|---:|---:|---:|']
for arm,s in stats.items():lines.append(f"| {arm} | {s['completed']}/{s['expected']} | {s['valid']} | {s['passed']} | {s['actualCostUsd']:.6f} |")
cost_label='本实验累计已知费用（已含继承，历史请求只计一次）' if continuation_path.exists() else '本批新增已知费用'
lines.extend(['',f'{cost_label} ${actual:.6f}；未知费用 {unknown} 笔，预留 ${reserve:.6f}。',f"核验 {len(checks)} 项，通过：{audit['allPassed']}。",'','模型沿用 SciCode：deepseek-v4.1-flash / DigitalOcean / high / temperature 0 / 16384 tokens。','独立采样与二值反馈最多5个完整答案、EX通过即停；三种多轮方法不设单题费用上限。','ObjRun 保留 c5 / 600秒 / 4分支 / 12 units；异常与答错分别记录。'])
lines.extend(['',f"原始记录分类：有效 {record_status_counts['valid']}；接口/基础设施异常 {record_status_counts['infrastructure_error']}；原生无最终submit {record_status_counts['native_no_final_submission']}；其他无效 {record_status_counts['other_invalid']}。原始grade不改，未提交与接口故障分列。"])
if continuation_path.exists():
 split=audit['continuationAccounting'];lines.extend(['',f"继承 {split['inheritedRecords']} 条结果、{split['inheritedModelCalls']} 笔请求：已知 ${split['inheritedKnownUsd']:.6f}，未知 {split['inheritedUnknownCount']} 笔。",f"本次续跑新增已知 ${split['newKnownUsd']:.6f}；新增未知及在飞 {split['newUnknownCountIncludingActive']} 笔。不能把旧归档费用再加到本报告累计金额上。"])
if cfg.get('recoveryFrom'):
 original=local.parent/'pilot-20261016-v1/AUDIT.json'
 if original.exists():
  old=read(original);audit['originalPilotAccounting']={k:old[k] for k in ['actualCostUsd','unknownCostCount','unknownCostUpperBoundUsd']}
  audit['originalPlusRecoveryKnownUsd']=old['actualCostUsd']+actual
  lines.extend(['',f"原始试跑已知费用 ${old['actualCostUsd']:.6f}、未知 {old['unknownCostCount']} 笔（预留 ${old['unknownCostUpperBoundUsd']:.6f}）完整保留；加本次恢复后已知合计 ${old['actualCostUsd']+actual:.6f}。",'恢复仅继续两条未完成原生断点；原始记录、原始候选和原始归档保持独立，不能把历史复制回执重复计费。'])
  (local/name).write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(local/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in audit.items() if k!='details'},ensure_ascii=False))
if not audit['allPassed']:sys.exit(1)
