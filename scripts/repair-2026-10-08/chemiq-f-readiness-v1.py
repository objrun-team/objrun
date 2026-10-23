"""Read stored ChemIQ metadata and freeze a prospective F-only review scope.

No imports of experiment/grader modules, SQL, sockets, subprocesses or models.
Only a new F documentation leaf is written. Answers/references are not exported.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/repair-2026-10-08"
BOOK_SHA = "4b11ba7dbcef8f075941c2e5337d687fa94d28837fc93e87a4eed1673a99646f"
PILOT = "repair-2026-10-08T10-25-57-408Z"


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def pin(path):
    path = Path(path)
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def prompt(row):
    # Data-only replay of scientific-journal-plan.ts scientificPrompt(chemiq,row).
    text = str(row.get("prompt", row.get("problem", row.get("question", ""))))
    answer_format = row.get("answer_format", "short")
    return (
        text + "\n\n" + f"Use the requested {answer_format} answer format. "
        "The final submitted answer must be a single line of at most 200 characters.\n"
        "Solve the task and submit your completed answer using submit. "
        "Search and filesystem tools are unavailable."
    )


def save_new(path, value, raw=False):
    data = value if raw else (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == data
    return pin(path)


def scaled(value, multiplier):
    return str(Decimal(str(value)) * multiplier)


def main(output):
    output = Path(os.path.abspath(output))
    assert output.parent == DOC and output.name.startswith("chemiq-f-formal-readiness-")
    assert not output.exists(), "Do not overwrite a prior readiness record"
    book_path = ROOT / ".phase1-data/chemiq/vendor/ChemIQ/questions/chemiq.jsonl"
    source = ROOT / ".phase1-data/chemiq/source.json"
    nonopsin_path = DOC / "legacy-chemiq-616-nonopsin-controls-raw-length.json"
    iupac_path = DOC / "legacy-chemiq-200-iupac-controls-raw-length.json"
    coverage_path = DOC / "legacy-chemiq-control-coverage.json"
    provenance_path = DOC / "chemiq-nextwave-grader-provenance.json"
    cost_path = DOC / "chemiq-full-cost-readiness-corrected.json"
    legacy_path = ROOT.parent / "notes/audit-2026-10-08/legacy-data-evidence.json"
    pilot_root = DOC / "campaigns" / PILOT
    initial_paths = [
        Path(__file__), book_path, source, nonopsin_path, iupac_path, coverage_path,
        provenance_path, cost_path, legacy_path,
        ROOT.parent / "notes/audit-2026-10-08/audit_legacy_data.py",
        ROOT / "runs/chemiq-f-0731/scorecard.json",
        DOC / "legacy-regrade-chemiq.json", DOC / "legacy-regrade-chemiq-local-opsin.json",
        DOC / "legacy-regrade-summary.json", DOC / "chemiq-scalability-readiness.json",
        DOC / "deepseek-cny-price-readonly.json",
        ROOT / "examples/benchmark/chemiq/objective.ts",
        ROOT / "scripts/repair-2026-10-08/scientific-journal-plan.ts",
        ROOT / "scripts/repair-2026-10-08/scientific-journal-campaign.ts",
        ROOT / "scripts/repair-2026-10-08/campaign-journal.ts",
        ROOT / "scripts/repair-2026-10-08/cny-cash-shadow-v2.ts",
        ROOT / "scripts/repair-2026-10-08/paid-resource-proof-v2.ts",
        pilot_root / "manifest.json", pilot_root / "summary.json", pilot_root / "api-ledger.json",
        pilot_root / "chemiq-public-tasks.json", pilot_root / "independent-deferred-closing-audit.json",
    ]
    provenance = read(provenance_path)
    initial_paths += [ROOT / item["relative_path"] for item in provenance["public_source_files"]]
    initial_paths.append(Path(provenance["public_archive"]["path"]))
    paths = list(dict.fromkeys(initial_paths))
    before = [pin(path) for path in paths]
    by_path = {item["path"]: item for item in before}
    assert pin(book_path)["sha256"] == BOOK_SHA
    for item in provenance["public_source_files"]:
        actual = by_path[str(ROOT / item["relative_path"]).replace("\\", "/")]
        assert (actual["bytes"], actual["sha256"]) == (item["bytes"], item["sha256"])

    # Discard every private field before computing prompts, strata or schedules.
    rows = []
    for index, line in enumerate(book_path.read_text(encoding="utf-8-sig").splitlines()):
        if not line.strip():
            continue
        question = json.loads(line)
        public = {key: question[key] for key in ("uuid", "question_category", "sub_category", "answer_format", "prompt") if key in question}
        official_id = "chemiq-" + question["uuid"]
        public["id"] = official_id
        rows.append({"officialIndex": index, "officialId": official_id, "publicRow": public,
                     "category": question["question_category"], "subCategory": question["sub_category"],
                     "method": question["verification_method"], "promptSha256": digest(prompt(public).encode())})
    del question
    assert len(rows) == 816 and len({item["officialId"] for item in rows}) == 816
    by_id = {item["officialId"]: item for item in rows}
    categories = Counter(item["category"] for item in rows)
    methods = Counter(item["method"] for item in rows)
    strata = Counter((item["category"], item["subCategory"], item["method"]) for item in rows)
    assert len(categories) == 8 and len(methods) == 5 and len(strata) == 14
    public_tasks = [{"row": item["publicRow"], "officialId": item["officialId"], "promptSha256": item["promptSha256"]} for item in rows]
    # public_tasks is fingerprinted, not written: it contains no GT but is lengthy.
    public_digest = digest(compact(public_tasks))

    nonopsin = read(nonopsin_path)
    iupac = read(iupac_path)
    coverage = read(coverage_path)
    control_rows = nonopsin["records"] + iupac["records"]
    controls = {item["task"]: item for item in control_rows}
    assert len(controls) == 816 and set(controls) == set(by_id)
    positive = {task for task, record in controls.items() if record["positive_passed"] is True}
    missing = {item["task"] for item in coverage["iupac_missing_control_records"]}
    assert len(positive) == 782 and set(by_id) - positive == missing and len(missing) == 34
    assert all(item["wrong_value_rejected"] for item in nonopsin["records"])
    assert all(item["wrong_structure_rejected"] for item in iupac["records"])
    assert all(item["wrong_format_rejected"] for item in control_rows)
    stand_sha = pin(ROOT / "examples/benchmark/chemiq/stand.py")["sha256"]
    assert nonopsin["adapter_sha256"] == iupac["adapter_sha256"] == stand_sha
    assert nonopsin["source_data_sha256"] == iupac["source_data_sha256"] == BOOK_SHA
    assert nonopsin["profile"] == iupac["profile"] == provenance["profile"]

    selected = {}
    seen = set()
    for item in rows:
        key = (item["category"], item["subCategory"], item["method"])
        if key not in seen:
            seen.add(key)
            selected[item["officialId"]] = ["First official-order task in its category/subcategory/method stratum"]
    mapping = {item["task"]: item for item in coverage["official_parsed_profile"]["mapping_gap_records"]}
    for subcategory in ("semi-canonical", "random"):
        boundary = next(item for item in rows if item["officialId"] in mapping
                        and item["subCategory"] == subcategory and mapping[item["officialId"]]["n_atoms"] == 25)
        selected.setdefault(boundary["officialId"], []).append("First official-order 25-atom mapping boundary; compact raw181/parser230")
    pilot_proposal = []
    for item in rows:
        if item["officialId"] in selected:
            pilot_proposal.append({key: item[key] for key in ("officialIndex", "officialId", "category", "subCategory", "method", "promptSha256")} |
                                  {"reasons": selected[item["officialId"]], "storedPositiveControlPassed": item["officialId"] in positive})
    assert len(pilot_proposal) == 16 and all(item["storedPositiveControlPassed"] for item in pilot_proposal)
    assert len({(item["category"], item["subCategory"], item["method"]) for item in pilot_proposal}) == 14
    missing_rows = [{key: item[key] for key in ("officialIndex", "officialId", "category", "subCategory", "method")} for item in rows if item["officialId"] in missing]
    optional = [next(item for item in missing_rows if item["subCategory"] == subcategory)
                for subcategory in ("zinc_random", "zinc_canonical")]

    pilot_manifest = read(pilot_root / "manifest.json")
    original_pilot_rows = read(pilot_root / "chemiq-public-tasks.json")
    assert len(original_pilot_rows) == 10
    assert all(item["promptSha256"] == by_id[item["officialId"]]["promptSha256"] for item in original_pilot_rows)
    assert all(by_id[item["officialId"]]["category"] == "nmr_elucidation" and by_id[item["officialId"]]["subCategory"] == "zinc_2d" for item in original_pilot_rows)
    cost = read(cost_path)
    assert cost["catalog"]["denominator"] == 816 and cost["pilot"]["run"] == PILOT
    fee_arm = cost["pilot"]["byArm"]["F"]
    prices = read(DOC / "deepseek-cny-price-readonly.json")
    assert prices["currency"] == "CNY" and prices["model"] == "deepseek-flash"
    assert prices["peak"] == {"uncachedInput": 2, "cachedInput": .04, "output": 8}
    prompt_tokens = int(fee_arm["promptTokens"]["total"])
    cached_tokens = int(fee_arm["cachedTokens"]["total"])
    output_tokens = int(fee_arm["outputTokens"]["total"])
    peak_total = (Decimal(prompt_tokens-cached_tokens)*2 + Decimal(cached_tokens)*Decimal('.04') + Decimal(output_tokens)*8)/Decimal(1000000)
    peak_no_cache_total = (Decimal(prompt_tokens)*2 + Decimal(output_tokens)*8)/Decimal(1000000)
    scenarios = []
    for count in (16, 816):
        for seconds, ratio in ((180, Decimal(1)), (600, Decimal(10)/Decimal(3)), (900, Decimal(5))):
            multiplier = Decimal(count)/10*ratio
            scenarios.append({"FTaskRuns": count, "scenarioSolveSeconds": seconds, "shape": "Observed F180 token/call/byte shape" if ratio == 1 else f"{seconds}/180 uniform pressure multiplier",
                              "cachedUsdPeakRateScenario": scaled(fee_arm["costUsd"]["total"], multiplier),
                              "noCacheUsdPeakRateScenario": scaled(fee_arm["noCacheUsd"]["total"], multiplier),
                              "cachedCnyAllPeakTokenScenario": str(peak_total*multiplier),
                              "noCacheCnyAllPeakTokenScenario": str(peak_no_cache_total*multiplier),
                              "callsScenario": scaled(fee_arm["calls"]["total"], multiplier),
                              "rawGzipBytesScenario": scaled(fee_arm["wireBytes"]["total"], multiplier),
                              "taskJsonBytesScenario": scaled(fee_arm["taskBytes"]["total"], multiplier),
                              "solveAndSettlementSecondsFourWorkersScenario": scaled(fee_arm["seconds"]["total"], multiplier/4),
                              "hardUpperBound": False, "invoice": False, "fxConversion": False})

    legacy_evidence = read(legacy_path)
    legacy = []
    for item in legacy_evidence["groups"]["ChemIQ"]:
        if "-f-" not in item["run"]:
            continue
        limits = item["declared_limits_K_T_search_readable"]
        assert len(limits) == 1 and len(limits[0]) == 4
        legacy.append({"run": item["run"], "tasks": item["tasks"], "storedPass": item["stored_pass"],
                       "states": item["states"], "sourceVersion": item["source_version"],
                       "finalResultsWithValidity": item["results_with_validity"], "checks": item["checks_c"],
                       "declaredMaxDeadSiblings": limits[0][0], "solveSeconds": limits[0][1],
                       "maxSearches": limits[0][2], "readable": limits[0][3],
                       "searchResponses": item["search_responses"], "searchHttp402": item["search_error_responses_http402"],
                       "blockedSubmissionReceipts": len(item["blocked_candidate_submissions"]),
                       "verifyWithoutNumericPass": len(item["verify_without_numeric_pass"]),
                       "scorecardSummary": item.get("scorecard_summary"),
                       "historicalActualModelCheckpointCertified": False, "newRepairedFormalScore": False})

    schedule = [{"index": index, "benchmark": "chemiq", "arm": "F", "replica": 0,
                 "officialId": item["officialId"], "promptSha256": item["promptSha256"]} for index, item in enumerate(rows)]
    schedule_sha = digest(compact(schedule))
    runtime = provenance["runtime_observed_imports_and_dependencies"]
    settings = {key: pilot_manifest[key] for key in ("model", "temperature", "seed", "reasoningEffort", "maxTokensPerRequest", "search", "allowedTools", "checksPerAttempt", "maxDeadSiblingsF", "maxBranchesF")}
    settings.update({"arms": ["F"], "replicasPerTask": 1, "solveSecondsOptions": [600, 900],
                     "selectedSolveSeconds": None,
                     "timeSelection": "Pending Root/user choice;900 matches old declared time,600 matches prior prospective plan. Neither reproduces all old protocol settings",
                     "proposedMaximumWorkers": 4, "workerCountMustPassFreshResourceGate": True,
                     "status": "Proposal only; recipe/entry/source and cash envelope not frozen or started"})
    report = {
        "protocol": "chemiq-f-formal-readiness-v1", "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "scope": "Stored-only metadata, public-field task projection, hashes and arithmetic; no model, network, Docker, scoring, SQL or production/environment changes",
        "validatedMetadata": True, "formalPaidReady": False, "newModelCalls": 0,
        "formalTarget": {"benchmark": "chemiq", "arm": "F", "denominator": 816, "taskRuns": 816,
                         "order": "Pinned original question-file order", "dataset": pin(book_path),
                         "officialSource": read(source), "fullTaskIdKeysetSha256": digest(compact([item["officialId"] for item in rows])),
                         "publicTaskDigest": public_digest, "taskScheduleSha256": schedule_sha,
                         "referencesExported": False, "oldCandidatesReused": False, "dropMissing34": False},
        "categoryCounts": dict(categories), "methodCounts": dict(methods),
        "strata": [{"category": a, "subCategory": b, "method": c, "count": n} for (a,b,c),n in strata.items()],
        "grader": {"profile": provenance["profile"], "standSha256": stand_sha,
                   "sameSourceAsStoredControls": True, "imageIdObservedHistorically": cost["catalog"]["storedImageId"],
                   "pythonObservedHistorically": runtime["python_version"],
                   "versions": {item["name"]: item["version"] for item in runtime["distributions"] if item["name"].lower() in ("rdkit", "numpy", "requests")},
                   "javaObservedHistorically": provenance["host_bridge"]["java_version"],
                   "freshRuntimeHealthOrNamespaceCheckPerformed": False,
                   "publicGraderSourceArchive": provenance["public_archive"], "archiveContainsEntireRuntime": False,
                   "officialParsedLengthIsRestored": False, "oldRestEquivalenceCertified": False,
                   "meaning": "Explicit revised localOPSIN2.8/raw-input-length deterministic profile, not an unchanged official-parsed or legacy REST score"},
        "controls": {"positivePassed": 782, "nonopsinPositivePassed": 616, "iupacPositivePassed": 166,
                     "wrongValueOrStructureRejected": 816, "wrongFormatRejected": 816,
                     "fullPositiveCertification": False, "mappingParsedLengthGapsRepaired": 30,
                     "missingPositiveReferenceNames": 34, "missingBySubcategory": dict(Counter(item["subCategory"] for item in missing_rows)),
                     "missingPositiveTaskRecords": missing_rows,
                     "meaning": "Absent positive reference controls are unavailable evidence, not a known model error or ungradable task; all 34 stay in 816"},
        "historicalF": legacy,
        "oldCandidateRegrade": {"limitedRiskTaskInstances": 6, "newGeneration": False,
                                "purpose": "Post-hoc diagnostic cannot restore the search path affected by old grading/budget bugs",
                                "historicalFinalGradingCandidateDigestAvailable": False},
        "actualPilot": {"run": PILOT, "tasksPerArm": 10, "FPass": 3, "UPass": 3,
                        "categories": ["nmr_elucidation/zinc_2d"], "solveSeconds": 180,
                        "settings": {key: pilot_manifest[key] for key in settings if key in pilot_manifest},
                        "FObserved": fee_arm, "totalRealCalls": 1243, "totalUsdPeakEstimate": "1.367459808",
                        "FRealCalls": 1223, "originalCompleted": cost["pilot"]["originalCompleted"],
                        "originalFatal": cost["pilot"]["originalFatal"], "laterClose": cost["pilot"]["laterClose"],
                        "representativeOfFull816": False},
        "prospectiveSettings": settings,
        "minimumRepresentativeFPilot": {"FTaskRuns": 16, "subsetOfFormalDenominator": True,
                                       "paidRunStarted": False, "selectionUsesModelOutcomes": False,
                                       "selection": "First task in all14 category/subcategory/method strata in official order, plus first25-atom mapping in each mapping subcategory; boundary metadata only",
                                       "covers": {"categories": 8, "strata": 14, "methods": 5, "mapping25AtomSubcategories": 2},
                                       "taskRecords": pilot_proposal,
                                       "queryAndTimeSettings": "Same finally selected600or900s/checks5/branches4/model/decoding/profile as the later formal run; time is not yet selected",
                                       "expectedPositiveControlsAvailable": True,
                                       "missing34AreCovered": False,
                                       "optionalTwoGapCasesAfterPositiveReferencesFixed": optional,
                                       "pilotIsFullScore": False,
                                       "futureFullInclusion": "Decide before generation whether pilot is separate or predeclared exact-source formal subset; never stitch changed protocols or select by outcomes"},
        "feeTimeByteScenarios": {"basis": "Ten nonrepresentative NMR F180 tasks; no new requests.600/180 and900/180 pressure multipliers are not measured scaling laws or bounds",
                                 "peakCnyRatesPerMillion": prices["peak"], "peakCnyFromOriginalFTokens": str(peak_total),
                                 "peakCnyNoCacheFromOriginalFTokens": str(peak_no_cache_total), "scenarios": scenarios,
                                 "excludes": ["New journal/cash/index/checkpoints", "SQLite and source archives", "grader queue files and private runtime", "task startup/closing pauses", "tail variance and new task types"],
                                 "meanVsMaximum": {"F180UsdMean": fee_arm["costUsd"]["mean"], "F180UsdMax": fee_arm["costUsd"]["maximum"], "F180NoCacheUsdMax": fee_arm["noCacheUsd"]["maximum"], "near180sDeadlineTasks": fee_arm["nearDeadlineTasks"]},
                                 "USDToCnyConversion": False, "invoiceRecovered": False, "freshBalanceRetrieved": False,
                                 "rechargeArrivalAssumed": False, "operatorGuardChosen": False},
        "requiredBeforeSmallPilot": [
            "Root reviews and freezes a separate ChemIQ F-only/subset entry+schedule+source. Existing frozen scientific plan emits U/F and its16 calibration rule differs; do not mutate/relabel frozen81 or use it asF-only.",
            "Fresh private grader health/profile/source/image/library/JAR/queue evidence must match explicit local2.8/raw-input-length level0, with noREST fallback; old controls/provenance are historical.",
            "All16 proposed pilot task positive/negative/format control receipts must remain valid under the chosen source; retain uncertainty for34 rather than selecting them away.",
            "Use durable raw gzip+journal admissions before provider forward, CNY peak reservation, late-response drain, faithful unknown accounting and exact canonical owner; Root refreshes balance/priceTTL after actual recharge. Old4unknown8.39218CNY stays carried.",
            "Fresh RAM/disk gates and bounded worker memory/evidence growth; no migration/cleanup implicit in this readiness record.",
            "Export raw task traces/candidateSHA/model wire and servedmodel/token/cost, explicit verify counts, physical runtime grading and final independent grading separately; private GT/control names/credentials remain excluded.",
            "After stored candidate sealing/deadline enforcement, independent official grading and true owned PID/port/cash/source close; partial/invalid scores never become model0 or full scores."
        ],
        "requiredBeforeRepairedFormalFullF": [
            "Complete valid private positive name controls for all34 missing IUPAC IDs, or obtain explicit approval for a clearly provisional profile; current evidence cannot certify full repaired grader readiness.",
            "Retain all816 exact IDs even if answers fail or tasks are unavailable. Report attempted/valid/invalid/missing keysets separately; no drop, result-based rerun or previous candidate substitution.",
            "Full816 needs a tested bounded append/stream/export plan; legacy wholeJSON ledger rewrites amplify IO, current cash.count loops allhistory and128MiB singlePin/256MiB cashmetadata gates may block huge runs.",
            "Choose a complete selected600or900s F cash/storage/time envelope from representative pilot actual receipts. Legacy80USD was an operatorguard, not userlimit; no fresh recharge/balance is certified by this review.",
            "User/Root confirmation limits for pilot/independent handoff remain; this record freezes a proposed task scope, not a launch authorization or new score."
        ],
        "sourceAndInputPins": before,
        "limitations": [
            "Hash/data replay certifies metadata only; no live private grader, Java queue, namespace, cash lock or API probe was made.",
            "Historical model/source/checkpoint/wire/candidate-final-input/completevalidity is not certified by stored scorecards. 0731scorecard hides4claimed relative toDB audit; preserve both originals.",
            "Checks5 bounds explicit checking under core rules, not all physical G HTTP calls or identical compute to U. Count parsed/correct graph requests, cachedjudges, runtimeauto and final separately.",
            "Seed42/temperature0 describe requested decoding, not provider determinism or exact historical0731 checkpoint equivalence.",
            "14strata plus mapping boundaries covers method paths, not all difficulty/length/cost/queue tails, and it does not repair or exercise every missingpositive case.",
            "Public grader code archive is not a complete OS/Python/Java runtime bundle. Fresh complete environment capture remains required."
        ]
    }
    after = [pin(path) for path in paths]
    assert after == before, "Stored input/source changed during review"
    report["originalInputsBeforeAfterMatch"] = True
    report["originalsModified"] = False
    output.mkdir()
    scope = {"protocol": "chemiq-f-prospective-fixed-scope-v1", "executed": False, "formalScore": False,
             "sourceDatasetPin": pin(book_path), "publicTaskDigest": public_digest,
             "taskScheduleSha256": schedule_sha, "taskSchedule": schedule}
    scope_pin = save_new(output / "task-scope.json", scope)
    report["formalTarget"]["scopeArtifact"] = scope_pin
    report_pin = save_new(output / "readiness.json", report)
    table = []
    for item in report["strata"]:
        table.append(f"| {item['category']} | {item['subCategory']} | {item['method']} | {item['count']} |")
    pilot_table = [f"| {item['officialIndex']} | {item['officialId']} | {item['category']}/{item['subCategory']} |" for item in pilot_proposal]
    summary = f"""ChemIQ F 正式重跑的固定分母是 **816 题、816 次 F**。本文件只准备范围；没有生成模型答案、评分或启动正式实验。目前 `formalPaidReady=false`。

