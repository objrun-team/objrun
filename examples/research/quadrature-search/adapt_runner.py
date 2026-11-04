"""One-time derivation from the already exercised local ObjRun campaign adapter."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
source=(HERE.parent/'dna-code-search/run.ts').read_text(encoding='utf-8')
source=source.replace('dna-code-search','quadrature-search').replace('DNA_BACKEND','QUADRATURE_BACKEND').replace('objrun-dna','objrun-quadrature')
source=source.replace("'dna'","'quadrature'").replace('dna-search','quadrature-search').replace('dna-five-hours','quadrature-five-hours')
source=source.replace('candidate.txt','candidate.json').replace("hash+'.txt'","hash+'.candidate.json'").replace('best-verified.txt','best-verified.candidate.json')
source=source.replace('strictly more than ${threshold} words','strictly fewer than ${threshold} nodes')
source=source.replace('?? 676','?? 36').replace('report.size > best.size','report.size < best.size')
source=source.replace('Python numpy/scipy/numba/sympy/ortools','Python numpy/scipy/mpmath/sympy')
source=source.replace('import numpy,scipy,numba,sympy,ortools','import numpy,scipy,mpmath,sympy').replace('DNA environment ready','Quadrature environment ready')
source=source.replace("'--proc', '/proc'","'--clearenv', '--proc', '/proc'")
source=source.replace("return { value: Boolean(report.valid && report.improved), note: JSON.stringify(report) };", """const summary = { ...report, moments: undefined, independent: report.independent ? { ...report.independent, moments: undefined } : undefined };
  return { value: Boolean(report.valid && report.improved), note: JSON.stringify(summary) };""")
source=source.replace('best = report;', "best = { ...report, moments: undefined, independent: report.independent ? { ...report.independent, moments: undefined } : undefined };")
source=source.replace("http_status: res.status, response_model: parsed.model", "http_status: res.status, generation_id: parsed.id, response_model: parsed.model")
source=source.replace("let engine: any, base = '', phase = 0, currentTask = '', stopping = false;", "let engine: any, base = '', phase = Math.max(0, ...readdirSync(join(dir, 'engine')).map(n=>Number(n.match(/^phase-(\\d+)/)?.[1]??0))), currentTask = '', stopping = false;")
source=source.replace("const config = join(dir, 'engine/config.yaml');", "const config = join(dir, 'engine/config.yaml');")
source=source.replace("const threshold = best.size;", "const threshold = best.size;\n  assertFrozen();")
source=source.replace("thresholds.set(currentTask, threshold);", "thresholds.set(currentTask, threshold);\n  put(join(dir,'engine',`phase-${phase}.json`),{task:currentTask,threshold,deadline:deadline.deadline_utc});")
source=source.replace("'independent_code_check'", "'independent_full_moment_check'")
source=source.replace("const checked = await command([python", "assertFrozen();\n  const checked = await command([python")
source=source.replace("if (checked.code !== 0) throw", "if (checked.code !== 0) throw")
# Runtime and grading code are not mounted in the model's namespace.
source=source.replace("let graderQueue = Promise.resolve();", """let graderQueue = Promise.resolve();
const frozen = JSON.parse(readFileSync(join(originalRun,'frozen-g.json'),'utf8'));
function assertFrozen() {
  for (const [name, hash] of Object.entries(frozen.files)) {
    if (createHash('sha256').update(readFileSync(join(originalRun,name))).digest('hex') !== hash)
      throw new Error('Frozen G integrity failure: '+name);
  }
}
assertFrozen();
""")
source=source.replace("const start = Date.now(), monotonicStart = performance.now();", "const start = Date.now(), monotonicStart = performance.now();")
# Install hard timer before startup; independent guard starts after process IDs exist.
source=source.replace("let proxy: any, toolServer: any;", """let proxy: any, toolServer: any;
const hardTimer=setTimeout(()=>{
  stopping=true;
  for(const ctl of controllers) ctl.abort();
  for(const job of jobs.values()) if(job.exitCode===null) try{job.proc.kill();}catch{}
  try{engine?.kill();}catch{}
  event({event:'hard_deadline_local_stop'});
},Math.max(1,remaining()));
""")
source=source.replace("stopping = true;\n  for", "stopping = true;\n  clearTimeout(hardTimer);\n  for")
# Record endpoint ports without the internal bearer token.
source=source.replace("await configure();", "await configure();\n  put(join(dir,'endpoints.json'),{engine:base,tool_port:toolServer.port,proxy_port:proxy.port});")
# Save a periodic independent audit of a changed atomic candidate, even before submit.
source=source.replace("while (remaining() && engine.exitCode === null) {", "let lastAudit=0, lastCandidateHash='';\n    while (remaining() && engine.exitCode === null) {")
source=source.replace("let task: any;\n      try", """if(Date.now()-lastAudit>60000){
        lastAudit=Date.now();
        try {
          const h=createHash('sha256').update(readFileSync(join(work,'candidate.json'))).digest('hex');
          if(h!==lastCandidateHash){await serializedVerify('{"path":"candidate.json"}',currentTask);lastCandidateHash=h;}
        }catch(e){event({event:'checkpoint_audit_error',error:String(e)});}
      }
      let task: any;
      try""")
(HERE/'run.ts').write_text(source,encoding='utf-8')
monitor=(HERE.parent/'dna-code-search/monitor.py').read_text().replace('dna-code-search','quadrature-search').replace('agent_dna_msg','agent_quadrature_msg')
monitor=monitor.replace("'last_events': events[-3:]", "'unconfirmed_request_ids': [e['id'] for e in dispatch if not any(f['id']==e['id'] and (f.get('usage') or {}).get('cost') is not None for f in finished)],\n        'last_events': events[-3:]")
(HERE/'monitor.py').write_text(monitor,encoding='utf-8')
