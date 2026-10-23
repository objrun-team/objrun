import json,os,pathlib,subprocess,sys,time
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'outputs';OUT.mkdir(parents=True,exist_ok=True)
q=json.load(sys.stdin);key=q.pop('key');assert isinstance(key,str) and key.strip()
lp=OUT/'launch.json'
if lp.exists():
    old=json.loads(lp.read_text());p=pathlib.Path('/proc')/str(old['pid'])/'cmdline'
    if p.exists() and str(ROOT/'package/run.py').encode() in p.read_bytes():print(json.dumps({'alreadyRunning':True,'pid':old['pid']}));raise SystemExit(0)
env={'PATH':str(ROOT/'bin')+':'+str(ROOT/'runtime/bin')+':/usr/bin:/bin','OPENROUTER_API_KEY':key,'PYTHONUTF8':'1','NO_PROXY':'127.0.0.1,localhost','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
with (OUT/'controller.stdout.log').open('ab') as out,(OUT/'controller.stderr.log').open('ab') as err:
    p=subprocess.Popen([str(ROOT/'runtime/bin/python'),str(ROOT/'package/run.py')],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
v={'pid':p.pid,'root':str(ROOT),'entry':'package/run.py','atUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'credentialWritten':False,'metadata':q};lp.write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v))