| 数据/计划 | 分母与实际状态 | 时间与显式检查 | 评分及结论 |
|---|---|---|---|
| 旧 `chemiq-f-0731` | 816；存680通过，DB仍4claimed，scorecard却计0running | 900秒，checks3，K8，search3 | 旧source未验证、finalvalidity0；不认证修复成绩 |
| 旧 `chemiq-f-c5kinf-0929` | 816；存633通过，仍6claimed；303次search全HTTP402 | 900秒，checks5，K100000，search3 | 不替换成新正式成绩 |
| 10月8日真实试跑 | F10，3通过；全部NMR/zinc_2d，U另10 | 180秒，checks5，branch4，无search | 固定localOPSIN2.8/raw-input-length；原shutdown超时保留，laterclosing独立通过 |
| 本次正式F提案 | 原题序全部816，F一次/题；未执行 | **600/900秒待选择**，checks5，branch4，K100000，无search | 新模型deepseek-flash/8192/temp0/seed42/reasoningnone；独立新协议 |

原F实际900秒；600秒来自此前新方案。当前两者都是待确认提案，Root基于“修复后正式”的时间可比性倾向900秒，但此件不替用户选定时限。即使沿900秒，模型、搜索、预算与评分协议仍有差异。题库 commit `63826f64990802e87f1b11b9192606a20838d522`，803,509字节，SHA `{BOOK_SHA}`。全部F范围提案及promptSHA见 [task-scope.json](task-scope.json)，scheduleSHA `{schedule_sha}`。仅公共字段参与prompt计算，参考答案没有写入清单；这不是完整执行协议的正式冻结。

