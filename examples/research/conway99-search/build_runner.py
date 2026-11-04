from pathlib import Path
import shutil,json,hashlib
root=Path(__file__).resolve().parents[3];here=Path(__file__).resolve().parent
run=Path((root/'data/conway99-search/latest-run.txt').read_text().strip())
s=(root/'examples/research/rna-bound-search/run.ts').read_text()
s=s.replace('rna-bound-search','conway99-search').replace('RNA_BACKEND','CONWAY_BACKEND').replace("name: 'rna'","name: 'conway'").replace("agent: 'rna'","agent: 'conway'").replace('rna-five-hours','conway99-five-hours')
s=s.replace('/home/imontlaji/.local/share/objrun-rna-20261030-env','/home/imontlaji/.local/share/objrun-ca-20261030-env')
s=s.replace("const container = 'objrun-rna-'", "const container = 'objrun-conway99-'")
start=s.index("  const supervise = ");end=s.index('\n  return [',start)
s=s[:start]+'''  const supervise = 'import sys,time,subprocess,os,signal\\np=subprocess.Popen(["/bin/bash","-s"],start_new_session=True)\\nend=float(sys.argv[1]);mono=time.monotonic()+max(0,end-time.time())\\nwhile p.poll() is None and time.time()<end and time.monotonic()<mono and not os.path.exists("/control/STOP"): time.sleep(.1)\\nif p.poll() is None:\\n try: os.killpg(p.pid,signal.SIGKILL)\\n except ProcessLookupError: pass\\n p.wait()\\nsys.exit(p.returncode or 0)';''' +s[end:]
s=s.replace("'--bind', linuxPath(work), '/work'", "'--ro-bind', linuxPath(join(originalRun,'control')), '/control', '--bind', linuxPath(work), '/work'")
s=s.replace("put(join(dir,'deadline.json'),deadline); armTimer();", "writeFileSync(join(dir,'deadline.json'),JSON.stringify(deadline,null,2),{flag:'wx'}); put(join(work,'campaign-clock.json'),deadline); armTimer();")
s=s.replace("if (!remaining() || stopping)","if (!remaining() || stopping || existsSync(join(originalRun,'control/STOP')))")
s=s.replace('while (remaining() && !stopping)',"while (remaining() && !stopping && !existsSync(join(originalRun,'control/STOP')))")
a=s.index('  const supervisor=',s.index('async function verifyArtifact'));b=s.index('\n}',a)
s=s[:a]+'''  const checked=await command([python,join(originalRun,'audit.py'),originalRun,artifact]);
  if(checked.code!==0)return {value:false,note:'Host independent audit failed: '+checked.stderr};
  const report=JSON.parse(checked.stdout.trim());
  best=JSON.parse(readFileSync(join(originalRun,'best-verified.json'),'utf8'));
  return {value:Boolean(report?.valid),note:JSON.stringify(report)};''' +s[b:]
s=s.replace('Python RNA (ViennaRNA 2.7.0), numpy/scipy/mpmath and g++ are installed.', 'Python numpy/scipy, OR-Tools CP-SAT, python-sat and g++ are installed.')
s=s.replace('independent_rna_upper_bound_check','independent_conway99_check')
a=s.index('  const recoveryNote=');b=s.index("\n  await api('POST', '/tasks'",a)
s=s[:a]+'''  const description=goal+`\\nHost audit best: ${JSON.stringify(best)}. About ${Math.floor(remaining()/60000)} minutes remain. The immutable first-dispatch clock will be in /work/campaign-clock.json. Start by reading the literature and rooted scaffold. Develop and run useful local CPU searches, inspect exact violation reports, and improve methods. Background jobs must remain foreground shell commands. Save a complete matrix even on interruption; periodically checkpoint in /work/candidates. A proof claim needs a separate certificate and host review. Keep working on the original main objective until independently verified success or deadline.\\n`;
''' +s[b:]
a=s.index('  const smoke = runJob(');b=s.index('\n  if (preflight)',a)
s=s[:a]+'''  const smoke = runJob("python -c 'import numpy,scipy,ortools,pysat; print(\\\"Conway environment ready\\\")'\\ng++ --version | head -n 1");
  await smoke.proc.exited;
  if(smoke.exitCode!==0)throw new Error('Scientific environment preflight failed');
  const audit = await verifyArtifact('{"path":"seed.json"}','preflight');
  if(JSON.parse(audit.note)?.constraint_violations===undefined)throw new Error('Seed independent audit failed');''' +s[b:]
