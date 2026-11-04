from pathlib import Path
p=Path(__file__).resolve().parent
s=(p.parent/'spherical-landscape/run.ts').read_text()
s=s.replace('spherical-landscape','ks-original-search').replace("'landscape'","'kssearch'").replace('independent_full_tangent_check','independent_exact_ks_check')
s=s.replace("process.env.QUADRATURE_BACKEND || 'bwrap'","'bwrap'")
s=s.replace('objrun-quadrature-20261030-env','objrun-ca-20261030-env')
a=s.index('function sandboxCommand()');b=s.index('const start = Date.now()',a)
base=(p.parent/'covering-array-search/run.ts').read_text();aa=base.index('function sandboxCommand()');bb=base.index('const start = Date.now()',aa)
s=s[:a]+base[aa:bb]+s[b:]
s=s.replace("let clockStarted=Boolean(priorDeadline);","let clockStarted=Boolean(priorDeadline);\nlet monotonicEnd=performance.now()+Math.max(0,hard-Date.now());")
s=s.replace("Math.max(0, hard-Date.now());","Math.max(0, Math.min(hard-Date.now(),monotonicEnd-performance.now()));")
s=s.replace("clockStarted=true;","clockStarted=true;monotonicEnd=performance.now()+18_000_000;")
s=s.replace("for (const p of ['engine', 'jobs', 'requests', 'verified'])","for (const p of ['engine', 'jobs', 'requests', 'verified', 'code-history'])")
s=s.replace("if (!remaining() || stopping)","if (!remaining() || stopping || existsSync(join(originalRun,'stop-requested.json')) || existsSync(join(originalRun,'success-certified.json')))")
s=s.replace("const id = ++nextJob;", "snapshotCode();\n  const id = ++nextJob;")
pos=s.index('function runJob(')
s=s[:pos]+'''function snapshotCode(){
  function visit(folder:string){for(const e of readdirSync(folder,{withFileTypes:true})){const p=join(folder,e.name);if(e.isDirectory() && e.name!=='__pycache__')visit(p);else if(e.isFile() && /\\.(py|cpp|c|h|sh|ts|js)$/.test(e.name)){const raw=readFileSync(p),hash=createHash('sha256').update(raw).digest('hex');const dest=join(dir,'code-history',hash+'-'+e.name);if(!existsSync(dest))writeFileSync(dest,raw);appendFileSync(join(dir,'code-history.jsonl'),JSON.stringify({utc:new Date().toISOString(),path:relative(work,p),sha256:hash})+'\\n');}}}
  visit(work);
}

'''+s[pos:]
a=s.index("  const checked = await command(");b=s.index('\nasync function serializedVerify',a)
s=s[:a]+'''  const reportPath=join(dir,'verified',hash+'.engine.json');
  const checked=await command([python,join(originalRun,'checker.py'),artifact,'--output',reportPath,'--baseline',String(frozen.baseline_n)]);
  if(checked.code!==0)throw new Error('Checker failed: '+checked.stderr);
  const report=JSON.parse(readFileSync(reportPath,'utf8'));
  appendFileSync(join(dir,'verifier-events.jsonl'),JSON.stringify({time:new Date().toISOString(),artifact,hash,n:report.n,valid:report.valid,strict_success:report.strict_success})+'\\n');
  if(report.strict_success){
    const finalPath=join(dir,'success-engine-final-replay.json');
    await command([python,join(originalRun,'checker.py'),artifact,'--output',finalPath,'--baseline',String(frozen.baseline_n)]);
    const final=JSON.parse(readFileSync(finalPath,'utf8'));
    if(final.strict_success){put(join(dir,'success-certified.json'),{certified_utc:new Date().toISOString(),artifact,report:final});stopping=true;for(const ctl of controllers)ctl.abort();for(const j of jobs.values())if(j.exitCode===null)try{j.proc.kill();}catch{}}
  }
  if(report.valid && report.n<best.n){best={...report,artifact};put(join(dir,'best-verified.json'),best);copyFileSync(artifact,join(dir,'best-verified.candidate.json'));}
  return {value:Boolean(report.strict_success),note:JSON.stringify(report)};
}
''' +s[b:]
s=s.replace("if (res.ok && parsed.choices?.length) return parsed;", "if(res.ok && parsed.choices?.length){if(parsed.model!==model){stopping=true;throw new Error('Provider returned a different model: '+parsed.model);}return parsed;}")
s=s.replace('Python numpy/scipy/mpmath/sympy and g++ are installed.','Python numpy/scipy/sympy/pysat/ortools and g++ are installed.')
s=s.replace('Use background=true for long searches.','Use background=true for long searches, with the command foreground within bash (no shell ampersand).')
a=s.index('  const description=goal+');b=s.index('\n\n  await api',a)
s=s[:a]+'''  const description=goal+`\\nCampaign clock is created on first paid dispatch; read /work/campaign-clock.json. Latest independently checked best: ${JSON.stringify(best)}. Read /reference/RESEARCH.md. Start substantive exact CPU search promptly; the optional /work/search_support.py supports --deadline, --radius and --seed. The 49-ray radius-2 pool is calibration only. Write and run your own improved algorithms. Persist candidate coordinates and progress. Continue research until exact certified success or original deadline, never claim success from your own report alone.`;
''' +s[b:]
s=s.replace("agent: 'kssearch'", "agent: 'kssearch'")
s=s.replace("import numpy,scipy,mpmath,sympy", "import numpy,scipy,sympy,pysat")
s=s.replace('Spherical landscape environment ready','Exact KS environment ready')
s=s.replace("if (Math.abs(JSON.parse(audit.note).energy)>1e-8)","if (!JSON.parse(audit.note).valid || JSON.parse(audit.note).n!==31)")
s=s.replace("while (remaining() && engine.exitCode === null)","while (remaining() && !stopping && !existsSync(join(dir,'success-certified.json')) && engine.exitCode === null)")
s=s.replace("if (engine.exitCode !== null && remaining() > 0)","if (engine.exitCode !== null && remaining() > 0 && !stopping && !existsSync(join(dir,'success-certified.json')))")
s=s.replace("if (remaining() > 0) await publish();","if (remaining() > 0 && !stopping) await publish();")
s=s.replace("  // Capture the last complete checkpoint", "  snapshotCode();\n  // Capture the last complete checkpoint")
s=s.replace("preflight ? 'preflight_passed' : 'five_hour_deadline'","preflight ? 'preflight_passed' : existsSync(join(dir,'success-certified.json')) ? 'certified_success' : 'five_hour_deadline'")
# All temporary Unix namespaces also terminate via external GNU timeout. Private host guard stops early.
(p/'run.ts').write_text(s,encoding='utf-8')