| 类别 | 子类 | 判卷方法 | 题数 |
|---|---|---|---|
{chr(10).join(table)}

评分器明确采用本地 OPSIN2.8.0（JAR SHA `{provenance['profile']['opsin']['jar_sha256']}`）、官方parser/RDKit和原判等函数；不回退REST。原子映射只将200字长度限制放在交付原文，修复30题解析加空格后的误拒。它是独立修订协议，不能写成旧未知REST或完全未改官方parsed-length的等价成绩。历史观察环境为Python3.12.11、RDKit2024.9.6、NumPy1.26.4、requests2.34.2、Java1.8.0_341；必须重新核实际环境，而非仅引用旧记录。

同一stand源码的正控已通过 **782/816**（非OPSIN616、IUPAC166），错误值/结构与格式负控各816全拒绝。缺34个可验证的IUPAC正参考，random/canonical各17。JSON给出全部34准确ID。它们不是已知答错或不可判题，不减分母；正式“修复完成”认证应先补齐私有正确名称及其本地判等正控，否则只能明确标为暂定协议。

建议最小代表性F试跑 **16题**：按原题序每个14子类/判法取首题，再加semi-canonical/random各一题25原子映射（紧凑原文181字，解析后230字）。全部16已有正控；选择未使用模型成绩。它比原NMR单类试跑覆盖完整，但不认证全部816或34缺参考。补参考后可再加JSON预定的两道缺口题作为诊断，不按模型成败换题。

