from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];D=Path(__file__).resolve().parent
s=(ROOT/'scripts/lj-bound-search/run.ts').read_text(encoding='utf-8').replace('lj-bound-search','lj-conjecture-search').replace('lj-five-hours','lj-conjecture-five-hours')
s=s.replace("const container = 'objrun-rna-'", "const container = 'objrun-lj-conjecture-'")
s=s.replace("if (!remaining() || stopping) throw new Error('The campaign deadline has been reached.');", "if (!remaining() || stopping || existsSync(join(originalRun,'stop-request.json'))) throw new Error('The campaign deadline has been reached.');")
s=s.replace("if (!remaining() || stopping) throw new Error('campaign deadline');", "if (!remaining() || stopping || existsSync(join(originalRun,'primary-success.json'))) throw new Error('campaign deadline or accepted primary success');")
s=s.replace("while (remaining() && !stopping) {", "while (remaining() && !stopping && !existsSync(join(originalRun,'primary-success.json'))) {")
s=s.replace("if(existsSync(reportPath)) return {value:false,note:JSON.stringify({...JSON.parse(readFileSync(reportPath,'utf8')),already_checked:true})};",'// Always re-evaluate current evidence hashes and protected review receipts.')
start=s.index('  const certificate=',s.index('async function verifyArtifact'))
end=s.index('\n}\n\nasync function serializedVerify',start)
s=s[:start]+'''  const checked=await command([python,join(originalRun,'checker/check.py'),originalRun,artifact,reportPath]);
  writeFileSync(join(dir,'verified',hash+'.checker.stdout.log'),checked.stdout);
  writeFileSync(join(dir,'verified',hash+'.checker.stderr.log'),checked.stderr);
  let report:any;try{report=JSON.parse(checked.stdout.trim());}catch{return {value:false,note:'Incomplete evidence check; no theorem accepted.'};}
  report={...report,artifact,task:taskId,checked_utc:new Date().toISOString()};
  put(reportPath,report);
  if(report.bundle_sha256)put(join(dir,'verified',report.bundle_sha256+'.review-status.json'),report);
  appendFileSync(join(dir,'verifier-events.jsonl'),JSON.stringify(report)+'\\n');
  if(report.requires_host_review)event({event:'primary_claim_requires_independent_review',bundle:report.bundle_sha256,claim_type:report.claim_type});
  if(report.secondary_check?.valid && report.secondary_replay?.independent_replay_passed){
    best={...best,secondary:report};put(join(dir,'best-verified.json'),best);
  }
  if(report.primary_passed){
    assertFrozen();best={...best,primary:report};put(join(dir,'best-verified.json'),best);
    put(join(dir,'primary-success.json'),{utc:new Date().toISOString(),report,authorization:'Only conjecture resolution/global counterexample independently reviewed; user authorized priority early stop.'});
    stopping=true;for(const ctl of controllers)ctl.abort();
    for(const job of jobs.values())if(job.exitCode===null)try{job.proc.kill();}catch{}
  }
  return {value:Boolean(report.primary_passed),note:JSON.stringify(report)};'''+s[end:]
start=s.index('  if (!preflight) {\n    const guard = Bun.spawn')
end=s.index('\n  await configure();',start)
s=s[:start]+"  // Independent external supervisor owns stop/closeout; no child guard.\n"+s[end:]
s=s.replace('Search for a genuinely improved all-N proof and save code, full proof and candidate.json.', 'Resolve the >=1 conjecture or globally certify a <1 counterexample. Improved bounds below1 are secondary only. Save complete proof, supporting code and candidate.json. Read /work/RESEARCH_LOG.md and host-feedback if present before choosing a distinct next route.')
s=s.replace('independent_lj_uniform_bound_check','independent_lj_conjecture_check')
s=s.replace("return { id, started: job.started, running: job.exitCode === null, exitCode: job.exitCode, stdout: readTail(job.logPath), stderr: readTail(job.errPath), remaining_seconds: Math.ceil(remaining()/1000) };", "const host_feedback=existsSync(join(work,'HOST_FEEDBACK.md'))?readFileSync(join(work,'HOST_FEEDBACK.md'),'utf8'):null;\n  return { id, started: job.started, running: job.exitCode === null, exitCode: job.exitCode, stdout: readTail(job.logPath), stderr: readTail(job.errPath), remaining_seconds: Math.ceil(remaining()/1000), host_feedback };")
s=s.replace('while (remaining() && !stopping && engine.exitCode === null)', "while (remaining() && !stopping && !existsSync(join(originalRun,'primary-success.json')) && engine.exitCode === null)")
old="const h=createHash('sha256').update(readFileSync(join(work,'candidate.json'))).digest('hex');"
new="""const data=readFileSync(join(work,'candidate.json'),'utf8');const desc=JSON.parse(data);const hasher=createHash('sha256').update(data);
          for(const name of [desc.proof_path,...(desc.files??[])].filter(Boolean)){
            if(typeof name==='string'&&!isAbsolute(name)&&!name.split(/[\\\\/]/).includes('..'))try{hasher.update(readFileSync(join(work,name)));}catch{}
          }
          for(const name of readdirSync(join(originalRun,'reviews')).filter(n=>n.endsWith('.json')))hasher.update(readFileSync(join(originalRun,'reviews',name)));
          const h=hasher.digest('hex');"""
assert old in s;s=s.replace(old,new)
s=s.replace("  await api('POST', '/exec', { sql: 'update handle set expect_ms=:ms', params: { ms: duration } });", "  await api('POST', '/exec', { sql: 'update handle set expect_ms=:ms', params: { ms: duration } });\n  // Avoid requiring a duplicate hand-in tool call; sealed DFS still grades only the recorded submit candidate.\n  await api('POST', '/exec', { sql: 'update cycle set must_call=null where mode=:mode and cycle=:cycle', params: { mode: 'lj-conjecture-search', cycle: 'submit' } });")
(D/'run.ts').write_text(s,encoding='utf-8')
for name in ('linux_owned.py',):
    text=(ROOT/'scripts/lj-bound-search'/name).read_text().replace('lj-bound-search','lj-conjecture-search')
    (D/name).write_text(text,encoding='utf-8')
# All host feedback goes through the real engine message endpoint, not a substitute model.
# intervene.ts is maintained separately: feedback is embedded in tool results,
# never inserted between an assistant tool_call and its tool result.
print('Round2 real-engine adapter built')
