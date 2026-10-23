"""Read existing cost metadata only; no graders, parsers, providers or runtime changes."""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "docs/repair-2026-10-08/campaigns"
OUT = ROOT / "docs/repair-2026-10-08"
PILOT_RUNS = {"repair-2026-10-08T06-06-06-739Z", "repair-2026-10-08T06-06-41-201Z", "repair-2026-10-08T06-51-16-840Z"}
RATES = {"input": 0.3, "cachedInput": 0.006, "output": 1.2}
SOURCES, AUDIT = [], []


def read(path):
    for attempt in range(4):
        try:
            raw = path.read_bytes()
            value = json.loads(raw)
            SOURCES.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"),
                            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                            "readAt": datetime.now(timezone.utc).isoformat()})
            return value
        except json.JSONDecodeError:
            if attempt == 3:
                raise
            time.sleep(0.05)


def stats(values):
    values = sorted(values)
    if not values:
        return {"n": 0, "mean": None, "max": None}
    return {"n": len(values), "min": values[0], "mean": statistics.mean(values),
            "median": statistics.median(values), "p90NearestRank": values[math.ceil(0.9 * len(values))-1],
            "max": values[-1]}


def usage(call):
    item = call.get("usage") or {}
    inp, out = item.get("prompt_tokens"), item.get("completion_tokens")
    cache = item.get("prompt_cache_hit_tokens", (item.get("prompt_tokens_details") or {}).get("cached_tokens", 0))
    valid = all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in [inp, out, cache])
    return (inp, out, cache) if valid and cache <= inp else None


def call_info(call):
    counts = usage(call)
    if counts:
        inp, out, cache = counts
        formula = ((Decimal(inp-cache)*Decimal("0.3") + Decimal(cache)*Decimal("0.006") + Decimal(out)*Decimal("1.2"))/Decimal(1_000_000))
        no_cache = (inp*0.3 + out*1.2)/1_000_000
    else:
        inp = out = cache = None
        formula = no_cache = None
    declared = call.get("usdUpperBound", call.get("accountedUpperBoundUsd"))
    return {"calls": 1, "inputTokens": inp, "outputTokens": out, "cacheTokens": cache,
            "inputMissTokens": inp-cache if counts else None, "usdUpperBound": declared,
            "recomputedUsdUpperBound": float(formula) if formula is not None else None,
            "noCacheUsd": no_cache, "closed": bool(call.get("finishedAt")),
            "httpStatus": call.get("httpStatus"), "fault": call.get("fault"),
            "basis": call.get("costBasis", "legacy_inferred_reported_usage" if counts and declared is not None else "pending")}


def aggregate(tasks):
    fields = ["calls", "inputTokens", "inputMissTokens", "outputTokens", "cacheTokens", "usdUpperBound", "noCacheUsd"]
    totals = {key: sum(task[key] for task in tasks) for key in fields}
    return {"taskRuns": len(tasks), "uniqueOfficialTasks": len({task["officialId"] for task in tasks}),
            "runs": sorted({task["run"] for task in tasks}), "totals": totals,
            "perTask": {key: stats([task[key] for task in tasks]) for key in fields},
            "cacheShareOfInput": totals["cacheTokens"]/totals["inputTokens"] if totals["inputTokens"] else None,
            "elapsedSeconds": stats([task["elapsedSeconds"] for task in tasks]),
            "nearOrPastSolveDeadline": sum(task["elapsedSeconds"] >= task["solveSeconds"] for task in tasks)}


