from pathlib import Path
import json,datetime,psutil,sys,subprocess,hashlib
ROOT=Path(__file__).resolve().parents[3]
run=Path(sys.argv[1]) if len(sys.argv)>1 else Path((ROOT/'data/lj-conjecture-search/latest-run.txt').read_text().strip())
def read(name):
    try:return json.loads((run/name).read_text(encoding='utf-8'))
    except (ValueError,FileNotFoundError):return None
out={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'run':str(run),'deadline':read('deadline.json'),'status':read('status.json'),'completion':read('completion.json'),'success':read('primary-success.json'),'final_summary_exists':(run/'final/summary.json').exists(),'processes':[]}
for name,info in (read('process.json') or {}).items():
    if not isinstance(info,dict) or 'pid' not in info:continue
    try:
        p=psutil.Process(info['pid']);same=abs(p.create_time()-info['created'])<.5
        out['processes'].append({'name':name,'pid':p.pid,'same_identity':same,'cpu_seconds':sum(p.cpu_times()[:2]),'rss':p.memory_info().rss,'children':[{'pid':c.pid,'name':c.name(),'cpu_seconds':sum(c.cpu_times()[:2])} for c in p.children(recursive=True)] if same else []})
    except psutil.Error:out['processes'].append({'name':name,'pid':info['pid'],'alive':False})
out['recent_work']=sorted([{'name':str(p.relative_to(run/'work')),'bytes':p.stat().st_size,'mtime':datetime.datetime.fromtimestamp(p.stat().st_mtime,datetime.timezone.utc).isoformat()} for p in (run/'work').rglob('*') if p.is_file()],key=lambda x:x['mtime'],reverse=True)[:20]
out['recent_jobs']=[{'file':p.name,'tail':p.read_text(encoding='utf-8',errors='replace')[-2500:]} for p in sorted((run/'jobs').glob('*.log'),key=lambda p:p.stat().st_mtime,reverse=True)[:4]]
sup=read('supervisor-process.json')
if sup:
    try:
        sp=psutil.Process(sup['pid']);out['supervisor']={**sup,'same_identity':abs(sp.create_time()-sup['created'])<.5,'alive':True}
    except psutil.Error:out['supervisor']={**sup,'alive':False}
linux=lambda p:'/mnt/'+str(p)[0].lower()+str(p)[2:].replace('\\','/')
try:
    z=subprocess.run(['wsl','-d','Ubuntu','--','python3',linux(run/'linux_owned.py'),linux(run)],capture_output=True,text=True,timeout=20)
    out['linux_work']=json.loads(z.stdout)
except Exception as e:out['linux_work']={'error':str(e)}
out['frozen_integrity']={n:hashlib.sha256((run/n).read_bytes()).hexdigest()==h for n,h in (read('frozen-g.json') or {}).get('files',{}).items()}
out['bundles']=[]
for p in (run/'verified').glob('*.review-status.json'):
    try:
        item=json.loads(p.read_text(encoding='utf-8'));out['bundles'].append({k:item.get(k) for k in ('bundle_sha256','claim_type','requires_host_review','primary_passed','unproved_steps')})
    except (ValueError,OSError):pass
calls=[]
if (run/'calls.jsonl').exists():
    for line in (run/'calls.jsonl').read_text(encoding='utf-8').splitlines():
        try:calls.append(json.loads(line))
        except ValueError:pass
from decimal import Decimal
responses=[x for x in calls if x.get('event')=='response'];dispatch=[x for x in calls if x.get('event')=='dispatch']
receipt_ids={x['id'] for x in responses if (x.get('usage') or {}).get('cost') is not None}
out['usage']={'requests':len(dispatch),'responses':len(responses),'receipted_cost_usd':str(sum((Decimal(str(x['usage']['cost'])) for x in responses if x['id'] in receipt_ids),Decimal(0))),'no_cost_receipt_ids':[x['id'] for x in dispatch if x['id'] not in receipt_ids],'served_models':sorted(set(x.get('response_model','unknown') for x in responses))}
(run/'monitor.jsonl').open('a',encoding='utf-8').write(json.dumps(out,ensure_ascii=False)+'\n')
print(json.dumps(out,ensure_ascii=True))
