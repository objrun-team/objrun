"""Prepare an adapter-only change; never edit sources loaded by a live runner."""
import json,pathlib
root=pathlib.Path(__file__).resolve().parent
stage=root/'concurrency-8-stage';stage.mkdir(exist_ok=True)
text=(root/'run.ts').read_text(encoding='utf8')
replacements={
"import {requestTimeoutMs,canaryReady,retainedTaskAttempts} from './interface-policy.ts';":"import {requestTimeoutMs,canaryReady,retainedTaskAttempts} from './interface-policy.ts';\nimport {TaskSlots} from './task-slots.ts';",
"const hash=(x:string|Buffer)=>":"const CONCURRENCY=Number(cfg.concurrency??cfg.initialConcurrency);\nconst taskSlots=new TaskSlots(CONCURRENCY);\nconst hash=(x:string|Buffer)=>",
"concurrency:2,perTaskDollarCap:null":"concurrency:CONCURRENCY,perTaskDollarCap:null",
"Grader PID: ${graderPid??'starting'}.":"Grader PID: ${graderPid??'starting'}. Total shared task concurrency: ${CONCURRENCY}; grader concurrency: ${cfg.graderConcurrency??2}. User requested concurrency 8 on 2026-10-14.",
"async function taskRun(task:any,arm:string){":"async function taskRun(task:any,arm:string){\n const p=join(OUT,'results',arm,task.officialId+'.json');if(existsSync(p)&&read(p).grade?.valid)return;\n return taskSlots.run(()=>taskRunInside(task,arm));\n}\nasync function taskRunInside(task:any,arm:string){",
"async function runBatch(jobs:any[],concurrency=2)":"async function runBatch(jobs:any[],concurrency=CONCURRENCY)",
"for(let i=0;i<jobs.length&&!shouldStop();i+=4)await runBatch(jobs.slice(i,i+4),1);":"for(let i=0;i<jobs.length&&!shouldStop();i+=CONCURRENCY*2)await runBatch(jobs.slice(i,i+CONCURRENCY*2),CONCURRENCY);",
}
for old,new in replacements.items():
    assert text.count(old)==1,(old,text.count(old))
    text=text.replace(old,new)
(stage/'run.ts.pending').write_text(text,encoding='utf8')
cfg=json.loads((root/'experiment.json').read_text(encoding='utf8'));cfg['concurrency']=8;cfg['graderConcurrency']=8
(stage/'experiment.json.pending').write_text(json.dumps(cfg,indent=2)+'\n',encoding='utf8')
grader=(root/'grader_service.py').read_text(encoding='utf8')
assert grader.count('guard = threading.Semaphore(2)')==1
grader=grader.replace('guard = threading.Semaphore(2)',"guard = threading.Semaphore(CONFIG.get('graderConcurrency', CONFIG.get('concurrency', 2)))")
(stage/'grader_service.py.pending').write_text(grader,encoding='utf8')
start=(root/'start.ps1').read_text(encoding='utf8')
assert start.count('concurrency=2}')==1
start=start.replace("$ceStamp=Get-Date", "$ceCfg=Get-Content -LiteralPath (Join-Path $ceRoot 'examples/benchmark/code-benchmarks/classeval/experiment.json') -Raw|ConvertFrom-Json\n$ceStamp=Get-Date").replace('concurrency=2}', 'concurrency=$ceCfg.concurrency}')
(stage/'start.ps1.pending').write_text(start,encoding='utf8')
print(json.dumps({'prepared':True,'sharedTaskConcurrency':8,'graderConcurrency':8,'liveSourcesModified':False}))