cohorts = []
tasks = []
in_flight = []
closed_paid = 0.0
for directory in sorted(BASE.iterdir()):
    if not (directory / "api-ledger.json").exists():
        continue
    ledger = read(directory / "api-ledger.json")
    manifest = read(directory / "manifest.json")
    summary = read(directory / "summary.json")
    calls = ledger.get("calls", [])
    infos = [call_info(call) for call in calls]
    sum_rows = sum(info["usdUpperBound"] or 0 for info in infos)
    cost = ledger.get("recordedUsageUpperBoundUsd", 0)
    reserved = ledger.get("reservedUpperBoundUsd", 0)
    row_error = abs(sum_rows-cost)
    mismatches = [i for i, info in enumerate(infos) if info["recomputedUsdUpperBound"] is not None and info["usdUpperBound"] is not None and abs(info["recomputedUsdUpperBound"]-info["usdUpperBound"]) > 1e-9]
    AUDIT.append({"run": directory.name, "calls": len(calls), "rowSumUsd": sum_rows, "ledgerRecordedUsd": cost,
                  "absoluteDifferenceUsd": row_error, "usageFormulaMismatchIndices": mismatches,
                  "invalidUsageCount": sum(usage(call) is None for call in calls),
                  "notFinishedCount": sum(not info["closed"] for info in infos),
                  "pendingCount": sum(ledger.get("pending", {}).values()), "reservedUsd": reserved,
                  "validCostArithmetic": row_error < 1e-9 and not mismatches})
    if summary.get("completed") is True:
        closed_paid += cost + max(0, reserved)
    else:
        in_flight.append({"run": directory.name, "profile": manifest.get("profile"), "benchmarks": manifest.get("benchmarks"),
                          "status": "in_flight_not_final", "completed": summary.get("completed"), "fatal": summary.get("fatal") or ledger.get("fatal"),
                          "plannedTaskRuns": summary.get("plannedTaskRuns"), "recordedTaskRuns": len(summary.get("records", [])),
                          "receiptCallsObserved": len(calls), "closedReceiptCallsObserved": sum(info["closed"] for info in infos),
                          "recordedUsageUpperBoundUsd": cost, "reservedUpperBoundUsd": max(0, reserved),
                          "pendingCount": sum(ledger.get("pending", {}).values()),
                          "capUsd": ledger.get("capUsd"), "lastReceiptStartedAt": calls[-1].get("startedAt") if calls else None,
                          "lastReceiptFinishedAt": calls[-1].get("finishedAt") if calls else None,
                          "limits": "Ledger and summary are separate live snapshots. Progress/cost only, no final score or success rate; excludes any remaining future requests."})
    if summary.get("completed") is not True or manifest.get("profile") != "pilot" or directory.name not in PILOT_RUNS:
        continue
    routes = defaultdict(list)
    for call in calls:
        routes[call["route"]].append(call)
    attributed = set()
    cohort_tasks = []
    task_seconds = manifest.get("taskSeconds", {})
    for record in summary.get("records", []):
        task_path = directory / f"task-{record['index']}.json"
        original = read(task_path)
        route_names = {call["route"] for call in original.get("apiCalls", [])}
        if len(route_names) != 1:
            raise RuntimeError("Pilot task route is ambiguous: " + str(task_path))
        route = next(iter(route_names))
        if route in attributed:
            raise RuntimeError("Pilot route attributed twice")
        attributed.add(route)
        cs = routes[route]
        if any(usage(call) is None or not call.get("finishedAt") for call in cs):
            raise RuntimeError("Completed pilot has an incomplete cost receipt")
        ti = [call_info(call) for call in cs]
        fields = ["calls", "inputTokens", "inputMissTokens", "outputTokens", "cacheTokens", "usdUpperBound", "noCacheUsd"]
        summed = {key: sum(call[key] for call in ti) for key in fields}
        copied_cost = sum(call.get("usdUpperBound", 0) for call in original.get("apiCalls", []))
        if len(cs) != len(original.get("apiCalls", [])) or abs(copied_cost-summed["usdUpperBound"]) > 1e-9:
            raise RuntimeError("Pilot task/ledger receipt mismatch")
        seconds = task_seconds.get(record["benchmark"], task_seconds.get("default", 180)) if isinstance(task_seconds, dict) else task_seconds
        task = {"run": directory.name, "index": record["index"], "benchmark": record["benchmark"], "arm": record["arm"],
                "replica": record.get("replica", 0), "officialId": record["officialId"], "route": route,
                "elapsedSeconds": record.get("seconds", 0), "solveSeconds": seconds, **summed}
        tasks.append(task)
        cohort_tasks.append(task)
    if set(routes) != attributed:
        raise RuntimeError("Unattributed completed pilot receipt route")
    by_group = defaultdict(list)
    for task in cohort_tasks:
        by_group[(task["benchmark"], task["arm"])].append(task)
    cohorts.append({"run": directory.name, "profile": manifest["profile"], "schemaVersion": manifest.get("schemaVersion"),
                    "benchmarks": manifest["benchmarks"], "arms": manifest["arms"], "taskSeconds": manifest.get("taskSeconds"),
                    "costUsd": cost, "calls": len(calls), "taskRuns": len(cohort_tasks),
                    "groups": [{"benchmark": key[0], "arm": key[1], **aggregate(rows)} for key, rows in sorted(by_group.items())]})

