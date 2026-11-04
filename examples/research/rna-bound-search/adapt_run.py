from pathlib import Path
HERE=Path(__file__).resolve().parent
s=(HERE.parent/'quadrature-search/run.ts').read_text(encoding='utf-8')
s=s.replace('quadrature-search','rna-bound-search').replace('QUADRATURE_BACKEND','RNA_BACKEND').replace('objrun-quadrature','objrun-rna').replace("'quadrature'","'rna'").replace('quadrature-five-hours','rna-five-hours')
s=s.replace("const hard = priorDeadline", "let hard = priorDeadline").replace('const deadline = priorDeadline','let deadline = priorDeadline')
s=s.replace("put(join(dir, 'deadline.json'), deadline);", "if (preflight || priorDeadline) put(join(dir, 'deadline.json'), deadline);")
s=s.replace('const hardTimer=setTimeout(()=>{','let hardTimer: any;\nfunction armTimer() { clearTimeout(hardTimer); hardTimer=setTimeout(()=>{')
s=s.replace('},Math.max(1,remaining()));','},Math.max(1,remaining())); }\narmTimer();',1)
insert='''
function startPaidClock() {
  if (preflight) throw new Error('Paid requests are prohibited in --check');
  if (existsSync(join(dir,'deadline.json'))) return;
  const first=Date.now(); hard=first+18_000_000;
  deadline={started_utc:new Date(first).toISOString(),deadline_utc:new Date(hard).toISOString(),deadline_epoch:hard/1000,duration_seconds:18000,model,only_campaign_budget:'elapsed time; begins immediately before first paid dispatch'};
  put(join(dir,'deadline.json'),deadline); armTimer();
  event({event:'first_paid_dispatch_clock',...deadline});
}
'''
s=s.replace("const token = randomBytes",insert+"\nconst token = randomBytes")
# Make the monotonic clock anchor agree exactly with first dispatch.
s=s.replace('const start = Date.now(), monotonicStart = performance.now();','const start = Date.now(); let clockWall=start, monotonicStart=performance.now();')
s=s.replace('hard-start-(performance.now()-monotonicStart)','hard-clockWall-(performance.now()-monotonicStart)')
s=s.replace('const first=Date.now(); hard=first+18_000_000;','const first=Date.now(); clockWall=first; monotonicStart=performance.now(); hard=first+18_000_000;')
s=s.replace("const id = ++nextRequest, ctl = new AbortController();", "startPaidClock();\n      const id = ++nextRequest, ctl = new AbortController();")
s=s.replace("if (res.ok && parsed.choices?.length) return parsed;", "if (res.ok && parsed.choices?.length) { if(parsed.model !== model) throw new Error('Provider returned unexpected model '+parsed.model); return parsed; }")
start=s.index('async function verifyArtifact(');end=s.index('\nasync function serializedVerify',start)
s=s[:start]+'''async function verifyArtifact(answer: string, taskId: string) {
  let descriptor: any;
  try { descriptor=JSON.parse(answer); } catch { return {value:false,note:'Expected JSON {"path":"candidate.json"}'}; }
  if(typeof descriptor?.path!=='string') return {value:false,note:'Missing path'};
  const p=descriptor.path.replace(/^\\/work\\//,'');
  if(isAbsolute(p)||p.split(/[\\\\/]/).includes('..')) return {value:false,note:'Path must remain inside /work'};
  let text:string;
  try {const actual=realpathSync(join(work,p)),rel=relative(realpathSync(work),actual);if(rel.startsWith('..')||isAbsolute(rel))throw Error('outside workspace');text=readFileSync(actual,'utf8').replace(/^\\uFEFF/,'');}
  catch(e){return {value:false,note:String(e)};}
  const hash=createHash('sha256').update(text).digest('hex');
  const artifact=join(dir,'verified',hash+'.candidate.json'),reportPath=join(dir,'verified',hash+'.json');
  if(!existsSync(artifact))writeFileSync(artifact,text);
  assertFrozen();
  if(existsSync(reportPath)) return {value:false,note:'Already checked: '+readFileSync(reportPath,'utf8')};
  const supervisor='import sys,time,subprocess; subprocess.run(sys.argv[2:],timeout=max(.001,float(sys.argv[1])-time.time()),check=True)';
  const argv=['wsl','-d','Ubuntu','--','bwrap','--unshare-all','--die-with-parent','--new-session',
    '--ro-bind','/usr','/usr','--ro-bind','/bin','/bin','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64',
    '--clearenv','--proc','/proc','--dev','/dev','--tmpfs','/tmp','--ro-bind',linuxEnv,linuxEnv,
    '--ro-bind',linuxPath(join(originalRun,'checker')),'/checker','--ro-bind',linuxPath(join(originalRun,'targets-frozen.json')),'/freeze.json',
    '--bind',linuxPath(join(dir,'verified')),'/audit','--setenv','OMP_NUM_THREADS','4','--setenv','PATH',linuxEnv+'/bin:/usr/bin:/bin',
    '--chdir','/audit',linuxEnv+'/bin/python','-c',supervisor,String(hard/1000),linuxEnv+'/bin/python','/checker/check.py',
    '/audit/'+hash+'.candidate.json','--freeze','/freeze.json','--out','/audit/'+hash+'-proof'];
  const checked=await command(argv);
  writeFileSync(join(dir,'verified',hash+'.checker.stdout.log'),checked.stdout);
  writeFileSync(join(dir,'verified',hash+'.checker.stderr.log'),checked.stderr);
  if(checked.code!==0) return {value:false,note:'Independent checker incomplete/interrupted; no universal bound. '+checked.stderr.slice(-2000)};
  let report:any;try{report=JSON.parse(checked.stdout.trim());}catch{throw Error('Invalid checker response');}
  report={...report,artifact,raw_sha256:hash,task:taskId,checked_utc:new Date().toISOString()};
  put(reportPath,report);appendFileSync(join(dir,'verifier-events.jsonl'),JSON.stringify(report)+'\\n');
  const prev=Number(best[report.target_id]?.probability_upper ?? 1.0000000000000002);
  const better=report.valid&&Number(report.probability_upper)<prev;
  if(better){best[report.target_id]=report;put(join(dir,'best-verified.json'),best);copyFileSync(artifact,join(dir,'best-'+report.target_id+'.candidate.json'));event({event:'verified_bound',target:report.target_id,bound:report.probability_upper,improved:report.improved,sha256:hash});}
  return {value:Boolean(better&&report.improved),note:JSON.stringify(report)};
}
''' + s[end:]
s=s.replace('Python numpy/scipy/mpmath/sympy and g++','Python RNA (ViennaRNA 2.7.0), numpy/scipy/mpmath and g++')
s=s.replace('const threshold = best.size;','const threshold = best;')
s=s.replace('const thresholds = new Map<string, number>();','const thresholds = new Map<string, any>();')
s=s.replace("'independent_full_moment_check'","'independent_rna_upper_bound_check'")
start=s.index('  const description = goal +');end=s.index("\n  await api('POST', '/tasks'",start)
s=s[:start]+'''  const description=goal+`\\nCurrent independently checked best certificates: ${JSON.stringify(best)}. About ${Math.floor(remaining()/60000)} minutes remain. The first model dispatch creates the exact deadline in the run ledger; it can never be reset. Improve the primary target and attempt the frozen backup. A candidate must beat both reference values and the previous verified candidate for that target. Inspect /work for persisted progress. Implement and execute useful rival searches and complete checks. Long jobs should use background=true and save checkpoints.\\n`;
''' +s[end:]
s=s.replace('solveSeconds: Math.max(1, Math.floor(remaining()/1000))','solveSeconds: unlimited')
s=s.replace('import numpy,scipy,mpmath,sympy','import RNA,numpy,scipy,mpmath').replace('Quadrature environment ready','RNA environment ready')
s=s.replace('Date.now()-lastAudit>60000','Date.now()-lastAudit>900000')
s=s.replace('verified_best_size: best.size','verified_best: best').replace('best: best.size','best')
# Timer-bound certificate checking is allowed during the run. Final replay runs
# separately after the guard stops model/solver processes.
old="  try { await verifyArtifact('{\"path\":\"candidate.json\"}', currentTask); } catch (e) { event({ event: 'final_checkpoint_error', error: String(e) }); }"
assert old in s;s=s.replace(old,"  event({event:'final_verification_deferred_to_finalize_script'});")
# Host guard must survive runner completion and detect the first-dispatch ledger.
s=s.replace("put(join(dir, 'guard-process.json'), { pid: guard.pid });","put(join(dir, 'guard-process.json'), { pid: guard.pid });")
(HERE/'run.ts').write_text(s,encoding='utf-8')
startps=(HERE.parent/'quadrature-search/start.ps1').read_text().replace('quadrature-search','rna-bound-search')
(HERE/'start.ps1').write_text(startps)
monitor=(HERE.parent/'quadrature-search/monitor.py').read_text().replace('quadrature-search','rna-bound-search').replace('agent_quadrature_msg','agent_rna_msg')
(HERE/'monitor.py').write_text(monitor)