| 原题索引(0起) | 固定taskID | 类别/子类 |
|---|---|---|
{chr(10).join(pilot_table)}

试跑与后续正式F应采用同一选定600/900秒、模型、判卷与明确预算；时限未选择，未执行。既有冻结scientific入口仍发U/F，其16题calibration选择规则也不同。应新增独立F-only入口/审核/sourcefreeze，不改原81源。试跑是否作为正式预定子集，必须生成前确定；修改协议后的试跑不能拼接成正式分数。显式verify5与runtime自动判卷/最终独立判卷分别记账，不能说所有物理G调用只有5次或U/F等预算因果对比。

费用和空间只能做场景：原F10共1223请求，USD峰价估计1.255906728；以同NMR180秒形状外推F816约USD102.48，600/180压力约USD341.61，900/180压力约USD512.41。独立按实际token与CNY峰价计算分别约CNY683.21/2277.38/3416.07；完全无缓存时约CNY4867.57/16225.23/24337.84。这些是非代表样本场景，不是发票、汇率转换、收费上界或余额。16题相应缓存峰价场景约CNY13.40/44.65/66.98，仍不能据此自动发请求。用户表示会充值不代表已到账；Root需临近启动实际刷新余额、价格TTL、独立现金envelope，并保留原4未知8.39218CNY责任。

旧全JSON逐请求重写不能直接扩大到完整816；现有append journal可作为新入口基础，但cash.count全历史遍历和128MiB单Pin/256MiB现金元数据限制仍须考虑。实际memory/disk、OPSIN共享队列延迟、任务证据增量均需16题先测；本文件不提供硬时间或资源保证。密钥、私有GT/正控名称不进模型/公开包；原始请求响应、候选/trace摘要、真实servedmodel/token/费用、各类评分及清理证据必须保全。无效评分保持无效，不能当模型0分。

全部当前输入及源码在本次读取前后逐SHA一致。完整 [readiness.json](readiness.json)：{report_pin['bytes']} 字节，SHA `{report_pin['sha256']}`。现有论文、旧分数、原包、冻结执行源码均未改。
"""
    markdown_pin = save_new(output / "readiness.md", summary.encode(), raw=True)
    print(json.dumps({"report": report_pin, "scope": scope_pin, "markdown": markdown_pin,
                      "source": pin(Path(__file__)), "metadataValidated": True,
                      "formalPaidReady": False, "modelCalls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    main(parser.parse_args().output_dir)