s=s.replace('    await publish();\n    console.log', '''    const auditor=Bun.spawn([python,join(originalRun,'audit.py'),originalRun,'--loop'],{stdin:'ignore',stdout:Bun.file(join(dir,'auditor.stdout.log')),stderr:Bun.file(join(dir,'auditor.stderr.log')),windowsHide:true});
    const auditTime=await command([python,'-c',`import psutil;print(psutil.Process(${auditor.pid}).create_time())`]);
    const info=JSON.parse(readFileSync(join(dir,'process.json'),'utf8'));info.auditor={pid:auditor.pid,created:Number(auditTime.stdout.trim())};put(join(dir,'process.json'),info);
    event({event:'auditor_started',pid:auditor.pid});
    await publish();
    console.log''',1)
s=s.replace('while (remaining() && engine.exitCode === null)',"while (remaining() && engine.exitCode === null && !existsSync(join(originalRun,'control/STOP')))")
s=s.replace("      let task: any;", "      best=JSON.parse(readFileSync(join(originalRun,'best-verified.json'),'utf8'));\n      let task: any;")
s=s.replace("if (remaining() > 0) await publish();", "if (remaining() > 0 && !existsSync(join(originalRun,'control/STOP'))) await publish();")
s=s.replace("if (engine.exitCode !== null && remaining() > 0)","if (engine.exitCode !== null && remaining() > 0 && !existsSync(join(originalRun,'control/STOP')))")
s=s.replace("preflight ? 'preflight_passed' : 'five_hour_deadline'", "preflight ? 'preflight_passed' : existsSync(join(originalRun,'success.json')) ? 'verified_main_success' : 'five_hour_deadline'")
(here/'run.ts').write_text(s)
start=(root/'examples/research/rna-bound-search/start.ps1').read_text().replace('rna-bound-search','conway99-search')
(here/'start.ps1').write_text(start)
monitor=(root/'examples/research/rna-bound-search/monitor.py').read_text().replace('rna-bound-search','conway99-search').replace('agent_rna_msg','agent_conway_msg')
monitor=monitor.replace("'deadline-guard']","'deadline-guard', 'success']")
monitor=monitor.replace('print(json.dumps(out, indent=2, ensure_ascii=False))', '''out['candidate_files']=[{'name':p.name,'bytes':p.stat().st_size,'mtime':p.stat().st_mtime} for p in (run/'work/candidates').glob('*.json')]
out['auditor_error_tail']=(run/'auditor.stderr.log').read_text()[-2000:] if (run/'auditor.stderr.log').exists() else ''
out['verified_count']=len(list((run/'verified').glob('*/report.json')))
out['cpu_seconds']={}
try:
 for name,v in process_info.items():
  if isinstance(v,dict) and 'pid' in v and out.get('process_health',{}).get(name):
   p=psutil.Process(v['pid']);out['cpu_seconds'][name]=sum(p.cpu_times()[:2]);out['cpu_seconds'][name+'_descendants']=[{'pid':c.pid,'name':c.name(),'cpu':sum(c.cpu_times()[:2])} for c in p.children(recursive=True)]
except psutil.Error:pass
(run/'monitoring'/('check-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')).write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(out, indent=2, ensure_ascii=False))''')
(here/'monitor.py').write_text(monitor)
for name in ('run.ts','audit.py','guard.py','finalize.py','monitor.py','start.ps1','rooted.py','test_checkers.py','build_runner.py','prepare.py'):shutil.copy2(here/name,run/name)
(run/'control').mkdir(exist_ok=True)
files=['GOAL.md','LITERATURE.md','checker/check_pairs.py','checker/check_matrix.py','reference/rooted.py','reference/test_checkers.py']
(run/'frozen-g.json').write_text(json.dumps({'files':{p:hashlib.sha256((run/p).read_bytes()).hexdigest() for p in files}},indent=2))
(run/'host-code-manifest.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in here.iterdir() if p.is_file()},indent=2))
print(run)
