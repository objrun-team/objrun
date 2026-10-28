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
 lines=['# ClimaQA-Gold MCQ 四组全量结果','','固定官方数据集验证通过的 245 题，包含最初 20 题试跑与随后 225 题。各组独立求解；模型使用 DeepSeek 官方 deepseek-flash，局部评分，最多判断两个不同选项。','', '| 方法 | 原始通过 / 245 | 原始未知 | 恢复后通过 / 245 | 恢复后未知 | 总请求数 | 估算费用 USD（低–高） |','|---|---:|---:|---:|---:|---:|---:|']
 for a in ARMS:
  p=per[a];c=allcost[a];lines.append(f"| {a} | {p['originalPassed']} ({p['originalAccuracyLower']*100:.2f}%) | {p['originalUnknown']} | {p['effectivePassed']} ({p['effectiveAccuracyLower']*100:.2f}%) | {p['effectiveUnknown']} | {c['requests']} | {c['low']:.6f}–{c['high']:.6f} |")
 low=sum(x['low'] for x in allcost.values());high=sum(x['high'] for x in allcost.values());unknown=sum(x['unknown'] for x in allcost.values());requests=sum(x['requests'] for x in allcost.values())
 lines+=['',f'全部阶段共 {requests} 次模型请求，费用估算 ${low:.6f}–{high:.6f}，未知费用请求 {unknown} 次。估算使用官方峰值与非峰值美元费率、usage 及缓存信息；实际逐请求账单不可得。',f'原始异常 {len(result["originalExceptionRows"])} 条，其中试跑异常 1 条有单独恢复，全量异常恢复结果 {len(recovery)} 条、有效 {sum(x["valid"] for x in recovery)} 条。原始与恢复结果保留，恢复采用独立全新尝试，不声称原生断点续跑。','',f'完整审计结果：{json.dumps(checks,ensure_ascii=False)}。','','Independent 的最终成绩使用金标早停与选择；Binary 可看到逐轮正误；ObjRun 具备原生工具和正确性反馈。两次不同选项判断的四选一无模型随机不重复枚举参照为 50%。四组并非同费用实验，差异不能单独归因于某个模块。','',f'配对比较：{json.dumps(paired,ensure_ascii=False)}。',f'首个已判断候选：{json.dumps(first,ensure_ascii=False)}。','','机器可读数据、全部逐题原始记录、异常批次和成本分类见同目录 `FINAL_SUMMARY.json`、`results/`、`exception-recovery-v1/` 与两次运行的请求回执。']
 (FULL/'FINAL_REPORT.zh.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps({'allChecksPassed':result['allChecksPassed'],'perArm':per,'costByArm':allcost,'originalExceptions':len(result['originalExceptionRows']),'recoveryRows':len(recovery),'checks':checks},ensure_ascii=False))
if __name__=='__main__':main()
