"""Build a new isolated package from the verified frozen engine and pinned data."""
from pathlib import Path
import ast
import json
import shutil
import sys
from protocol import NAME,REVISION,UPSTREAM,DATA_SHA,PARAMETERS,RULES,PROTOCOL_SHA,digest,TOOLS

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO.parent/'tmp'/NAME
RESEARCH=REPO.parent/'tmp/olympiadbench-design-20261017'
ORIGIN=REPO/'docs/frontierscience/frontierscience-formal-20261016-v1-deepseek-c32/frozen-source/package/engine'

def main():
    if ROOT.exists():raise RuntimeError('ExistingStageInspectNoOverwrite')
    package=ROOT/'package';package.mkdir(parents=True)
    for p in Path(__file__).parent.iterdir():
        if p.suffix in {'.py','.ts'}:shutil.copy2(p,package/p.name)
    engine=package/'engine';shutil.copytree(ORIGIN,engine,ignore=shutil.ignore_patterns('node_modules','__pycache__','.env'))
    lib=engine/'test/_lib.ts';s=lib.read_text(encoding='utf-8')
    s=s.replace('mkdtempSync, rmSync, writeFileSync','mkdtempSync, rmSync, writeFileSync, appendFileSync')
    s=s.replace('[`--env-file=', '["--no-install", `--env-file=')
    s=s.replace('proc.stdout?.on("data", (d: Buffer) => (log += d.toString()));','proc.stdout?.on("data", (d: Buffer) => { log += d.toString(); appendFileSync(join(dir,"engine.stdout.log"),d); });')
    s=s.replace('proc.stderr?.on("data", (d: Buffer) => (log += d.toString()));','proc.stderr?.on("data", (d: Buffer) => { log += d.toString(); appendFileSync(join(dir,"engine.stderr.log"),d); });')
    start=s.index('  for (let i = 0; i < 100; i++) {');end=s.index('\n  const call =',start)
    s=s[:start]+'''  const readyDeadline = Date.now()+60000;
  while (true) {
    try { if ((await fetch(`${base}/health`, {signal:AbortSignal.timeout(1000)})).ok) break; } catch {}
    if (proc.exitCode !== null || proc.signalCode !== null || Date.now()>=readyDeadline) {
      proc.kill(); throw new Error(`Engine startup failed: ${log}`);
    }
    await Bun.sleep(100);
  }
''' +s[end:]
    lib.write_text(s,encoding='utf-8')
    vendor=package/'vendor';vendor.mkdir()
    for source,name in [('inference/code/math_judger.py','math_judger.py'),('inference/judge.py','judge.py'),
        ('inference/code/evaluators/evaluator.py','evaluator.py'),('eval/scoring_examples.json','scoring_examples.json')]:
        shutil.copy2(RESEARCH/'upstream'/source,vendor/name)
    # Extract the exact prompt builder without importing the obsolete model SDKs.
    tree=ast.parse((vendor/'evaluator.py').read_text(encoding='utf-8'))
    wanted=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef,ast.Assign))]
    scope={};exec(compile(ast.Module(body=wanted,type_ignores=[]),'official_prompt','exec'),scope)
    evaluator=scope['Evaluator']('deepseek-flash');evaluator.is_chinese=False;evaluator.is_math=False;evaluator.is_theorem_proving=False
    rows=json.loads((RESEARCH/'frozen-rows.json').read_text(encoding='utf-8'))
    data=ROOT/'data';data.mkdir()
    raw=RESEARCH/'hf/OlympiadBench/OE_TO_physics_en_COMP/OE_TO_physics_en_COMP.parquet'
    assert digest(raw.read_bytes())==DATA_SHA
    shutil.copy2(raw,data/'original.parquet')
    public=[];private=[];manifest=[]
    for index,r in enumerate(rows):
        tid='olympiadbench-physics-en-'+str(r['id'])
        prompt=evaluator.make_prompt(r)+'\n'+((r['context']+'\n') if r.get('context') else '')+r['question']
        public.append({'id':tid,'originalId':r['id'],'prompt':prompt,'subfield':r['subfield'],'answerType':r['answer_type'],'multiple':r['is_multiple_answer']})
        private.append({**{k:r[k] for k in ['question','context','answer_type','final_answer','error']},'id':tid,'originalId':r['id']})
        manifest.append({'id':tid,'originalId':r['id'],'sourceRow':index,'promptSha256':digest(prompt)})
    assert len(public)==len({r['id'] for r in public})==236
    fields=list(dict.fromkeys(r['subfield'] for r in public));canary=[]
    for field in fields:canary.append(next(r['id'] for r in public if r['subfield']==field))
    for predicate in [lambda r:r['multiple'],lambda r:'Equation' in r['answerType'],lambda r:',' in r['answerType']]:
        canary.append(next(r['id'] for r in public if r['id'] not in canary and predicate(r)))
    assert len(set(canary))==8
    for name,value in [('public-tasks.json',public),('private-tasks.json',private),('manifest.json',manifest),
        ('source.json',{'revision':REVISION,'fileSha256':DATA_SHA,'count':236,'upstream':UPSTREAM,'canaryIds':canary,'canarySelection':'first released row per subfield, then first unused multiple, Equation, mixed-type; fixed before API calls; included in formal236'})]:
        (data/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    cfg={'run':NAME,'benchmark':'OlympiadBench Physics EN Text 236','dataRevision':REVISION,'taskCount':236,'arms':['baseline','objrun'],
        'parameters':PARAMETERS,'rules':RULES,'protocolSha256':PROTOCOL_SHA,'expectedModelMapping':'DeepSeek-V4.1-Flash-1017',
        'solveSeconds':600,'engineStartupSeconds':60,'checksPerAttempt':5,'maxBranches':4,'cyclesMaxUnits':12,
        'taskConcurrency':16,'modelConcurrency':16,'graderConcurrency':4,'toolPolicy':TOOLS,'logicalCallMaxAttempts':3,
        'perQuestionDollarCap':None,'batchBudgetUsd':None,'pythonPackages':RULES['deps'],
        'priceUsdPerMillion':{'offpeak':{'hit':.003,'miss':.15,'output':.6},'peak':{'hit':.006,'miss':.3,'output':1.2}},
        'peakHoursUtc':[[1,4],[6,10]],'priceObservedDate':'2026-10-17','statistics':{'seed':20261017,'replicates':20000,'stratify':'subfield'},
        'authorization':'User requested integration, zero-model acceptance, 8x2 canary then full236x2 on novaeve; official DeepSeek; complete retrieval of results/logs/costs.'}
    (package/'experiment.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    prov=ROOT/'provenance';prov.mkdir()
    (prov/'engine-origin.json').write_text(json.dumps({'source':str(ORIGIN),'engineSourceFiles':{p.relative_to(engine).as_posix():digest(p.read_bytes()) for p in engine.rglob('*') if p.is_file()},'changes':['test/_lib.ts: no-install, owned logs, bounded 60-second readiness']},indent=2)+'\n',encoding='utf-8')
    for name in ['pricing','thinking','completion']:
        shutil.copy2(RESEARCH/(name+'.html'),prov/(name+'.html'))
    print(json.dumps({'stage':str(ROOT),'canaryIds':canary,'publicCount':len(public)}))

if __name__=='__main__':main()
