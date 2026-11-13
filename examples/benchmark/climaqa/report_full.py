"""Read-only audit and report across pilot, main and the separate recovery batch."""
import collections, datetime, json, pathlib, re
import run
ROOT=run.ROOT;PILOT=ROOT/'docs/climaqa/pilot-20261028-v1';FULL=ROOT/'docs/climaqa/full-20261028-v1';ARMS=run.ARMS
def records(path):return [run.read(p) for p in (path/'results').glob('*/*.json')]
def costs(path):
 result={a:{'requests':0,'prompt':0,'completion':0,'low':0.,'high':0.,'unknown':0} for a in ARMS}
 for p in (path/'calls').glob('*/*/*/dispatch.json'):
  a=p.relative_to(path/'calls').parts[0];o=result[a];o['requests']+=1;receipt=p.with_name('receipt.json')
  if not receipt.exists():o['unknown']+=1;continue
  r=run.read(receipt);u=r.get('usage') or {};o['prompt']+=u.get('prompt_tokens',0);o['completion']+=u.get('completion_tokens',0)
  if r.get('estimate') is None:o['unknown']+=1
  else:o['low']+=r['estimate']['lowerUsd'];o['high']+=r['estimate']['upperUsd']
 return result
def main():
 if not (FULL/'finished.json').exists():raise RuntimeError('MainAndRecoveryNotFinished')
 public=run.read(PILOT/'public.json')+run.read(FULL/'public.json');book={x['id']:x['answer'] for root in (PILOT,FULL) for x in run.read(root/'private.json')};ids={x['id'] for x in public};complexity={x['id']:x['complexity'] for x in public}
 original=records(PILOT)+records(FULL);assert len(ids)==245 and len(original)==980
 original_map={(r['arm'],r['id']):r for r in original};assert len(original_map)==980 and set(original_map)=={(a,i) for a in ARMS for i in ids}
 recovery=records(FULL/'exception-recovery-v1');replacement={(x['arm'],x['id']):x for x in recovery if x['valid']}
 pilot_recovery=run.read(PILOT/'recovery-271-v1/result.json');assert pilot_recovery['valid'];replacement[('objrun',pilot_recovery['id'])]=pilot_recovery
 effective=dict(original_map);effective.update(replacement)
 checks={};pins=run.read(FULL/'source-pins.json')['files'];checks['sourcePins']=all(run.sha((ROOT/p).read_bytes())==s for p,s in pins.items())
 checks['scope']=len(ids)==245 and len(original_map)==980
 checks['goldMapping']=all(not r['valid'] or r['grade']['passed']==(run.parse(r['answer'])==book[r['id']]) for r in original)
 checks['candidateHash']=all(run.sha(r['answer'])==r['answerSha256'] for r in original)
 checks['twoDistinctLimit']=all(r['distinctJudgments']<=2 for r in original)
 checks['recoveryEligibility']=all(not original_map[(r['arm'],r['id'])]['valid'] for r in recovery)
 checks['recoveryGold']=all(not r['valid'] or r['grade']['passed']==(run.parse(r['answer'])==book[r['id']]) for r in recovery)
 checks['pilotRecovery']=pilot_recovery['cumulativeDistinctJudgments']<=2 and pilot_recovery['grade']['passed']==(run.parse(pilot_recovery['native']['answer'])==book[pilot_recovery['id']])
 per={};first={}
 for arm in ARMS:
  orig=[original_map[(arm,i)] for i in ids];eff=[effective[(arm,i)] for i in ids];v=[x for x in eff if x['valid']];p=sum(x.get('grade',{}).get('passed',False) for x in v);u=245-len(v)
  op=sum(x.get('grade',{}).get('passed',False) for x in orig if x['valid']);ou=sum(not x['valid'] for x in orig)
  per[arm]={'originalPassed':op,'originalUnknown':ou,'originalAccuracyLower':op/245,'originalAccuracyUpper':(op+ou)/245,'effectivePassed':p,'effectiveValid':len(v),'effectiveUnknown':u,'effectiveAccuracyLower':p/245,'effectiveAccuracyUpper':(p+u)/245,'levels':{k:{'n':sum(complexity[x['id']]==k for x in eff),'passed':sum(x['valid'] and x.get('grade',{}).get('passed',False) and complexity[x['id']]==k for x in eff),'unknown':sum(not x['valid'] and complexity[x['id']]==k for x in eff)} for k in ('BASE','REASONING','HYPOTHETICAL')}}
  fpassed=fknown=0
  for r in orig:
   if arm=='objrun':
    root=PILOT if r['id'] in {x['id'] for x in run.read(PILOT/'public.json')} else FULL;f=root/'tasks'/arm/r['id']/'feedback.json';fx=run.read(f) if f.exists() else []
    answers=[run.parse(x['candidate']) for x in fx if x['node']=='/correct' and run.parse(x['candidate'])]
    if answers:fknown+=1;fpassed+=answers[0]==book[r['id']]
    if r['valid']:
     tree=run.read(root/'tasks'/arm/r['id']/'tree.json');verdict=r.get('engineVerdict') or {}
     if r.get('candidateHow')=='submitted' and not (any(x.get('cycle')=='submit' and x.get('done')==1 for x in tree) and verdict.get('valid') and bool(verdict.get('pass'))==r['grade']['passed']):checks['nativeHandin']=False
   elif r.get('samples'):
    fknown+=1;fpassed+=r['samples'][0]['grade']['passed']
  first[arm]={'known':fknown,'passed':fpassed}
 checks.setdefault('nativeHandin',True)
 # Across main and recovery, observe all journaled correctness decisions for a task.
 journal={}
 for root in (FULL,FULL/'exception-recovery-v1'):
  for p in (root/'judgments').glob('*/*.jsonl'):
   key=(p.parent.name,p.stem);journal.setdefault(key,set()).update(json.loads(x)['answer'] for x in p.read_text(encoding='utf-8').splitlines())
 checks['acrossRecoveryBudget']=all(len(x)<=2 for x in journal.values())
 costroots={'pilot':PILOT,'pilotRecovery':PILOT/'recovery-271-v1','main':FULL,'mainRecovery':FULL/'exception-recovery-v1'}
 # Pilot recovery has a native result but its calls share the standard layout.
 costtable={name:costs(path) for name,path in costroots.items()}
 allcost={a:{k:sum(costtable[n][a][k] for n in costtable) for k in ('requests','prompt','completion','low','high','unknown')} for a in ARMS}
 checks['noUnsettledRequests']=all(not any(not x.with_name('receipt.json').exists() for x in (path/'calls').glob('*/*/*/dispatch.json')) for path in costroots.values())
 checks['allSuccessfulRecoveriesValid']=all(x['valid'] for x in recovery)
 paired={}
 for a,b in [('objrun','binary'),('binary','independent'),('objrun','baseline')]:
  both=[(effective[(a,i)],effective[(b,i)]) for i in ids];complete=[(x,y) for x,y in both if x['valid'] and y['valid']]
  paired[a+'-minus-'+b]={'completePairs':len(complete),'onlyFirst':sum(x['grade']['passed'] and not y['grade']['passed'] for x,y in complete),'onlySecond':sum(y['grade']['passed'] and not x['grade']['passed'] for x,y in complete),'unknownPairs':245-len(complete)}
 result={'atUtc':run.now(),'checks':checks,'allChecksPassed':all(checks.values()),'perArm':per,'firstCandidate':first,'paired':paired,'costByPhase':costtable,'costByArm':allcost,'recoveryRows':len(recovery),'recoveryValid':sum(x['valid'] for x in recovery),'originalExceptionRows':[{'arm':r['arm'],'id':r['id'],'error':r.get('error')} for r in original if not r['valid']]}
 run.save(FULL/'FINAL_SUMMARY.json',result)
 lines=['# ClimaQA-Gold MCQ full four-arm results','','245 tasks verified against the pinned official dataset, including the initial 20-task pilot and subsequent 225 tasks. Each arm solves independently, using official DeepSeek deepseek-flash, local grading, and at most two distinct option checks.','', '| Method | Original passes / 245 | Original unknowns | Post-recovery passes / 245 | Post-recovery unknowns | Total requests | Estimated cost USD (low–high) |','|---|---:|---:|---:|---:|---:|---:|']
 for a in ARMS:
  p=per[a];c=allcost[a];lines.append(f"| {a} | {p['originalPassed']} ({p['originalAccuracyLower']*100:.2f}%) | {p['originalUnknown']} | {p['effectivePassed']} ({p['effectiveAccuracyLower']*100:.2f}%) | {p['effectiveUnknown']} | {c['requests']} | {c['low']:.6f}–{c['high']:.6f} |")
 low=sum(x['low'] for x in allcost.values());high=sum(x['high'] for x in allcost.values());unknown=sum(x['unknown'] for x in allcost.values());requests=sum(x['requests'] for x in allcost.values())
 lines+=['',f'Across all phases: {requests} model requests, estimated cost ${low:.6f}–{high:.6f}, and {unknown} requests with unknown cost. Estimates use official peak/off-peak dollar rates, usage, and cache information; actual per-request billing is unavailable.',f'Original anomalies: {len(result["originalExceptionRows"])}. One pilot anomaly has separate recovery; full-run recovery contains {len(recovery)} results, {sum(x["valid"] for x in recovery)} valid. Original and recovery results are preserved; recovery uses fresh independent attempts, not native checkpoint continuation.','',f'Complete audit results: {json.dumps(checks,ensure_ascii=False)}.','','Independent final scores use gold-label early stopping and selection; Binary sees round-level correctness; ObjRun has native tools and correctness feedback. The model-free reference for two distinct checks among four options is 50% success under random enumeration without replacement. The four arms are not cost-matched, so differences cannot be attributed solely to one module.','',f'Paired comparison: {json.dumps(paired,ensure_ascii=False)}.',f'First graded candidate: {json.dumps(first,ensure_ascii=False)}.','','Machine-readable data, all original per-task records, exception batches, and cost categories are in FINAL_SUMMARY.json, results/, exception-recovery-v1/, and both runs’ request receipts.']
 (FULL/'FINAL_REPORT.zh.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps({'allChecksPassed':result['allChecksPassed'],'perArm':per,'costByArm':allcost,'originalExceptions':len(result['originalExceptionRows']),'recoveryRows':len(recovery),'checks':checks},ensure_ascii=False))
if __name__=='__main__':main()
