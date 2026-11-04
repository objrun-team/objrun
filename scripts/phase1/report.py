"""Build a phase-1 evidence report; completed pilots require separate acceptance."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs/phase1'
PILOTS = DOCS / 'pilots'
RUNS = {
    'gpqa': 'phase1-gpqa-2026-10-07T21-35-26-479Z',
    'cmt': 'phase1-cmt-2026-10-07T21-35-57-664Z',
    'aime': 'phase1-aime-2026-10-07T21-38-19-542Z',
    'chembench': 'phase1-chembench-2026-10-07T21-39-14-785Z',
    'chemiq': 'phase1-chemiq-2026-10-07T21-39-46-436Z',
    'atmossci-bench': 'phase1-atmossci-bench-2026-10-07T21-34-07-121Z',
    'lab-bench': 'phase1-lab-bench-2026-10-07T21-37-30-940Z',
    'humaneval-plus': 'phase1-humaneval-plus-2026-10-07T21-44-47-134Z',
    'scicode': 'phase1-scicode-verified-2026-10-07T21-48-09-120Z',
    'atomworld': 'phase1-atomworld-2026-10-07T22-03-23-513Z',
    'llm-srbench': 'phase1-llm-srbench-2026-10-07T22-05-05-487Z',
    'biocoder': 'phase1-biocoder-2026-10-07T22-10-01-874Z',
}
SUBSETS = {
    'gpqa': 'Diamond，前10题；固定选项顺序',
    'cmt': '官方数据前10个完整问题',
    'aime': '2024 I 前10题；准备数据含2024/2025共60题',
    'chembench': '预先排除12个官方非正目标缺陷题后的seed=0顺序前10题；确定性评分',
    'chemiq': '官方默认首10题；RDKit/OPSIN，保留官方长度限制',
    'atmossci-bench': 'MCQ10 前10题；开放题待验证',
    'lab-bench': '公开 ProtocolQA 前10题；纯文本，其他图像类别待验证',
    'humaneval-plus': 'v0.1.10前10题，全部base+plus测试；隔离RPC有额外计时开销',
    'scicode': 'SciCode-Verified v2：10个完整问题、39个子步骤；原始版待下载',
    'atomworld': 'AddAtomAction 前10题；stol=0.5，primitive_cell=false',
    'llm-srbench': '作者公开LSR-Transform；30个训练样本可见，其余训练点反馈，全部测试点终判',
    'biocoder': 'Rosalind 10题；官方输出比较；完整GitHub Python/Java模糊测试队列待验证',
    'scienceworld': '10个原生测试variation完整动作episode；120秒/100动作',
}
DEFERRED = {
    'minif2f': 'Lean/Mathlib 工具链与构建缓存；按用户要求暂缓。',
    'putnambench': 'Lean/Mathlib 工具链与构建缓存；按用户要求暂缓。',
    'deepswe': '逐仓库镜像及修复环境；112/113与v1/v1.1仍待核，按用户要求暂缓。',
    'terminal-bench': '逐任务容器；隐藏测试隔离仍待审计，按用户要求暂缓。',
    'skillsbench': '逐任务容器；76/87口径与参考环境故障仍待核，按用户要求暂缓。',
    'scienceagentbench': 'verified 数据与官方容器环境；按用户要求暂缓。',
    'astrovisbench': '官方工作流要求约100GB余量；按用户要求暂缓。',
}
DATASET_COUNTS = {'gpqa': 198, 'cmt': 50, 'aime': 60, 'chembench': 2785, 'chemiq': 816, 'humaneval-plus': 164, 'atomworld': 1000, 'atmossci-bench': 670, 'lab-bench': 108, 'scicode': 64}
DIAGNOSTIC_REASONS = {
    'phase1-gpqa-2026-10-07T20-50-33-704Z': '答案格式校准，非预定10题试跑。',
    'phase1-gpqa-2026-10-07T20-52-31-336Z': '启动时没有源码快照；不补填历史版本。',
    'phase1-cmt-2026-10-07T20-53-10-226Z': '启动时没有源码快照；不补填历史版本。',
    'phase1-scicode-verified-2026-10-07T21-08-34-504Z': '首题预检，非10题试跑。',
    'phase1-scicode-verified-2026-10-07T21-09-58-497Z': '评分适配存在比较模块/Sympy传输故障；不得宣传该轮模型通过率。',
    'phase1-atmossci-bench-2026-10-07T21-31-35-133Z': '评分路由配置错误导致404；保留10题与费用。',
    'phase1-lab-bench-2026-10-07T21-33-17-084Z': '评分路由404，完成6题后中止第7题；数据库费用另核。',
    'phase1-scienceworld-2026-10-07T22-10-54-693Z': '评分与终判路由匹配遗漏斜杠，返回404；保留7个故障episode及中止第8题的费用。',
}

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def peak_cost(usage):
    inp, out, cached = [float(x or 0) for x in usage]
    return ((inp - cached) * .3 + cached * .006 + out * 1.2) / 1e6

def scicode_control_evidence(ids):
    expanded=read(DOCS/'scicode-expanded-controls.json')
    negative=read(DOCS/'scicode-negative-controls.json')
    path=ROOT/'.phase1-data/scicode-verified/vendor/scicode-verified/scicode_verified/problems_test.jsonl'
    problems={str(p['problem_id']):p for p in map(json.loads,path.read_text(encoding='utf-8').splitlines())}
    expected={(pid,step['step_number']) for pid in ids for step in problems[pid]['sub_steps']}
    positive=expanded['records']
    wrong=[r for r in negative['records'] if r['kind']=='wrong_return']
    syntax=[r for r in negative['records'] if r['kind']=='syntax_error']
    if not expanded.get('complete') or not expanded.get('allPassed') or not negative.get('complete') or not negative.get('allPassed'):
        raise ValueError('SciCode selected-step grader controls are incomplete or failing')
    if len(positive)!=len(expected) or {(r['problem'],r['step']) for r in positive}!=expected:
        raise ValueError('SciCode positive control task identity mismatch')
    if len(wrong)!=len(expected) or {(r['problem'],r['step']) for r in wrong}!=expected:
        raise ValueError('SciCode wrong-return control task identity mismatch')
    if len(syntax)!=len(ids) or {r['problem'] for r in syntax}!=set(ids):
        raise ValueError('SciCode syntax controls omit a selected problem')
    for record in positive+negative['records']:
        fixture=ROOT/'examples/benchmark/scicode/fixtures'/record['source']
        if not fixture.resolve().is_relative_to((ROOT/'examples/benchmark/scicode/fixtures').resolve()):
            raise ValueError('Invalid reference fixture path')
        if record['sourceSha256']!=hashlib.sha256(fixture.read_bytes()).hexdigest():
            raise ValueError('SciCode reference control source changed')
        if record.get('valid') is not True:
            raise ValueError('SciCode control contains a grader fault')
    if any(r.get('passed') is not True for r in positive) or any(r.get('passed') is not False or r.get('checkPassed') is not True for r in negative['records']):
        raise ValueError('SciCode control verdict mismatch')
    return {'wholeProblems':len(ids),'positiveSteps':len(positive),'wrongReturnSteps':len(wrong),
            'syntaxProblems':len(syntax),'gradingSeconds':90,'coverage':'Selected Verified v2 steps only',
            'correct':'scicode-expanded-controls.json','negative':'scicode-negative-controls.json',
            'privacyAndExit':'scicode-selfcheck.json','canonicalFullProtocolValidated':False}


def completed(slug, run):
    home = PILOTS / run
    summary, manifest = read(home / 'summary.json'), read(home / 'manifest.json')
    if not summary['completed'] or not manifest.get('sourceDigest'):
        raise ValueError(f'{run}: incomplete generation or missing source snapshot')
    if slug == 'scicode':
        acceptance = read(home / 'whole-problems-reaccepted.json')
        if not acceptance.get('complete') or not acceptance.get('allOriginalVerdictsMatch'):
            raise ValueError('SciCode candidate-identified reacceptance is incomplete or changed')
        candidates = {r['officialId']: hashlib.sha256(r['answer'].encode()).hexdigest() for r in summary['results']}
        identities = [identity for r in acceptance['results'] for identity in r['candidateIdentities']]
        if len(identities) != len(candidates) or {i['officialId'] for i in identities} != set(candidates) or any(i['answerSha256'] != candidates.get(i['officialId']) for i in identities):
            raise ValueError('SciCode reacceptance candidate changed')
        problems_path = ROOT / '.phase1-data/scicode-verified/vendor/scicode-verified/scicode_verified/problems_test.jsonl'
        problems = {str(p['problem_id']):p for p in map(json.loads,problems_path.read_text(encoding='utf-8').splitlines())}
        delivered = {r['officialId']:r['answer'] for r in summary['results']}
        for record in acceptance['results']:
            problem = problems[record['problem']]
            expected_ids = ['scicode-'+step['step_number'] for step in problem['sub_steps']]
            if [i['officialId'] for i in record['candidateIdentities']] != expected_ids:
                raise ValueError('SciCode candidate substep order changed')
            codes = []
            for identity in record['candidateIdentities']:
                answer = delivered[identity['officialId']]
                match = re.search(r'```(?:python)?\s*\n([\s\S]*?)```',answer)
                code = (match[1] if match else answer).strip()
                if hashlib.sha256(code.encode()).hexdigest() != identity['extractedCodeSha256']:
                    raise ValueError('SciCode extracted candidate changed')
                codes.append(code)
            cumulative = problem['required_dependencies']+'\n\n'+'\n\n'.join(codes)
            if hashlib.sha256(cumulative.encode()).hexdigest() != record['cumulativeCodeSha256']:
                raise ValueError('SciCode cumulative candidate changed')
        for name in ['controller.py','grade.py','worker.py','codec.py']:
            if acceptance['graderSourceHashes'].get(name) != hashlib.sha256((ROOT/'examples/benchmark/scicode'/name).read_bytes()).hexdigest():
                raise ValueError('SciCode reacceptance grader source changed')
        verdicts = [r['finalAcceptance'] for r in acceptance['results']]
        ids = [r['problem'] for r in acceptance['results']]
    elif slug == 'scienceworld':
        acceptance = read(home / 'acceptance.json')
        verdicts = [r['final'] for r in acceptance['episodes']]
        ids = [r['id'] for r in acceptance['episodes']]
    else:
        acceptance = read(home / 'acceptance.json')
        verdicts = acceptance['records']
        ids = [r['officialId'] for r in verdicts]
        candidates = {r['officialId']: hashlib.sha256(r['answer'].encode()).hexdigest() for r in summary['results']}
        if any(r['candidateSha256'] != candidates.get(r['officialId']) for r in verdicts):
            raise ValueError(f'{run}: acceptance candidate changed')
    if len(verdicts) != 10 or len(set(ids)) != 10:
        raise ValueError(f'{run}: pilot denominator is not ten distinct complete tasks')
    if any(type(r.get('valid')) is not bool or type(r.get('passed')) is not bool for r in verdicts):
        raise ValueError(f'{run}: malformed verdict')
    control_name = 'scicode' if slug == 'scicode' else 'atmossci' if slug == 'atmossci-bench' else 'lab' if slug == 'lab-bench' else slug
    current_control = ROOT / '.scratch/phase1' / f'{control_name}-selfcheck.json'
    controls = read(current_control if current_control.exists() else DOCS / f'{control_name}-selfcheck.json')
    if controls.get('allPassed') is not True:
        raise ValueError(f'{slug}: grader control did not pass')
    row = {'slug': slug, 'run': run, 'tasks': len(verdicts), 'valid': sum(r['valid'] for r in verdicts), 'passed': sum(r['valid'] and r['passed'] for r in verdicts), 'graderErrors': sum(not r['valid'] for r in verdicts), 'generationUnits': summary['tasks'], 'seconds': sum(r['seconds'] for r in summary['results']), 'usdUpperBound': summary['usdUpperBound'], 'sourceDigest': manifest['sourceDigest'], 'taskIds': ids, 'protocol': SUBSETS[slug], 'acceptance': (home / ('whole-problems-reaccepted.json' if slug == 'scicode' else 'acceptance.json')).relative_to(DOCS).as_posix()}
    if slug == 'scicode':
        row['gradingControls'] = scicode_control_evidence(ids)
    return row

def report():
    world = sorted(PILOTS.glob('phase1-scienceworld-*'))
    if world:
        RUNS['scienceworld'] = world[-1].name
    rows = [completed(slug, run) for slug, run in RUNS.items()]
    if len(rows) != 13:
        raise ValueError('All thirteen selected lightweight pilots must finish before final reporting')
    costs = []
    for p in sorted(PILOTS.glob('*/summary.json')):
        summary = read(p)
        amount = float(summary.get('usdUpperBound', 0))
        db = ROOT / '.phase1-data/pilots' / p.parent.name / 'data/h2h.sqlite'
        db_amount = None
        if db.exists():
            with sqlite3.connect(f'file:{db.as_posix()}?mode=ro', uri=True) as conn:
                usage = conn.execute('select sum(prompt_tokens),sum(completion_tokens),sum(cached_tokens) from agent_bot_msg').fetchone()
                db_amount = peak_cost(usage)
        costs.append({'run': p.parent.name, 'classification': 'selected_pilot' if p.parent.name in RUNS.values() else 'diagnostic', 'generationUnitsCompleted': summary['tasks'], 'completed': summary['completed'], 'summaryUpperBoundUsd': amount, 'databaseRecordedUpperBoundUsd': db_amount, 'recordedUpperBoundUsd': max(amount, db_amount or 0), 'reason': DIAGNOSTIC_REASONS.get(p.parent.name)})
    recorded = sum(c['recordedUpperBoundUsd'] for c in costs)
    reserve = read(DOCS / 'cost-reconciliation.json')['unreportedUsageReserveUsd']
    output = {'createdAt': datetime.now(timezone.utc).isoformat(), 'scope': '13 lighter preparation pilots completed; 7 high-storage benchmarks deferred by user. Variants/subsets remain explicit; full 20-benchmark canonical readiness is not claimed.', 'pilotBenchmarks': len(rows), 'pilotWholeTasks': sum(r['tasks'] for r in rows), 'pilotGenerationUnits': sum(r['generationUnits'] for r in rows), 'pilotCostUpperBoundUsd': sum(r['usdUpperBound'] for r in rows), 'allRecordedModelCostUpperBoundUsd': recorded, 'unreportedUsageReserveUsd': reserve, 'budgetAccountedUpperBoundUsd': recorded + reserve, 'budgetUsd': 30, 'providerInvoiceVerified': False, 'pilots': rows, 'deferred': DEFERRED, 'costLedger': costs}
    if output['budgetAccountedUpperBoundUsd'] > 30:
        raise ValueError('Shared pilot cap exceeded')
    (DOCS / 'results.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    registry = read(DOCS / 'benchmarks.json')
    registry['updatedAt'] = output['createdAt']
    registry['executionScope'] = output['scope']
    by_slug = {r['slug']: r for r in rows}
    sources = {}
    for bench in registry['benchmarks']:
        slug = bench['slug']
        source_home = 'scicode-verified' if slug == 'scicode' else slug
        file = ROOT / '.phase1-data' / source_home / 'source.json'
        if file.exists():
            sources[slug] = read(file)
            if sources[slug].get('commit') and slug != 'scicode': bench['sourceCommit'] = sources[slug]['commit']
        if slug in by_slug:
            row = by_slug[slug]
            bench.update(state='pilot_variant_only' if slug == 'scicode' else 'pilot_validated_subset', pilotTasksCompleted=row['tasks'], pilotPassed=row['passed'], pilotValid=row['valid'], pilotRun=row['run'], protocol=row['protocol'], selfCheck='Passed controls; exact coverage and limitations in selfcheck artifact', canonicalFullProtocolValidated=False)
            if slug == 'scicode':
                original = read(ROOT / '.phase1-data/scicode/source.json')
                bench['sourceCommit'] = bench['originalSourceCommit'] = original['commit']
                bench['pilotSourceCommit'] = sources[slug]['commit']
                sources[slug] = {'original': original, 'pilotVariant': sources[slug], 'variantLabel': 'SciCode-Verified v2'}
                bench['pilotVariant'] = 'SciCode-Verified v2'
                bench['gradingControls'] = row['gradingControls']
                bench['selfCheck'] = '39 selected-step correct and wrong-return controls, 10 syntax controls, plus private-target/fixture/exit probes passed.'
                bench['remaining'] = 'Original data quota; canonical multi-environment/1800s; unselected class/helper-dependent tasks remain unvalidated.'
        else:
            bench.update(state='deferred_storage', pilotTasksCompleted=0, deferReason=DEFERRED[slug])
    (DOCS / 'benchmarks.json').write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (DOCS / 'benchmark-sources.json').write_text(json.dumps(sources, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    text = ['# 第一阶段轻量试跑报告', '', '用户要求需要大量空间的先不跑。本轮完成13个测试集的限定子集/版本试跑，每集10个完整任务；7个测试集暂缓。原文档的20集完整标准仍未全部满足。以下是接入与评分准备证据，不能用来判断ObjRun相对基线的收益。', '', f"模型：DeepSeek-V4.1-Flash。正式保留试跑的费用估计为 ${output['pilotCostUpperBoundUsd']:.4f}；计入诊断及SQLite中额外用量，共 ${recorded:.4f}。另保留 ${reserve:.2f} 中断请求预算，合计 ${recorded+reserve:.4f}，低于首轮 $30 上限。尚未核对服务商账单。", '', '| 测试集/子集 | 独立终判通过/全部题 | 有效终判 | 模型费用上界（美元） | 单题平均秒数 | 证据 |', '|---|---:|---:|---:|---:|---|']
    for r in rows:
        text.append(f"| {r['slug']}：{r['protocol']} | {r['passed']}/{r['tasks']} | {r['valid']}/{r['tasks']} | {r['usdUpperBound']:.6f} | {r['seconds']/r['tasks']:.1f} | [独立验收]({r['acceptance']}) |")
    text += ['', 'ScienceWorld的耗时包含交互；SciCode包含同一整题全部子步骤。拒绝与无效终判分别记录，未删题缩小分母。SciCode选中39个步骤的独立正确控制及错误返回控制均已通过，另有10个语法异常与隐藏目标/参考文件/退出控制；完整原始版和规范多环境复现待完成。39个子步骤不单独计为39道整题。', '', '## 费用与后续资源', '', '上表费用按实际记录token与公开峰值单价估算，包含重试/修改；正式实验的题量、模型、超时和组别不同，不能直接把这批固定顺序的10题外推为完整榜成绩或可靠账单。results.json保留每轮诊断费用。后续预算可用每集“试跑费用÷10×计划题量×实验组数”作为初始量级，再预留长尾；重型集未试跑，暂不虚构费用或耗时。正式比较仍须独立重试、自改进、ObjRun同条件三组及文档要求的代表性控制。', '', '## 暂缓清单', '']
    text += [f'- {slug}：{reason}' for slug, reason in DEFERRED.items()]
    text += ['', '## 测量与复现', '', '每轮manifest记录模型配置、启动时源码摘要、任务ID与数据版本；task文件保存实际交付候选和工具调用，SQLite保留原始用量。终判在该任务生成结束后独立执行，未用于挑选、修改或停止。符号回归的反馈仅用训练数据，终判专用/accept读取测试集。代码候选由UID65534在只读、无网络容器执行；数值目标/隐藏测试只在root评分端。ScienceWorld记录初始/最终状态摘要及私有完整动作轨迹。', '', '固定依赖及镜像见environment.json与examples/benchmark/_lib/requirements-*.txt。大数据和私有测试在被git忽略的.phase1-data中，公开证据只保存版本、摘要和判决。评分控制覆盖见各*selfcheck.json；没有把未验证的协议写为完成。', '', '公共修复通过类型检查、11条实际评分/候选/故障回归及4条Python评分服务测试。论文已撤下94.4/85.1及未核实的软件榜胜出比较，并重建PDF；历史出处见legacy-scores.md。', '']
    lab=read(PILOTS/RUNS['lab-bench']/'abstention.json')
    text += ['', '## 补充终判指标', '', f"LAB本轮弃答{lab['abstentions']}/10，交付格式无效{lab['invalidFormat']}/10；总分母仍为10题。每题身份与候选摘要见该轮abstention.json。", '', '符号回归已对同一批冻结候选独立复评并保存逐题NMSE等数值误差，布尔终判与原记录全部一致。见该轮numerical-metrics.json；当前LSR-Transform发布行没有单列ood_input/output，不能把普通test误差声称为已经验证的外推误差。', '', 'SciCode已对冻结的39份实际交付答案补做带候选摘要的独立复评，逐步骤及整题布尔判决与原验收全部一致。独立正确控制按公开问题定义编写，未进入模型上下文；优化前的超时控制保留为诊断。\n\n后续软件及科学评分接口修复、真实HTTP/缓存回归见completion-audit.md；这些是代码证据，没有将其记成软件榜官方试跑完成。', '']
    (DOCS / 'report.md').write_text('\n'.join(text), encoding='utf-8')
    estimates = ['# 后续实验费用初估', '', '仅使用本轮模型token记录按峰值单价线性缩放；不是账单、承诺或充分资源预算。固定顺序的10题在题型与难度上有偏差；三组协议、长尾运行时间和模型不同都可能改变费用。旧软件榜与重型集没有本轮可靠数据，保持待估。', '', '| 本轮协议 | 已下载数据/子集题数 | 10题×3组（美元） | 全子集×3组量级（美元） |', '|---|---:|---:|---:|']
    for r in rows:
        n = DATASET_COUNTS.get(r['slug'])
        estimates.append(f"| {r['slug']} | {n if n else '完整范围待定'} | {r['usdUpperBound']*3:.4f} | {format(r['usdUpperBound']/10*n*3,'.4f') if n else '待定'} |")
    estimates += ['', 'SciCode题数是Verified v2的64个整题，包含本轮未实现的类/辅助函数依赖题，不表示这64题已能执行。ChemBench总数含12个非正目标题；正式结果保留完整分母并单列官方指标缺陷。AtmosSci仅计MCQ10数据670题、LAB仅计ProtocolQA 108题、AtomWorld仅计AddAtomAction 1000题；没有将这些子集称作完整benchmark。AIME为2024/2025共60题。BioCoder完整GitHub测试队列、符号回归完整发现协议与ScienceWorld正式variation清单须先确定。', '', '资源当前按轻量试跑限制：数值/代码评分容器2 CPU/2GB、无网络；文本评分容器1GB；ScienceWorld JVM堆512MB。它们是本轮上限，不是正式多环境/仓库修复协议的资源需求。当前C盘无余量，F盘约1GB；重型镜像、Lean/Mathlib与约100GB的AstroVisBench环境暂缓。', '', '阶段二执行前先固定实际20集题量、U/self-refine/ObjRun三组条件与文档指定的8个代表集A–E控制。以本表定初始量级，在每个更改后的正式协议抽样验证成本后再扩大。每个模型调用、失败与无用量请求都计入共享预算；不按通过题数计算费用。', '']
    (DOCS / 'experiment-estimates.md').write_text('\n'.join(estimates), encoding='utf-8')
    print(json.dumps({k: output[k] for k in ['pilotBenchmarks', 'pilotWholeTasks', 'pilotCostUpperBoundUsd', 'allRecordedModelCostUpperBoundUsd', 'budgetAccountedUpperBoundUsd']}))

if __name__ == '__main__':
    report()
