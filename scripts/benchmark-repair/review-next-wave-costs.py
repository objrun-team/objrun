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


lines = ["# Next-wave cost review and budget preparation", "",
         "Completed scientific pilots have been reconciled by task/request: **216 task runs, 859 API calls**, total cost upper bound **$1.262360088**. CMT F accounts for most spending. ChemIQ has no paid sample in this round; AIME has only one task, whose cost cannot guarantee the full 60 tasks. The full GPQA run is currently in flight; the following records only progress/cost snapshots, with no final results or selective-retry advice.", "",
         f"Review time (UTC): `{report['observedAt']}`. This analysis calls no LLM, grader, or CMT parser and changes no frozen execution files.", "",
         "## Original sample support", "",
         "Costs use frozen accounting rates: uncached input $0.30/M, cached input $0.006/M, output $1.20/M. These are cost upper bounds for existing experimental records, not independently verified provider bills or new live price quotes. Input includes cached tokens; cache is a subset of input and must not be counted twice.", "",
         "| Benchmark/arm | Task runs / distinct tasks | Total calls | Calls per task mean / max | Total input | Total output | Total cache hits | Total USD | USD per task mean | USD per task max |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
for group in report["groups"]:
    total = group["totals"]
    lines.append(f"| {group['benchmark']} / {group['arm']} | {group['taskRuns']} / {group['uniqueOfficialTasks']} | {total['calls']} | {mean_max(group,'calls')} | {total['inputTokens']:,} | {total['outputTokens']:,} | {total['cacheTokens']:,} | {total['usdUpperBound']:.6f} | {group['perTask']['usdUpperBound']['mean']:.6f} | {group['perTask']['usdUpperBound']['max']:.6f} |")
lines += ["", "The 50 R task runs are 5 replicas of each of the same 10 tasks, not 50 distinct tasks. GPQA U/F combines three completed pilots: each arm has 12 task runs but only 10 distinct tasks. This duplication describes incurred costs only and is not used to extrapolate other benchmarks in the next wave. CMT/ChemBench support is the first 10 tasks in fixed order, not a random sample.", "",
          "Per-task token distributions follow; JSON also includes per-request/per-task min, mean, median, nearest-rank p90, max, and cost metadata for each original task index.", "",
          "| Benchmark/arm | Input mean / max | Output mean / max | Cache hits mean / max |",
          "|---|---:|---:|---:|"]
for group in report["groups"]:
    lines.append(f"| {group['benchmark']} / {group['arm']} | {mean_max(group,'inputTokens')} | {mean_max(group,'outputTokens')} | {mean_max(group,'cacheTokens')} |")
lines += ["", f"CMT F: 10 task runs, {cmt_f['totals']['calls']} calls total, mean {cmt_f['perTask']['calls']['mean']:.1f}, max {cmt_f['perTask']['calls']['max']}; cost mean ${cmt_f['perTask']['usdUpperBound']['mean']:.6f}, max ${cmt_f['perTask']['usdUpperBound']['max']:.6f}. Cached share of input: {cmt_f['cacheShareOfInput']:.2%}; recorded total duration reached/exceeded 180 seconds for {cmt_f['nearOrPastSolveDeadline']} tasks (including cleanup time). The full CMT F protocol allows 1800 seconds; this cost distribution is not an upper bound for the full time limit.", "",
          "## Next-wave full denominators: ChemBench500, AIME60, CMT50, U/F", "",
          "Total: 610 tasks, **1220 task runs**. The table distinguishes empirical extrapolation from conservative sensitivity scenarios; all amounts are incremental, excluding existing spending.", "",
          "| Benchmark | U/F task runs | Supporting tasks per arm | Pilot-mean extrapolation USD | All tasks at observed arm maximum USD | Mean without caching USD | F time-limit sensitivity USD | F time limit + no caching USD |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
for projection in projections:
    lines.append(f"| {projection['benchmark']} | {projection['plannedTaskRuns']} | {projection['sampleTasksPerArm']['U']} / {projection['sampleTasksPerArm']['F']} | {projection['empiricalPilotMeanUsd']:.3f} | {projection['allTasksAtObservedArmMaxUsd']:.3f} | {projection['noCachePilotMeanUsd']:.3f} | {projection['FDeadlineSensitivityMeanUsd']:.3f} | {projection['FDeadlineAndNoCacheSensitivityMeanUsd']:.3f} |")
lines.append(f"| Total | 1220 | — | {combined['empiricalPilotMeanUsd']:.3f} | {combined['allTasksAtObservedArmMaxUsd']:.3f} | {combined['noCachePilotMeanUsd']:.3f} | {combined['FDeadlineSensitivityMeanUsd']:.3f} | {combined['FDeadlineAndNoCacheSensitivityMeanUsd']:.3f} |")
lines += ["", "F time-limit sensitivity scales only F pilot mean costs by declared duration ratios: ChemBench/AIME 180→600 seconds, factor 10/3; CMT 180→1800 seconds, factor 10. U retains the empirical mean. This is a budget stress scenario, **not** an empirical model of costs growing linearly with time or a confidence interval. The no-cache scenario reprices all observed input at $0.30/M. Harder full-set tasks, changing actual cache behavior, the effect of 4 workers on latency/caching, and branch retries may invalidate any of these scenarios.", "",
          "For the full combined wave, reserve a recommended **incremental $60**: cache-preserving F time-limit sensitivity $40.118 × 1.25, plus a $5 engineering allowance for AIME single-task/selection uncertainty, rounded up to $5. A more conservative preparation value covering substantial cache failure is **incremental $225** ($175.968 × 1.25 + $5, rounded up). These margins are engineering configuration choices; a small fixed-order sample cannot establish coverage probability, and no fixed amount proves that the full denominator will finish.", "",
          "## Preparing ChemIQ10 U/F", "",
          f"There are no observed ChemIQ cost samples, so zero observations are not reported as zero cost. CMT U/F, also a 180-second pilot, is used only as a conservative proxy: for 20 task runs, mean proxy ${chemiq['proxyPilotMeanUsd']:.3f}, all at observed max ${chemiq['proxyAllTasksAtObservedArmMaxUsd']:.3f}, mean without caching ${chemiq['proxyNoCacheMeanUsd']:.3f}. This does not establish actual ChemIQ costs or results. Prepare a recommended **incremental $5** first, retaining all prespecified indices for 10 U/F tasks and the original cost ledger.", "",
          "## In-flight GPQA and cumulative cost protection", ""]
for active in in_flight:
    lines.append(f"`{active['run']}` is in flight: summary records {active['recordedTaskRuns']}/{active['plannedTaskRuns']} task runs; ledger observes {active['receiptCallsObserved']} requests, including {active['closedReceiptCallsObserved']} closed. Recorded upper bound ${active['recordedUsageUpperBoundUsd']:.6f}, reserved ${active['reservedUpperBoundUsd']:.6f}, pending {active['pendingCount']}, current cumulative guard ${active['capUsd']}. Ledger and summary are separately read dynamic snapshots, not one atomic transaction. These numbers cannot produce final results; subsequent unsent/unreturned requests are absent from current costs.")
lines += ["", f"Other completed paid pilots total ${closed_paid:.9f}; adding the current in-flight recorded/reserved snapshot gives about ${current_held:.6f}. The next-wave guard means **all existing campaign costs + new costs for this wave**; do not use $60 as the cumulative guard while ignoring historical spending.", "",
          "After full GPQA closes, let B be the actual total across all historical ledgers: prepare the ChemIQ pilot cumulative cap at least as B+$5, then combined full as actual B_after+$60. If the current full run stays within its $15 cumulative guard, ordinary preparation values can be **cumulative $20 (ChemIQ) → $80 (combined)**; cache-failure stress configuration is **cumulative $245, operationally $250**. **$15 is a root-imposed guard, not a user-specified limit**. Raising the guard leaves room for the full denominator; it does not mean automatically spending the amount. If the guard is actually exhausted, retain cost/incomplete records and classify the outcome as infrastructure-invalid; do not fill unrun tasks with 0 scores or selectively retry.", "",
          "## Single shared paid-process commands", "",
          "Wait for current GPQA cleanup and receipt/source closure; maintain one paid process. Its 4 workers share one proxy/cost-reservation queue/atomic paid-lock, with benchmarks rotated by the frozen taskSchedule. Do not split this into three concurrent paid Bun processes.", "",
          "```powershell", f"Set-Location -LiteralPath '{ROOT}'", "$env:NODE_PATH='"+str(ROOT / "app/node_modules").replace("\\", "/")+"'", "$env:OBJRUN_REPAIR_WORKERS='4'", "$env:OBJRUN_REPAIR_ARMS='U,F'", "$env:OBJRUN_REPAIR_TASK_COUNT='10'", "$env:OBJRUN_REPAIR_BUDGET_USD='20'", "bun --env-file=.env scripts/benchmark-repair/campaign-next.ts pilot 'chemiq'", "", "# Wait for the previous paid campaign to close completely; full must not retain a pilot override", "Remove-Item Env:OBJRUN_REPAIR_TASK_COUNT -ErrorAction SilentlyContinue", "$env:OBJRUN_REPAIR_BUDGET_USD='80'", "bun --env-file=.env scripts/benchmark-repair/campaign-next.ts full 'chembench,aime,cmt'", "```", "",
          "The PowerShell combined argument must retain its quotes: **`'chembench,aime,cmt'`**. The $20/$80 values above depend on existing costs remaining within the current $15 guard. Recompute B from closed ledgers before actual startup; explicitly configure $250 if using the cache-failure stress scenario. Grading stations must be healthy; the ChemIQ startup/shutdown provenance audit verifies the actual grading environment. Prefer 4 workers by default; if resources are insufficient, the entry point records degradation before any generation.", "",
          "## Original sources and recomputation", "",
          "Prediction support is fixed to the following three completed pilots, preventing a completed prefix of in-flight GPQA or subsequent new samples from silently changing the current extrapolation basis:", ""]
for cohort in cohorts:
    lines.append(f"- `{cohort['run']}`: {cohort['taskRuns']} task runs, {cohort['calls']} requests, ${cohort['costUsd']:.9f}.")
lines += ["", "See `next-wave-cost-review.json` in the same directory for per-file SHAs, original task indices, cost arithmetic differences, and complete distributions. Per-request amounts and ledger aggregates were verified for all input ledgers (error <1e-9 USD), and apiCalls for every completed pilot task match the canonical ledger. No additional CMT parser was read/executed, and no answer diagnostics were performed.", "",
          "```powershell", "python -X utf8 scripts/benchmark-repair/review-next-wave-costs.py", "```", ""]
(OUT / "next-wave-cost-review.md").write_text("\n".join(lines), encoding="utf-8")
print(json.dumps({"groups": len(report["groups"]), "closedPilotTaskRuns": len(tasks), "closedPilotCalls": len(per_call),
                  "closedPaidUsd": closed_paid, "combined": combined, "chemiq": chemiq, "budget": budget,
                  "inFlight": in_flight, "arithmeticValid": all(audit["validCostArithmetic"] for audit in AUDIT)}, indent=2))
