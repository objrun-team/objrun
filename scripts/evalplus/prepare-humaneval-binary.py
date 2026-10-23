"""Freeze a separate binary-feedback experiment; never rewrite earlier arms."""
import hashlib,json,pathlib,datetime
ROOT=pathlib.Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/evalplus-20261012/humaneval/binary-v1'
OUT.mkdir(parents=True,exist_ok=True)
def save(name,value):
    path=OUT/name
    text=json.dumps(value,indent=2,ensure_ascii=False)+'\n'
    if path.exists() and path.read_text(encoding='utf-8')!=text:
        raise RuntimeError('Existing preparation differs: '+str(path))
    path.write_text(text,encoding='utf-8')
cfg={
    'protocolVersion':'humaneval-base-binary-max5-v1','dataset':'humaneval','count':164,
    'datasetVersion':'v0.1.10','evaluatorVersion':'0.3.1',
    'model':'deepseek/deepseek-v4.1-flash','provider':'DigitalOcean','fallbacks':False,
    'temperature':0,'reasoning':'enabled/high','maxTokens':16384,'seedWire':None,
    'concurrency':2,'maxChecks':5,'feedbackTests':'base','feedbackValues':['passed','failed'],
    'history':'same public prompt plus own prior answers and binary base verdicts only',
    'stopPolicy':'first base pass or fifth check; choose first base pass else fifth candidate',
    'finalScoring':'frozen selected candidate; official EvalPlus base+plus; plus never used for feedback or stopping',
    'perTaskDollarCap':None,'costPolicy':'retain actual usage.cost and unknown upper bounds; respect existing account/key limits',
    'interfaceRetriesPerSample':3,'invalidGrades':'retry same saved candidate, never emit failed for environment faults',
    'graderPort':17963,'httpProxy':'http://127.0.0.1:10809','dockerForbidden':True,
    'executor':'WSL Ubuntu Python3.12 venv; unchanged Linux Landlock+seccomp UID65534 worker',
    'referenceBinaryProtocol':'scripts/code-benchmarks/bird/run.ts; common.ts binaryFeedback',
    'referenceHumanEvalProtocol':'docs/evalplus-20261012/humaneval/config.json; full baseline request'
}
save('config.json',cfg)
old=json.loads((ROOT/'docs/evalplus-20261012/source-pins.json').read_text(encoding='utf-8-sig'))
selected=[]
for item in old['files']:
    p=pathlib.Path(item['path'])
    if '/vendor/' in p.as_posix() or '/pure-deps/' in p.as_posix() or p.name in ['HumanEvalPlus.jsonl','MbppPlus.jsonl','grade.py','grader_service.py','worker.py','codec.py','sandbox.py']:
        if hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:
            raise RuntimeError('Original grading source changed: '+str(p))
        selected.append(p)
selected += [ROOT/'scripts/evalplus'/name for name in [
    'prepare-humaneval-binary.py','humaneval-binary-policy.ts','humaneval-binary-policy.test.ts',
    'run-humaneval-binary.ts','start-humaneval-binary.ps1','start-humaneval-binary-grader.sh','control-humaneval-binary.py']]
selected += [OUT/'config.json',ROOT/'docs/evalplus-20261012/humaneval/public-tasks.json',
    ROOT/'docs/evalplus-20261012/humaneval/task-ids.json',
    ROOT/'docs/evalplus-20261012/humaneval/full/calls/baseline/HumanEval-0/sample-0/attempt-0/request.json',
    ROOT/'scripts/benchmark-campaign/full-f/shared/digitalocean-provider.ts',
    ROOT/'scripts/benchmark-campaign/full-f/shared/digitalocean-inference.ts']
files=[{'path':str(p.resolve()),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(set(selected))]
save('source-pins.json',{'protocol':cfg['protocolVersion'],'originalGradingSourcesVerified':True,'files':files})
print(json.dumps({'prepared':str(OUT),'pinnedFiles':len(files),'modelCalls':0}))
