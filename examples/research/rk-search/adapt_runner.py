"""Derive an isolated adapter from the existing exercised ObjRun experiment adapter."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
s=(HERE.parent/'quadrature-search/run.ts').read_text(encoding='utf-8')
s=s.replace('quadrature-search','rk-search').replace('QUADRATURE_BACKEND','RK_BACKEND').replace('objrun-quadrature','objrun-rk').replace("'quadrature'","'rk'").replace('quadrature-five-hours','rk-five-hours')
s=s.replace("const linuxEnv = '/home/imontlaji/.local/share/objrun-rk-20261030-env';","const linuxEnv = JSON.parse(readFileSync(join(originalRun,'runtime-manifest.json'),'utf8')).linux_environment;")
s=s.replace("const start = Date.now(), monotonicStart = performance.now();","let start = Date.now(), monotonicStart = performance.now();")
s=s.replace('const hard = priorDeadline','let hard = priorDeadline').replace('const deadline = priorDeadline','let deadline = priorDeadline')
s=s.replace("put(join(dir, 'deadline.json'), deadline);","if (priorDeadline) put(join(dir, 'deadline.json'), deadline);")
s=s.replace('const hardTimer=setTimeout','let hardTimer=setTimeout')
s=s.replace("const thresholds = new Map<string, number>();","const thresholds = new Map<string, string>();")
s=s.replace('const threshold = thresholds.get(taskId) ?? 36;',"const threshold = thresholds.get(taskId) ?? best.error_norm;")
s=s.replace("'--threshold', String(threshold)","'--threshold', String(best.error_norm)")
s=s.replace('if (report.valid && report.size < best.size)', 'if (report.valid && report.improved)')
s=s.replace('const threshold = best.size;', 'const threshold = best.error_norm;')
s=s.replace('strictly fewer than ${threshold} nodes','error norm below ${threshold} by the frozen improvement margin')
s=s.replace('independent_full_moment_check','independent_rooted_tree_check')
s=s.replace('moments: undefined, independent:', 'high_precision: undefined, moments: undefined, independent:')
s=s.replace("{ ...report.independent, moments: undefined }", "{ precision_digits: report.independent.precision_digits, max_constraint_residual: report.independent.max_constraint_residual, error_norm: report.independent.error_norm }")
s=s.replace("body.stream = false;", "body.stream = false;\n    if (!preflight && !existsSync(join(dir,'deadline.json'))) armCampaign();")
s=s.replace("if (res.ok && parsed.choices?.length) return parsed;","if (res.ok && parsed.choices?.length) { if (parsed.model !== model) throw new Error('Provider returned a different model: '+parsed.model); return parsed; }")
old="""  if (!preflight) {
    const guard = Bun.spawn([python, join(originalRun, 'guard.py'), dir], { stdin: 'ignore', stdout: Bun.file(join(dir, 'guard.stdout.log')), stderr: Bun.file(join(dir, 'guard.stderr.log')), windowsHide: true });
    guard.unref();
    put(join(dir, 'guard-process.json'), { pid: guard.pid });
  }"""
assert old in s
s=s.replace(old,"  if (!preflight && priorDeadline) startGuard();")
insertion="""
function startGuard(){
  const guard = Bun.spawn([python, join(originalRun,'guard.py'),dir],{stdin:'ignore',stdout:Bun.file(join(dir,'guard.stdout.log')),stderr:Bun.file(join(dir,'guard.stderr.log')),windowsHide:true});
  guard.unref(); put(join(dir,'guard-process.json'),{pid:guard.pid});
}
function armCampaign(){
  start=Date.now(); monotonicStart=performance.now(); hard=start+18_000_000;
  deadline={started_utc:new Date(start).toISOString(),deadline_utc:new Date(hard).toISOString(),deadline_epoch:hard/1000,duration_seconds:18000,model,only_campaign_budget:'elapsed time; first paid request dispatch'};
  put(join(dir,'deadline.json'),deadline); clearTimeout(hardTimer);
  hardTimer=setTimeout(()=>{stopping=true;for(const ctl of controllers)ctl.abort();for(const job of jobs.values())if(job.exitCode===null)try{job.proc.kill();}catch{};try{engine?.kill();}catch{};event({event:'hard_deadline_local_stop'});},remaining());
  startGuard(); event({event:'first_paid_request_clock_started',...deadline});
}
"""
s=s.replace('async function startProxy() {',insertion+'\nasync function startProxy() {')
# Reruns preserve exact deadline; no three-minute paid preflight exists.
# Preflight only runs local engine/tools/checker and cannot call a model.
s=s.replace("if (body.model !== model)","if(preflight) throw new Error('Paid requests forbidden in local-only preflight');\n    if (body.model !== model)")
s=s.replace("const description = goal +", "const description = goal +")
s=s.replace("writeFileSync(join(dir, 'jobs', `${id}.command.txt`), cmd);", "writeFileSync(join(dir, 'jobs', `${id}.command.txt`), cmd);")
s=s.replace("event({ event: 'job_started', id });", "event({ event: 'job_started', id, pid:proc.pid });")
# CPU thread count is concurrency hygiene, not a search iteration budget.
s=s.replace("'--setenv', 'HOME', '/work'", "'--setenv', 'OPENBLAS_NUM_THREADS','1','--setenv','OMP_NUM_THREADS','1','--setenv','MKL_NUM_THREADS','1','--setenv', 'HOME', '/work'")
(HERE/'run.ts').write_text(s,encoding='utf-8')
for name in ['start.ps1','monitor.py','guard.py','test_guard.py']:
    t=(HERE.parent/'quadrature-search'/name).read_text(encoding='utf-8').replace('quadrature-search','rk-search').replace('agent_quadrature_msg','agent_rk_msg')
    (HERE/name).write_text(t,encoding='utf-8')