groups_map = defaultdict(list)
for task in tasks:
    groups_map[(task["benchmark"], task["arm"])].append(task)
group_summary = {key: aggregate(rows) for key, rows in groups_map.items()}
projections = []
for name, n, full_seconds in [("chembench", 500, 600), ("aime", 60, 600), ("cmt", 50, 1800)]:
    u, f = group_summary[(name, "U")], group_summary[(name, "F")]
    ratio = full_seconds/180
    projection = {"benchmark": name, "officialTasks": n, "plannedTaskRuns": 2*n,
                  "sampleTasksPerArm": {"U": u["taskRuns"], "F": f["taskRuns"]}, "pilotSeconds": 180, "fullSeconds": full_seconds,
                  "FDeadlineSensitivityMultiplier": ratio,
                  "empiricalPilotMeanUsd": n*(u["perTask"]["usdUpperBound"]["mean"]+f["perTask"]["usdUpperBound"]["mean"]),
                  "allTasksAtObservedArmMaxUsd": n*(u["perTask"]["usdUpperBound"]["max"]+f["perTask"]["usdUpperBound"]["max"]),
                  "noCachePilotMeanUsd": n*(u["perTask"]["noCacheUsd"]["mean"]+f["perTask"]["noCacheUsd"]["mean"]),
                  "FDeadlineSensitivityMeanUsd": n*(u["perTask"]["usdUpperBound"]["mean"]+ratio*f["perTask"]["usdUpperBound"]["mean"]),
                  "FDeadlineAndNoCacheSensitivityMeanUsd": n*(u["perTask"]["noCacheUsd"]["mean"]+ratio*f["perTask"]["noCacheUsd"]["mean"])}
    projections.append(projection)
columns = ["empiricalPilotMeanUsd", "allTasksAtObservedArmMaxUsd", "noCachePilotMeanUsd", "FDeadlineSensitivityMeanUsd", "FDeadlineAndNoCacheSensitivityMeanUsd"]
combined = {column: sum(projection[column] for projection in projections) for column in columns}
combined.update({"officialTasks": 610, "plannedTaskRuns": 1220, "arms": ["U", "F"], "workers": 4})
round5 = lambda x: 5*math.ceil(x/5)
combined["preparedIncrementalUsd"] = round5(combined["FDeadlineSensitivityMeanUsd"]*1.25+5)
combined["noCacheStressPreparedIncrementalUsd"] = round5(combined["FDeadlineAndNoCacheSensitivityMeanUsd"]*1.25+5)
cmt_u, cmt_f = group_summary[("cmt", "U")], group_summary[("cmt", "F")]
chemiq = {"officialTasks": 10, "plannedTaskRuns": 20, "arms": ["U", "F"], "actualChemiqSampleTasks": 0,
          "proxy": "CMT U/F completed-pilot cost only; not a ChemIQ measurement or expected score",
          "proxyPilotMeanUsd": 10*(cmt_u["perTask"]["usdUpperBound"]["mean"]+cmt_f["perTask"]["usdUpperBound"]["mean"]),
          "proxyAllTasksAtObservedArmMaxUsd": 10*(cmt_u["perTask"]["usdUpperBound"]["max"]+cmt_f["perTask"]["usdUpperBound"]["max"]),
          "proxyNoCacheMeanUsd": 10*(cmt_u["perTask"]["noCacheUsd"]["mean"]+cmt_f["perTask"]["noCacheUsd"]["mean"]),
          "preparedIncrementalUsd": 5, "pilotSeconds": 180}
