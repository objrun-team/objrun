"""Stage an owned engine copy; never alter another experiment or its dependencies."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
from protocol import REVISION, PARAMETERS, PROTOCOL_SHA, JUDGE_SYSTEM

REPO = Path(__file__).resolve().parents[3]
ROOT = REPO.parent / 'tmp/frontierscience-formal-20261016-v1-deepseek-c32'
ORIGIN = REPO.parent / 'tmp/scibench-formal-20261016-v1/package/engine'
package = ROOT / 'package'
package.mkdir(parents=True, exist_ok=True)
for p in Path(__file__).parent.iterdir():
    if p.suffix in {'.py', '.ts'}: shutil.copy2(p, package/p.name)
engine = package / 'engine'
if not engine.exists():
    shutil.copytree(ORIGIN, engine, ignore=shutil.ignore_patterns('node_modules', '__pycache__', '.env'))
changes=[]
def change(rel, before, after):
    p=engine/rel
    original=p.read_text(encoding='utf-8')
    if after in original and before not in original:return
    if before not in original:raise RuntimeError('PatchAnchorMissing:'+rel)
    updated=original.replace(before, after)
    p.write_text(updated,encoding='utf-8')
    changes.append({'path':rel,'beforeSha256':hashlib.sha256(original.encode()).hexdigest(),'afterSha256':hashlib.sha256(updated.encode()).hexdigest()})
change('app/src/llm/index.ts', 'officialOpenRouter', 'officialDeepSeek')
change('app/src/llm/index.ts', 'vendor === "openrouter" && model === "deepseek/deepseek-v4.1-flash"', 'vendor === "deepseek" && model === "deepseek-flash"')
change('app/src/llm/index.ts', 'extra.provider = { only: ["digitalocean"], allow_fallbacks: false, max_price: { prompt: 0.3, completion: 1.2 } };\n        extra.reasoning = { enabled: true, effort: "high", exclude: false };', 'extra.thinking = { type: "enabled" };')
change('test/_lib.ts', 'env: { ...process.env, TGENGIN_CONFIG: join(dir, "config.yaml") }', 'env: { PATH: process.env.PATH, HOME: process.env.HOME, NO_PROXY: "127.0.0.1,localhost", DEEPSEEK_API_KEY: "local-bridge-placeholder", TGENGIN_CONFIG: join(dir, "config.yaml") }')
change('app/src/objective/tool.ts', 'expectMs: 120_000', 'expectMs: 600_000')
change('app/src/llm/index.ts', 'maxRetries: RETRIES', 'maxRetries: 0')
change('app/src/main.ts', '["deepseek", "deepseek-v4-flash", "chat,tools"]', '["deepseek", "deepseek-flash", "chat,tools"]')
config={'run':ROOT.name,'benchmark':'FrontierScience-Olympiad','dataRevision':REVISION,
 'dataPath':'olympiad/test.jsonl','taskCount':100,'arms':['baseline','objrun'],
 'parameters':PARAMETERS,'protocolSha256':PROTOCOL_SHA,'apiBase':'https://api.deepseek.com',
 'modelMapping':'DeepSeek-V4.1-Flash; rolling alias observed 2026-10-16; not an immutable model pin',
 'solveSeconds':600,'checksPerAttempt':5,'maxBranches':4,'cyclesMaxUnits':12,
 'taskConcurrency':32,'apiConcurrency':32,'solveApiConcurrency':24,'graderApiConcurrency':8,
 'logicalCallMaxAttempts':3,'judgeTimeoutSeconds':600,'temperatureEffective':'ignored in thinking mode; omitted on wire',
 'priceUsdPerMillion':{'offpeak':{'hit':.003,'miss':.15,'output':.6},'peak':{'hit':.006,'miss':.3,'output':1.2}},
 'pricingSource':'https://api-docs.deepseek.com/quick_start/pricing/','priceObservedDate':'2026-10-16',
 'peakHoursUtc':[[1,4],[6,10]],'holidayRule':'Chinese public holidays are offpeak; 2026-10-16 is an ordinary Friday',
 'toolPolicy':['submit','verify','task_tree','node_load'],
 'finalJudge':'one new request per arm/id using frozen protocol; no online cache; same-model consistency only',
 'failureRules':{'empty':'valid model failure; never substitute reasoning_content','length':'retain visible content as delivered; empty remains empty; grader length is invalid','no_submission':'valid task failure with empty frozen candidate','transport':'infrastructure exception; preserve candidate; never regenerate completed model output','judge_parse':'scoring exception; never default to incorrect'},
 'statistics':{'pairedBootstrapReplicates':20000,'seed':20261016,'unit':'question','scope':'one run of fixed100; question uncertainty, not run-to-run variability'},
 'authorization':'user 2026-10-16: complete integration, controls, independent novaeve deployment, official DeepSeek only, formal100x2, 15-minute follow-up and verified retrieval'}
(package/'experiment.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(package/'judge-system.txt').write_text(JUDGE_SYSTEM,encoding='utf-8')
origin={'origin':str(ORIGIN),'snapshot':'audited SciCode engine as copied into SciBench staging; isolated changes only','changes':changes,
 'files':[{'path':str(p.relative_to(engine)).replace('\\','/'),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(engine.rglob('*')) if p.is_file()]}
(package/'engine-origin.json').write_text(json.dumps(origin,indent=2)+'\n')
print(json.dumps({'root':str(ROOT),'engineFiles':len(origin['files']),'patches':len(changes),'protocolSha256':PROTOCOL_SHA}))
