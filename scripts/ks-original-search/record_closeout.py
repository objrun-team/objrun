"""Finalize saved-evidence metadata only. No models, solvers, or new search."""
import json,hashlib,collections,os,shutil
from pathlib import Path
from datetime import datetime,timezone
root=Path(__file__).resolve().parents[2]
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
text=f'''本轮已完成，主目标未达成。冻结基线为31条互异实三维射线，目标始终为至多30条；最终最小有效集合为31条。

真实 ObjRun 引擎始终使用 OpenRouter deepseek/deepseek-v4.1-flash。北京时间2026年10月31日19:57:42.102开始，2026年11月1日00:57:42.102截止，搜索窗口18000秒；截止后仅复核已保存证据。117次请求的模型标识均匹配固定模型。

终检重建了{s['candidate_artifacts_rechecked']}份不同文件内容的候选，{s['valid_artifacts']}份通过。其中126份为31射线文件；这不是非同构集合数量，也不代表发现新构造。三份拒绝证据分别为空集合、26射线可着色集合和235射线可着色集合。未发现通过完整独立终检的至多30射线集合。

证据等级：精确有理数/实二次域坐标验证、非零及射线去重、全部正交对和正交三元组重建、完整DIMACS编码、可重放DPLL不可满足证书；另一套SymPy精确几何与位掩码SAT实现重新构建并复核。基线为31条射线、71个正交对、17个正交三元组。冻结checker哈希仍与运行前一致，40项预检已通过。

费用按116份含费用的API回执合计 **USD {s['usage']['recorded_cost_usd']}**。117次请求均有响应，无仍在等待响应的请求。第89次请求因上下文超限被提供方拒绝（HTTP400），没有费用回执，其费用状态未知，未按零计入。原始回执与逐请求明细保存在requests/、calls.jsonl、final/usage.json。

本轮执行了整数与实二次域坐标池、旋转并集、删点替换及SAT隐式击中集搜索。两项最终289射线池搜索分别记录6340与6500次迭代，但未给出有效的更小集合。模型日志中的有限池排除结论未纳入独立认证结论；有限搜索不构成R³普遍下界。复现或生成31射线候选仅为部分成果。

两次基础设施恢复分别处理工具消息衔接故障和提供方上下文超限；保存旧轨迹后在原截止时间内继续，模型与checker未变。截止守护写下stop-requested.json，主控制器记录hard_deadline_local_stop；守护未完成后续收尾回执，故由本次监控接手纯证据终检。stop-audit.json确认控制器、引擎、验证器、守护均已停止，所属Linux命名空间为空。未重启共享WSL，未发布结果。

监控自动化ks已删除，回执为final/automation-cleanup.json。

宿主贡献：文献与31射线复现、冻结checker、运行隔离/计时/监控、初始可选搜索辅助程序、并发临时文件修复和恢复调度。模型贡献：经ObjRun编写/选择/执行的搜索程序与策略，原始输入输出保存在数据库和requests中。已有工具贡献：ObjRun、PySAT/SAT求解器、SymPy、科学Python、Bun/SQLite及bubblewrap。代码版本、随机种子、候选坐标、图、编码、证书和回执均保留在独立运行目录。

主要文件：frozen-g.json；baseline-audit.*；reference/RESEARCH.md；runtime-manifest.json；engine/；work/；code-history/；verified/；final/summary.json；final/usage.json；final/stop-audit.json；final/evidence-manifest.json。
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