current_held = closed_paid + sum(run["recordedUsageUpperBoundUsd"] + run["reservedUpperBoundUsd"] for run in in_flight)
budget = {"costAlreadyClosedUsd": closed_paid, "currentRecordedPlusReservedSnapshotUsd": current_held,
          "formula": "After GPQA closes, B = sum(all existing paid ledgers' recorded cost plus outstanding reserve). ChemIQ cap >= B+5. After ChemIQ, combined cap >= actual cumulative B_after+60; cache-loss stress alternative >= B_after+225. These are preparation scenarios, not deterministic completion bounds.",
          "combinedAdditionalPreparationUsd": combined["preparedIncrementalUsd"], "chemiqAdditionalPreparationUsd": 5,
          "combinedCacheLossStressAdditionalUsd": combined["noCacheStressPreparedIncrementalUsd"],
          "ordinaryCumulativePreparationIfCurrentFullStaysWithinIts15UsdGuard": round5(15+5+combined["preparedIncrementalUsd"]),
          "cacheLossStressCumulativePreparationIfCurrentFullStaysWithinIts15UsdGuard": round5(15+5+combined["noCacheStressPreparedIncrementalUsd"]),
          "ordinaryMarginPolicy": "1.25 x cached F deadline sensitivity scenario + USD5 for AIME single-question/selection uncertainty, rounded up to USD5; ChemIQ gets a separate USD5 proxy preparation envelope.",
          "limits": "The USD15 guard was root-chosen, not a user spending cap. A larger guard authorizes space for costs, not automatic expenditure. No fixed dollar amount proves completion: first ordered pilot questions are not random representative samples; long full deadlines, cache behavior, question difficulty and branching can change costs."}

report = {"observedAt": datetime.now(timezone.utc).isoformat(), "method": "Read completed pilot manifests, api-ledger and original task records; join every route once, check task/ledger copies and recompute frozen token formula. No candidate parsing or grader execution.",
          "ratesUsdPerMillion": RATES, "ratesStatus": "Frozen experiment accounting rates, not independently verified provider invoices or a new live pricing quote",
          "inputTokenMeaning": "inputTokens includes cacheTokens; cached tokens are a subset, not an extra additive token count.",
          "quantiles": "Per-task and per-call p90 use nearest rank. Means/maxima describe observed samples, not confidence bounds.",
          "cohorts": cohorts, "groups": [{"benchmark": key[0], "arm": key[1], **summary} for key, summary in sorted(group_summary.items())],
          "perCall": [], "supportCohortPolicy": "These three completed pilot run IDs are fixed for this review. A later rerun refreshes live cumulative cost, but does not silently add a new pilot to the prediction support.",
          "pilotTaskCosts": tasks, "arithmeticAudit": AUDIT, "inFlight": in_flight,
          "projections": projections, "combined": combined, "chemiqPilot": chemiq, "budgetPreparation": budget,
          "sources": SOURCES, "executionSourceSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
per_call = []
for directory in sorted(BASE.iterdir()):
    if any(cohort["run"] == directory.name for cohort in cohorts):
        # These completed raw ledgers are stable; they are only reread for distribution grouping.
        ledger = json.loads((directory / "api-ledger.json").read_bytes())
        for call in ledger["calls"]:
            row = call_info(call)
            path = call["route"].split("/")
            row.update({"benchmark": path[1], "arm": path[2]})
            per_call.append(row)
report["perCall"] = [{"benchmark": benchmark, "arm": arm, "calls": len(rows),
                      **{key: stats([row[key] for row in rows]) for key in ["inputTokens", "inputMissTokens", "outputTokens", "cacheTokens", "usdUpperBound", "noCacheUsd"]}}
                     for (benchmark, arm), rows in sorted(((key, [row for row in per_call if (row["benchmark"],row["arm"]) == key]) for key in groups_map))]
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "next-wave-cost-review.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")


