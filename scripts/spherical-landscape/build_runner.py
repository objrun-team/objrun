"""Adapt the existing real-engine campaign adapter without changing its source."""
from pathlib import Path
root=Path(__file__).resolve().parents[2];here=Path(__file__).resolve().parent
s=(root/'scripts/quadrature-search/run.ts').read_text()
s=s.replace('quadrature','spherical-landscape').replace('Quadrature','Spherical landscape')
s=s.replace('data/spherical-landscape-search','data/spherical-landscape')
s=s.replace("name: 'spherical-landscape'", "name: 'landscape'").replace("agent: 'spherical-landscape'", "agent: 'landscape'")
# Reuse installed scientific environment read-only, never modify another run.
s=s.replace('/home/imontlaji/.local/share/objrun-spherical-landscape-20261030-env','/home/imontlaji/.local/share/objrun-quadrature-20261030-env')
s=s.replace('const hard = priorDeadline ? priorDeadline.deadline_epoch*1000 : start + duration;','let hard = priorDeadline ? priorDeadline.deadline_epoch*1000 : start + duration;\nlet clockStarted=Boolean(priorDeadline);')
s=s.replace('const remaining = () => Math.max(0, Math.min(hard-Date.now(), hard-start-(performance.now()-monotonicStart)));','const remaining = () => !clockStarted && !preflight ? duration : Math.max(0, hard-Date.now());')
s=s.replace("const deadline = priorDeadline ??", "let deadline = priorDeadline ??")
s=s.replace("put(join(dir, 'deadline.json'), deadline);", "if(priorDeadline || preflight) put(join(dir, 'deadline.json'), deadline);")
a=s.index('const hardTimer=setTimeout(');b=s.index('\nconst token =',a)
s=s[:a]+'''let hardTimer: any;
function armDeadline(){
  hardTimer=setTimeout(()=>{
    stopping=true;
    for(const ctl of controllers) ctl.abort();
    for(const job of jobs.values()) if(job.exitCode===null) try{job.proc.kill();}catch{}
    try{engine?.kill();}catch{}
    event({event:'hard_deadline_local_stop'});
  },Math.max(1,remaining()));
}
function startClock(){
  if(preflight) throw new Error('Paid model calls are forbidden in preflight');
  if(clockStarted)return;
  const now=Date.now();hard=now+18_000_000;clockStarted=true;
  deadline={started_utc:new Date(now).toISOString(),deadline_utc:new Date(hard).toISOString(),deadline_epoch:hard/1000,duration_seconds:18000,model,only_campaign_budget:'elapsed time from first paid dispatch'};
  writeFileSync(join(dir,'deadline.json'),JSON.stringify(deadline,null,2),{flag:'wx'});
  armDeadline();
  const guard=Bun.spawn([python,join(originalRun,'guard.py'),dir],{stdin:'ignore',stdout:Bun.file(join(dir,'guard.stdout.log')),stderr:Bun.file(join(dir,'guard.stderr.log')),windowsHide:true});guard.unref();
  put(join(dir,'guard-process.json'),{pid:guard.pid});
  event({event:'first_paid_dispatch_clock_started',...deadline});
}
if(priorDeadline || preflight) armDeadline();
''' +s[b:]
a=s.index('  const threshold = thresholds.get(taskId)');b=s.index('\n  let descriptor:',a);s=s[:a]+s[b:]
a=s.index('  const checked = await command([python,');b=s.index('\n  const summary =',a)
s=s[:a]+'''  const checked = await command([python, join(originalRun, 'checker.py'), artifact, '--output',join(dir,'verified',hash+'.json'),'--baseline',join(originalRun,'baseline-audit.json')]);
  if(checked.code!==0)throw new Error('Checker failed: '+checked.stderr);
  const report=JSON.parse(readFileSync(join(dir,'verified',hash+'.json'),'utf8'));
  appendFileSync(join(dir,'verifier-events.jsonl'),JSON.stringify({time:new Date().toISOString(),artifact,hash,energy:report.energy,gradient_norm:report.gradient_norm,evidence_level:report.evidence_level})+'\\n');
  if(report.strict_numerical_candidate){best={...report,gram:undefined,perturbations:undefined,full_tangent_spectrum:undefined,quotient_spectrum:undefined,min_quotient_eigenvalue:report.quotient_spectrum[0],artifact};put(join(dir,'best-verified.json'),best);copyFileSync(artifact,join(dir,'best-verified.candidate.json'));}
''' +s[b:]
a=s.index('  const summary =',s.index('async function verifyArtifact'));b=s.index('\n}',a)
s=s[:a]+'''  const summary={...report,gram:undefined,perturbations:undefined,full_tangent_spectrum:undefined,quotient_spectrum:undefined,min_quotient_eigenvalue:report.quotient_spectrum[0]};
  return {value:Boolean(report.strict_numerical_candidate),note:JSON.stringify(summary)};''' +s[b:]
s=s.replace('    const body: any = await req.json();','    if(preflight) throw new Error("No paid preflight allowed");\n    const body: any = await req.json();')
s=s.replace('      const id = ++nextRequest, ctl', '      startClock();\n      const id = ++nextRequest, ctl')
# Guard is created at the first dispatch, not at process launch.
a=s.index('  if (!preflight) {\n    const guard');b=s.index('\n  await configure();',a);s=s[:a]+s[b:]
s=s.replace('  const threshold = best.size;','  const threshold = 0;')
s=s.replace('independent_full_moment_check','independent_full_tangent_check')
a=s.index('  const description = goal +');b=s.index('\n  await api(\'POST\', \'/tasks\'',a)
s=s[:a]+'''  const description=goal+`\\nCurrent campaign: ${JSON.stringify(deadline)}. Actual deadline is established at the first paid dispatch and saved to /work/campaign-clock.json. Read that file. Host checker report: ${JSON.stringify(best)}. Read /reference/reproduction.json, then run the supplied /work/search_support.py as a background CPU program with --deadline set to deadline_epoch. Inspect results, independently submit promising candidates, refine high precision and pursue certification. You may improve or replace search code, but use the fixed definition and preserve complete candidate coordinates and trajectories. Tool commands are bash in an isolated environment. Use background=true for long work, and job_status sparingly. Continue until the absolute deadline.`;
''' +s[b:]
s=s.replace("  event({event:'first_paid_dispatch_clock_started',...deadline});","  put(join(work,'campaign-clock.json'),deadline);\n  event({event:'first_paid_dispatch_clock_started',...deadline});")
s=s.replace("  if (!JSON.parse(audit.note).valid) throw new Error('Reference code failed verification');", "  if (Math.abs(JSON.parse(audit.note).energy)>1e-8) throw new Error('Reference code failed verification');")
s=s.replace("verified_best_size: best.size", "best_evidence: best.evidence_level")
s=s.replace("best: best.size", "best: best.evidence_level")
# Independent audit service scans every complete candidate, even without submission.
s=s.replace("    await publish();", "    const auditor=Bun.spawn([python,join(originalRun,'audit_loop.py'),originalRun],{stdin:'ignore',stdout:Bun.file(join(dir,'auditor.stdout.log')),stderr:Bun.file(join(dir,'auditor.stderr.log')),windowsHide:true});\n    event({event:'auditor_started',pid:auditor.pid});\n    await publish();",1)
s=s.replace("    if (!remaining() || stopping) throw new Error('campaign deadline');", "    if (!remaining() || stopping) throw new Error('campaign deadline');")
(here/'run.ts').write_text(s)
print(here/'run.ts')
