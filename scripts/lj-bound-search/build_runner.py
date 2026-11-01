from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];D=Path(__file__).resolve().parent
s=(ROOT/'scripts/rna-bound-search/run.ts').read_text(encoding='utf-8')
s=s.replace('rna-bound-search','lj-bound-search').replace("'rna-five-hours'","'lj-five-hours'").replace("name: 'rna'","name: 'lj'").replace("agent: 'rna'","agent: 'lj'")
s=s.replace('RNA_BACKEND','LJ_BACKEND')
s=s.replace('/home/imontlaji/.local/share/objrun-rna-20261030-env','/home/imontlaji/.local/share/objrun-lj-20261031-env')
s=s.replace('Python RNA (ViennaRNA 2.7.0), numpy/scipy/mpmath','Python numpy/scipy/mpmath/sympy')
s=s.replace("import RNA,numpy,scipy,mpmath\\nprint('RNA environment ready')","import numpy,scipy,mpmath,sympy\\nprint('LJ environment ready')")
s=s.replace('independent_rna_upper_bound_check','independent_lj_uniform_bound_check')
start=s.index('  const supervisor=',s.index('async function verifyArtifact'))
end=s.index('\n  return {value:Boolean(better&&report.improved),note:JSON.stringify(report)};',start)
s=s[:start]+'''  const certificate=join(dir,'verified',hash+'.certificate.json');
  const checked=await command([python,join(originalRun,'checker/check.py'),artifact,certificate]);
  writeFileSync(join(dir,'verified',hash+'.checker.stdout.log'),checked.stdout);
  writeFileSync(join(dir,'verified',hash+'.checker.stderr.log'),checked.stderr);
  if(checked.code!==0)return {value:false,note:'Checker incomplete; no accepted theorem.'};
  let report:any;try{report=JSON.parse(checked.stdout.trim());}catch{throw Error('Invalid checker response');}
  report={...report,artifact,raw_sha256:hash,task:taskId,checked_utc:new Date().toISOString(),certificate};
  if(report.valid && report.improved){
    const replay=await command([python,join(originalRun,'checker/replay.py'),certificate]);
    writeFileSync(join(dir,'verified',hash+'.replay.stdout.log'),replay.stdout);
    writeFileSync(join(dir,'verified',hash+'.replay.stderr.log'),replay.stderr);
    try{report.independent_replay=JSON.parse(replay.stdout.trim());}catch{report.independent_replay={independent_replay_passed:false};}
    const obj=JSON.parse(text);
    const proofRel=String(obj.proof_path??'PROOF.md');
    if(isAbsolute(proofRel)||proofRel.split(/[\\\\/]/).includes('..'))report.proof_saved=false;
    else{
      try{const actual=realpathSync(join(work,proofRel));const rel=relative(realpathSync(work),actual);if(rel.startsWith('..')||isAbsolute(rel))throw Error('outside');
        const proof=readFileSync(actual,'utf8');report.proof_saved=proof.length>200;
        writeFileSync(join(dir,'verified',hash+'.model-proof.md'),proof);
      }catch{report.proof_saved=false;}
    }
    if(report.independent_replay.independent_replay_passed && report.proof_saved){
      assertFrozen();best=report;put(join(dir,'best-verified.json'),best);
      put(join(dir,'primary-success.json'),{utc:new Date().toISOString(),report,authorization:'User explicitly requests immediate stop after independent main-goal verification.',analytic_basis:'Frozen host PROOF_FAMILY.md; independent exact polynomial and tail replay.'});
      event({event:'primary_success_independently_verified',bound:report.c_new_expression,sha256:hash});
      stopping=true;
      for(const ctl of controllers)ctl.abort();
      for(const job of jobs.values())if(job.exitCode===null)try{job.proc.kill();}catch{}
    }
  }
  put(reportPath,report);appendFileSync(join(dir,'verifier-events.jsonl'),JSON.stringify(report)+'\\n');
  return {value:Boolean(report.valid&&report.improved&&report.independent_replay?.independent_replay_passed&&report.proof_saved),note:JSON.stringify(report)};'''+s[end+len('\n  return {value:Boolean(better&&report.improved),note:JSON.stringify(report)};'):]
start=s.index('  const recoveryNote=')
end=s.index("\n  await api('POST', '/tasks'",start)
s=s[:start]+'''  const description=goal+`\\nCurrent independently checked best: ${JSON.stringify(best)}. About ${Math.floor(remaining()/60000)} minutes remain. First dispatch freezes the exact deadline; it can never be reset. Search for a genuinely improved all-N proof and save code, full proof and candidate.json. Submit promptly when complete; independent success ends this campaign immediately. Inspect persisted /work progress.\\n`;
'''+s[end:]
s=s.replace('while (remaining() && engine.exitCode === null)', 'while (remaining() && !stopping && engine.exitCode === null)')
s=s.replace("if(Date.now()-lastAudit>900000)","if(Date.now()-lastAudit>15000)")
s=s.replace("if (remaining() > 0) await publish();","if (remaining() > 0 && !stopping) await publish();")
s=s.replace("if (engine.exitCode !== null && remaining() > 0)","if (engine.exitCode !== null && remaining() > 0 && !stopping)")
s=s.replace("preflight ? 'preflight_passed' : 'five_hour_deadline'", "preflight ? 'preflight_passed' : existsSync(join(dir,'primary-success.json')) ? 'independent_primary_success' : 'five_hour_deadline'")
s=s.replace("const audit = await verifyArtifact", "const audit = await verifyArtifact")
# Prevent any recovery after successful stop, not just after deadline.
s=s.replace("const preflight = process.argv.includes('--check');", "const preflight = process.argv.includes('--check');\nif(existsSync(join(originalRun,'primary-success.json'))||existsSync(join(originalRun,'final/summary.json')))throw Error('Campaign already closed; final review only.');")
# Full-context storage is kept; only diagnostic tails are bounded. Checkpoints every 15s
# allow immediate success; user-facing operational monitor remains every 15 minutes.
(D/'run.ts').write_text(s,encoding='utf-8')
start=(ROOT/'scripts/rna-bound-search/start.ps1').read_text().replace('rna-bound-search','lj-bound-search')
start=start.replace("'early-stop-request.json'","'primary-success.json'")
(D/'start.ps1').write_text(start,encoding='utf-8')
print('Built isolated LJ adapter from existing real ObjRun harness')