def number(value, places=6):
    return f"{value:,.{places}f}" if places else f"{value:,}"


def mean_max(group, key, places=1):
    values = group["perTask"][key]
    return number(values["mean"], places) + " / " + number(values["max"], places)


lines = ["# 下一波费用核对与预算准备", "",
         "已完成科学 pilot 的 **216 个 task run、859 次 API 调用**逐任务/逐请求对齐，合计费用上界 **$1.262360088**。主要支出来自 CMT F。ChemIQ 尚无本轮付费样本；AIME 只有一题，不能据单题费用保证完整 60 题。当前 GPQA 全量在途，下面仅记进度/费用快照，不给最终成绩或选择性重试建议。", "",
         f"核对时间（UTC）：`{report['observedAt']}`。本分析不调用 LLM、评分器或 CMT parser，不改任何已冻结执行文件。", "",
         "## 原始样本支持", "",
         "费用按已冻结会计费率计算：未缓存 input $0.30/M、缓存 input $0.006/M、output $1.20/M。它是现有实验记录的费用上界口径，不是独立核验后的供应商账单，也不是新的实时价格报价。input 含缓存 token；cache 是 input 的子集，不能重复加算。", "",
         "| 基准/臂 | task run / 不同题目 | 调用总数 | 每任务调用均值 / max | input 总量 | output 总量 | cache hit 总量 | USD 总额 | 每任务 USD 均值 | 每任务 USD max |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
for group in report["groups"]:
    total = group["totals"]
    lines.append(f"| {group['benchmark']} / {group['arm']} | {group['taskRuns']} / {group['uniqueOfficialTasks']} | {total['calls']} | {mean_max(group,'calls')} | {total['inputTokens']:,} | {total['outputTokens']:,} | {total['cacheTokens']:,} | {total['usdUpperBound']:.6f} | {group['perTask']['usdUpperBound']['mean']:.6f} | {group['perTask']['usdUpperBound']['max']:.6f} |")
lines += ["", "R 的 50 个 task run 对应同一批 10 道题各 5 个副本，不是 50 道不同题。GPQA U/F 合并三个完成 pilot，各 12 个 task run 只有 10 道不同题；该重复只用于描述已发生费用，未拿它外推下一波其它基准。CMT/ChemBench 支持均为固定顺序前 10 题；不是随机抽样。", "",
          "每任务 token 分布如下；JSON 另含逐请求/逐任务 min、mean、median、nearest-rank p90、max，以及每个原始 task index 的成本元数据。", "",
          "| 基准/臂 | input 均值 / max | output 均值 / max | cache hit 均值 / max |",
          "|---|---:|---:|---:|"]
for group in report["groups"]:
    lines.append(f"| {group['benchmark']} / {group['arm']} | {mean_max(group,'inputTokens')} | {mean_max(group,'outputTokens')} | {mean_max(group,'cacheTokens')} |")
lines += ["", f"CMT F：10 个 task run 共 {cmt_f['totals']['calls']} 次调用，均值 {cmt_f['perTask']['calls']['mean']:.1f}、max {cmt_f['perTask']['calls']['max']}；费用均值 ${cmt_f['perTask']['usdUpperBound']['mean']:.6f}、max ${cmt_f['perTask']['usdUpperBound']['max']:.6f}。input 缓存比例 {cmt_f['cacheShareOfInput']:.2%}，有 {cmt_f['nearOrPastSolveDeadline']} 个 task 的记录总历时达到/超过 180 秒（包含收尾时间）。完整协议 CMT F 允许 1800 秒，这批费用分布不能当完整时限的上界。", "",
          "## 下一波完整分母：ChemBench500、AIME60、CMT50，U/F", "",
          "总计 610 道题、**1220 个 task run**。下表明确区分实测外推与保守敏感性；所有金额都是增量，不含已有支出。", "",
          "| 基准 | U/F task run | 每臂支持题数 | pilot 均值外推 USD | 全部取已观察臂内 max USD | 均值但无缓存 USD | F 时限敏感性 USD | F 时限 + 无缓存 USD |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
for projection in projections:
    lines.append(f"| {projection['benchmark']} | {projection['plannedTaskRuns']} | {projection['sampleTasksPerArm']['U']} / {projection['sampleTasksPerArm']['F']} | {projection['empiricalPilotMeanUsd']:.3f} | {projection['allTasksAtObservedArmMaxUsd']:.3f} | {projection['noCachePilotMeanUsd']:.3f} | {projection['FDeadlineSensitivityMeanUsd']:.3f} | {projection['FDeadlineAndNoCacheSensitivityMeanUsd']:.3f} |")
lines.append(f"| 合计 | 1220 | — | {combined['empiricalPilotMeanUsd']:.3f} | {combined['allTasksAtObservedArmMaxUsd']:.3f} | {combined['noCachePilotMeanUsd']:.3f} | {combined['FDeadlineSensitivityMeanUsd']:.3f} | {combined['FDeadlineAndNoCacheSensitivityMeanUsd']:.3f} |")
lines += ["", "F 时限敏感性只把 F 的 pilot 平均费用按声明时限倍率放大：ChemBench/AIME 从 180→600 秒，倍率 10/3；CMT 从 180→1800 秒，倍率 10。U 保持实测均值。它是预算压力情景，**不是**成本与时间线性增长的实证模型或置信区间。无缓存情景把全部实测 input 按 $0.30/M 重算。完整题目更难、实际缓存变化、4 worker 对延迟/缓存的影响和分支重试可能使任何这些情景失准。", "",
          "建议完整 combined 波预留 **增量 $60**：缓存保持的 F 时限敏感性 $40.118 × 1.25，再加 $5 的 AIME 单题/选择不确定性工程预留，按 $5 向上取整。若要覆盖缓存明显失效的压力情景，另一个较保守准备值是 **增量 $225**（$175.968 × 1.25 + $5 后向上取整）。这些余量是工程配置选择；固定顺序小样本不足以推断覆盖概率，任何固定金额都不能证明完整分母一定完成。", "",
          "## ChemIQ10 U/F 的准备", "",
          f"无 ChemIQ 实测费用样本，所以不把 0 个观测写成费用为 0。仅借同为 180 秒 pilot 的 CMT U/F 作保守代理：20 个 task run 的均值代理 ${chemiq['proxyPilotMeanUsd']:.3f}、全部取已观察 max ${chemiq['proxyAllTasksAtObservedArmMaxUsd']:.3f}、均值且无缓存 ${chemiq['proxyNoCacheMeanUsd']:.3f}。它不证明 ChemIQ 的真实费用或成绩。建议先准备 **增量 $5**，保留 10 题 U/F 全部预定索引及原始费用账。", "",
          "## 在途 GPQA 与累计费用保护", ""]
for active in in_flight:
    lines.append(f"`{active['run']}` 在途：summary 记录 {active['recordedTaskRuns']}/{active['plannedTaskRuns']} 个 task run，ledger 观察 {active['receiptCallsObserved']} 个请求、其中 {active['closedReceiptCallsObserved']} 个已闭合；已记上界 ${active['recordedUsageUpperBoundUsd']:.6f}，预留 ${active['reservedUpperBoundUsd']:.6f}，pending {active['pendingCount']}，本次累计 guard ${active['capUsd']}。ledger 与 summary 是分别读取的动态快照，不是同一原子事务，不能由这些数生成最终成绩；后续未发/未回请求不在当前费用中。")
lines += ["", f"已完成其它付费 pilot 合计 ${closed_paid:.9f}；加上当前在途已记/预留快照约 ${current_held:.6f}。下一波 guard 的含义是**所有既有 campaign 费用 + 本波新费用**，不能把 $60 当累计 guard 后忽略历史支出。", "",
          "GPQA 全量闭合后令 B 为实际所有历史账本总额：ChemIQ pilot 的累计 cap 至少按 B+$5 准备；随后 combined full 按实际 B_after+$60 准备。若现 full 总累计仍在其 $15 guard 内，普通准备值可取 **累计 $20（ChemIQ）→$80（combined）**；缓存失效压力配置为 **累计 $245，操作上可取 $250**。**$15 是 root 自设保护，不是用户给定上限**；提高 guard 为完整分母留空间，不表示自动把金额花完。若 guard 真耗尽，要保留费用/未完成记录并按基础设施无效处理，不能把未运行题补成 0 分或选择性重试。", "",
          "## 单共享付费进程命令", "",
          "等待现 GPQA 收尾且 receipt/source 闭合，保持一条付费进程。4 worker 在一个进程内共享同一 proxy/费用预留队列/原子 paid-lock；不同基准按已冻结 taskSchedule 轮转。不要分三个并发付费 Bun 进程。", "",
          "```powershell", f"Set-Location -LiteralPath '{ROOT}'", "$env:NODE_PATH='"+str(ROOT / "app/node_modules").replace("\\", "/")+"'", "$env:OBJRUN_REPAIR_WORKERS='4'", "$env:OBJRUN_REPAIR_ARMS='U,F'", "$env:OBJRUN_REPAIR_TASK_COUNT='10'", "$env:OBJRUN_REPAIR_BUDGET_USD='20'", "bun --env-file=.env scripts/repair-2026-10-08/campaign-next.ts pilot 'chemiq'", "", "# 等上一个 paid campaign 完全闭合；full 不能遗留 pilot override", "Remove-Item Env:OBJRUN_REPAIR_TASK_COUNT -ErrorAction SilentlyContinue", "$env:OBJRUN_REPAIR_BUDGET_USD='80'", "bun --env-file=.env scripts/repair-2026-10-08/campaign-next.ts full 'chembench,aime,cmt'", "```", "",
          "PowerShell 的 combined 参数须保留引号 **`'chembench,aime,cmt'`**。上述 $20/$80 依赖已有成本仍在当前 $15 guard 内；实际启动前以闭合 ledger 重算 B，若采用缓存失效压力情景再显式配置 $250。评分站须健康，ChemIQ startup/shutdown provenance audit 会核实实际评分环境。默认优先 4 worker，资源不足时入口在任何生成前记录降级。", "",
          "## 原始来源与重算", "",
          "预测支持仅固定以下三个完成 pilot，避免在途 GPQA 的已完成前缀或后续新样本静默改变当前外推基础：", ""]
for cohort in cohorts:
    lines.append(f"- `{cohort['run']}`：{cohort['taskRuns']} task run、{cohort['calls']} 请求、${cohort['costUsd']:.9f}。")
lines += ["", "逐文件 SHA、原始 task index、费用算术差异与完整分布见同目录 `next-wave-cost-review.json`。已核对所有输入账本的逐请求金额和 ledger 汇总（误差 <1e-9 USD），各完成 pilot task 的 apiCalls 与 canonical ledger 一致；未读/执行额外 CMT parser 或进行答题诊断。", "",
          "```powershell", "python -X utf8 scripts/repair-2026-10-08/review-next-wave-costs.py", "```", ""]
(OUT / "next-wave-cost-review.md").write_text("\n".join(lines), encoding="utf-8")
print(json.dumps({"groups": len(report["groups"]), "closedPilotTaskRuns": len(tasks), "closedPilotCalls": len(per_call),
                  "closedPaidUsd": closed_paid, "combined": combined, "chemiq": chemiq, "budget": budget,
                  "inFlight": in_flight, "arithmeticValid": all(audit["validCostArithmetic"] for audit in AUDIT)}, indent=2))
