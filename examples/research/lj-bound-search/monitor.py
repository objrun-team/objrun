from pathlib import Path
import json,datetime,psutil,sys
ROOT=Path(__file__).resolve().parents[3]
run=Path(sys.argv[1]) if len(sys.argv)>1 else Path((ROOT/'data/lj-bound-search/latest-run.txt').read_text().strip())
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
(run/'monitor.jsonl').open('a',encoding='utf-8').write(json.dumps(out,ensure_ascii=False)+'\n')
print(json.dumps(out,ensure_ascii=False))
