"""Finalize saved-evidence metadata only. No models, solvers, or new search."""
import json,hashlib,collections,os,shutil
from pathlib import Path
from datetime import datetime,timezone
root=Path(__file__).resolve().parents[3]
run=Path((root/'data/ks-original-search/latest-run.txt').read_text().strip());final=run/'final'
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
def write(p,v):p.write_text(json.dumps(v,indent=2,ensure_ascii=False),encoding='utf-8')
s=read(final/'summary.json');assert not s['primary_success'] and s['minimum_valid_n']==31
receipt=read(final/'automation-cleanup.json');assert 'deleted' in json.dumps(receipt).lower()
stops=read(final/'stop-audit.json');assert not any(v['owned_identity_alive'] for v in stops['windows_observed'].values());assert stops['linux']['remaining_namespaces']==[]
reports=[read(p) for p in final.glob('*.report.json')]
s['candidate_count_scope']='Counts refer to unique candidate file bytes, not inequivalent or non-isomorphic KS sets.'
s['valid_ray_count_distribution']=dict(sorted(collections.Counter(x['n'] for x in reports if x['valid']).items()))
s['rejected_candidates']=[{k:x.get(k) for k in ['sha256','n','error','unsat']} for x in reports if not x['valid']]
s['finite_pool_claims']='Model-produced finite-pool exclusion logs were preserved but not independently certified in final adjudication; no universal lower bound or novelty claim is made.'
s['monitor_automation_cleanup']={'automation_id':'ks','status':'deleted','receipt':'final/automation-cleanup.json'}
s['no_live_search_processes_confirmed']=True
s['model_id_audit']=dict(collections.Counter(read(p)['model'] for p in (run/'requests').glob('*.json') if '.response.' not in p.name))
s['recovery_records']=[p.name for p in sorted(run.glob('recovery-*.json')) if not p.name.endswith('-before.json')]
s['final_adjudication_utc']=datetime.now(timezone.utc).isoformat()
write(final/'summary.json',s)
notes=read(run/'RUN_NOTES.json');notes.update(status='completed_without_primary_success',minimum_valid_n=31,primary_success=False,final_report='final/REPORT.md',automation_status='deleted',final_adjudication_utc=s['final_adjudication_utc']);write(run/'RUN_NOTES.json',notes)
auto=read(run/'monitor-automation.json');auto.update(status='DELETED',cleanup_receipt='final/automation-cleanup.json');write(run/'monitor-automation.json',auto)
text=f'''This run is complete, but the main objective was not achieved. The frozen baseline contains 31 distinct real three-dimensional rays; the target remained at most 30 throughout. The smallest final valid set contains 31 rays.

The real ObjRun engine used OpenRouter deepseek/deepseek-v4.1-flash throughout. The search window ran for 18,000 seconds, from 2026-10-31 19:57:42.102 to 2026-11-01 00:57:42.102 Beijing time. Only saved evidence was reviewed after the deadline. Model identifiers matched the fixed model in all 117 requests.

Final checks reconstructed {s['candidate_artifacts_rechecked']} candidates with distinct file contents; {s['valid_artifacts']} passed. Of these, 126 were 31-ray files. This is not a count of nonisomorphic sets and does not establish new constructions. The three rejected artifacts were an empty set, a colorable 26-ray set, and a colorable 235-ray set. No set of at most 30 rays passed complete independent final verification.

Evidence level: exact rational/real quadratic-field coordinate validation, nonzero checks and ray deduplication, reconstruction of all orthogonal pairs and triples, complete DIMACS encoding, and replayable DPLL unsatisfiability certificates. A separate implementation using SymPy exact geometry and bitmask SAT reconstructed and rechecked them. The baseline contains 31 rays, 71 orthogonal pairs, and 17 orthogonal triples. Frozen checker hashes still match their pre-run values; all 40 preflight checks passed.

The 116 API receipts with recorded costs sum to **USD {s['usage']['recorded_cost_usd']}**. All 117 requests received responses; none remain pending. Request 89 was rejected by the provider for exceeding context limits (HTTP 400) and has no cost receipt. Its cost is unknown and was not counted as zero. Original receipts and per-request details are in requests/, calls.jsonl, and final/usage.json.

This run explored integer and real quadratic-field coordinate pools, rotated unions, point removal/replacement, and SAT implicit hitting-set search. The two final 289-ray-pool searches recorded 6,340 and 6,500 iterations, respectively, without producing a valid smaller set. Finite-pool exclusion claims in model logs were not included in independently certified conclusions; finite search does not establish a universal lower bound in R³. Reproducing or generating 31-ray candidates is only a partial result.

Two infrastructure recoveries addressed broken tool-message continuity and provider context-limit exhaustion. Old traces were saved before continuing within the original deadline; the model and checker were unchanged. The deadline watchdog wrote stop-requested.json, and the main controller recorded hard_deadline_local_stop. The watchdog did not finish its subsequent closeout receipt, so this monitoring session took over evidence-only final checks. stop-audit.json confirms that the controller, engine, verifier, and watchdog have all stopped and their Linux namespace is empty. Shared WSL was not restarted, and results were not published.

The ks monitoring automation was deleted; its receipt is final/automation-cleanup.json.

Host contributions: literature review and 31-ray reproduction, frozen checker, run isolation/timing/monitoring, initial optional search helpers, concurrent temporary-file repair, and recovery scheduling. Model contributions: search programs and strategies written/selected/executed through ObjRun; original inputs and outputs are saved in the database and requests. Existing tools: ObjRun, PySAT/SAT solvers, SymPy, scientific Python, Bun/SQLite, and bubblewrap. Code versions, random seeds, candidate coordinates, graphs, encodings, certificates, and receipts are retained in the separate run directory.

Key files: frozen-g.json; baseline-audit.*; reference/RESEARCH.md; runtime-manifest.json; engine/; work/; code-history/; verified/; final/summary.json; final/usage.json; final/stop-audit.json; final/evidence-manifest.json.
'''
(final/'REPORT.md').write_text(text,encoding='utf-8')
shutil.copytree(Path(__file__).resolve().parent,run/'host-source',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
# Hash complete saved evidence without traversing the read-only dependency junction.
manifest={}
for folder,dirs,files in os.walk(run,followlinks=False):
    dirs[:]=[d for d in dirs if d not in ['node_modules','__pycache__'] and not Path(folder,d).is_symlink()]
    for name in files:
        p=Path(folder,name);rel=p.relative_to(run).as_posix()
        if rel=='final/evidence-manifest.json':continue
        h=hashlib.sha256()
        with p.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
        manifest[rel]={'sha256':h.hexdigest(),'bytes':p.stat().st_size}
write(final/'evidence-manifest.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'excluded':'External node_modules junction and __pycache__ only; manifest excludes itself. No secrets printed.','files':manifest})
print(json.dumps({'primary_success':False,'minimum_valid_n':31,'candidates_rechecked':s['candidate_artifacts_rechecked'],'valid_artifacts':s['valid_artifacts'],'elapsed_search_seconds':18000,'recorded_cost_usd':s['usage']['recorded_cost_usd'],'no_cost_receipt':s['usage']['without_cost_receipt'],'no_response':s['usage']['without_response'],'automation':'deleted','manifest_files':len(manifest),'report':str(final/'REPORT.md')}))
