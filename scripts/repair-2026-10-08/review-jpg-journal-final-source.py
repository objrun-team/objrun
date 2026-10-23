"""Read only the fixed JPG review graph; create independent F reports with xb.

This is a source/evidence review, not a runner, provider client, or Docker probe.
It never imports or executes the reviewed runtime or reruns its controls.
"""
from __future__ import annotations

import ast
import datetime as dt
import difflib
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/repair-2026-10-08"
FINAL = DOCS / "jpg-journal-fsync-revision/owned-fsync-v3-final"
ARCHIVE = DOCS / "jpg-journal-fsync-revision/pre-owned-fsync-v3"
OUT_JSON = DOCS / "jpg-journal-independent-final-source-review.json"
OUT_MD = DOCS / "jpg-journal-independent-final-source-review.md"
EXPECTED_SOURCES = {
    "skb-jpg-journal-campaign.ts": (40505, "a03704a6eab65706e90a6bdf3e60f785e7930dcb24ec73fdccbe8d5cf72350cf"),
    "jpg-paid-resource-admission-v1.ts": (16915, "f815f002fc0413c09e8fc0bbf28c96af19d41e608c8967ce601d8dcf0dae75d7"),
    "jpg-journal-contract.ts": (8352, "b15a108e3d90b1626277368678e2593a6d8f2c883deb3a98a454f052912c301f"),
    "audit-jpg-journal-campaign.py": (38835, "cb33c62c6f5f912e2309832532add56ec36d8239248355f304d3e52e800d8857"),
}
EXPECTED_REVIEW = (26083, "9ae9539fbfafb4b277e8ac800532e1e77d8aca13c022349f87bd94107c582ed2")
EXPECTED_CHECKS = (3253, "bb6b4de8b31131eee5fc7b3e970aa327a8b4c380a98ff2bad0aa5426d606b451")
EXPECTED_ARCHIVE = (120505, "c25545d67f6dc6284b1817392c89ce1d5802d10f033cfb5910df38037eec8451")
EXPECTED_SCIENCE = (13933, "5d4a33edb1f8cb99bba1eb198bfbde7cf8d87fd0102e38aff11c5c5564b2bd33")


def require(ok, why):
    if not ok:
        raise AssertionError(why)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def actual_pin(path):
    path = Path(path).absolute()
    require(path.is_relative_to(ROOT) and path.drive.upper() == "F:", "review_pin_not_F_project")
    require(path.is_file() and not path.is_symlink(), "review_pin_not_regular")
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


def verify_pin(claim):
    actual = actual_pin(claim["path"])
    require(actual["bytes"] == claim["bytes"] and actual["sha256"] == claim["sha256"], "pin_mismatch:" + actual["path"])
    return actual


def fixed(path, pair):
    return verify_pin({"path": str(path), "bytes": pair[0], "sha256": pair[1]})


def read_json(path):
    return json.loads(Path(path).read_bytes())


def py_functions(text):
    return {node.name: ast.get_source_segment(text, node) for node in ast.parse(text).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def ts_owned_blocks(text):
    # These full exact substrings include admission, collection, and owner graph
    # inputs. No semantic execution or dynamic parsing of the runtime occurs.
    out = {}
    for key, start, end in [
        ("operation_receipt_collection", "      if(basename(path.path)==='operation-owner.json'){", "    demand(bridgeOwnerPin,'jpg_bridge_owned_receipt_missing');"),
        ("owned_scope", "    const ownedScope=", "    const physicalFeedback="),
    ]:
        a = text.index(start)
        b = text.index(end, a)
        out[key] = text[a:b]
    return out


def write_new(path, raw):
    require(path.is_relative_to(ROOT) and path.drive.upper() == "F:", "report_write_scope")
    with path.open("xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    require(path.read_bytes() == raw, "report_readback")
    return actual_pin(path)


def main():
    require(not OUT_JSON.exists() and not OUT_MD.exists(), "immutable_report_already_exists")
    review_pin = fixed(FINAL / "review.json", EXPECTED_REVIEW)
    checks_pin = fixed(FINAL / "checks.json", EXPECTED_CHECKS)
    archive_pin = fixed(ARCHIVE / "manifest.json", EXPECTED_ARCHIVE)
    review = read_json(review_pin["path"])
    checks = read_json(checks_pin["path"])
    archive = read_json(archive_pin["path"])
    sources = [fixed(ROOT / "scripts/repair-2026-10-08" / name, pair) for name, pair in EXPECTED_SOURCES.items()]
    require(review["newSources"] == sources and checks["sourcePins"] == sources, "owner_source_set_not_exact")
    require(review["formalPaidReady"] is False and review["readyTaskIds"] == [], "owner_overclaims_readiness")
    require(review["sourceTaskCount"] == 87 and review["supportedTaskIds"] == ["jpg-ocr-stat"] and review["unsupportedTaskCount"] == 86, "denominator_scope")

    execution = [verify_pin(p) for p in review["executedSourcePins"]]
    require(len(execution) == 80 and len({p["path"] for p in execution}) == 80, "execution_source_count")
    science_path = DOCS / "journal-preparations/repair-2026-10-08T18-27-31-018Z/source.json"
    science_pin = fixed(science_path, EXPECTED_SCIENCE)
    science = read_json(science_path)
    science_rows = science["files"] + science["repairFiles"]
    require(len(science_rows) == 81, "science_source_count")
    protected = [verify_pin({**p, "path": str(ROOT / p["path"])}) for p in science_rows]

    snapshots = [verify_pin(p) for p in review["sourceSnapshots"]]
    archived = []
    for row in archive["inventory"]:
        saved = verify_pin(row["saved"])
        require(Path(saved["path"]).is_relative_to(ARCHIVE), "archive_saved_path_scope")
        require(saved["bytes"] == row["original"]["bytes"] and saved["sha256"] == row["original"]["sha256"], "archive_copy_original_pin_mismatch")
        archived.append(saved)
    require(len(archived) == 184, "archive_inventory_count")
    previous_review_pin = verify_pin(review["previousReviewPin"])
    previous = read_json(previous_review_pin["path"])
    historical_control_pins = []
    for field in ["stdoutPin", "stderrPin"]:
        historical_control_pins.append(verify_pin(previous["controls"][field]))
    historical_control_pins += [verify_pin(p) for p in previous["controls"]["fixtureReceiptPins"]]

    expected_changed = {"flush_tree", "private_grade"}
    previous_py = (ARCHIVE / "scripts/repair-2026-10-08/audit-jpg-journal-campaign.py").read_text(encoding="utf-8")
    current_py = (ROOT / "scripts/repair-2026-10-08/audit-jpg-journal-campaign.py").read_text(encoding="utf-8")
    old_functions, new_functions = py_functions(previous_py), py_functions(current_py)
    changed = sorted(n for n in old_functions if n not in new_functions or old_functions[n] != new_functions[n])
    added = sorted(n for n in new_functions if n not in old_functions)
    require(set(changed) == expected_changed and added == ["create_owned_flush_fixture", "ordinary_owned_path"], "unexpected_python_semantic_delta")
    require(old_functions["owned_graph"] == new_functions["owned_graph"] and old_functions["owned_probe"] == new_functions["owned_probe"], "exact_owned_graph_changed")
    previous_ts = (ARCHIVE / "scripts/repair-2026-10-08/skb-jpg-journal-campaign.ts").read_text(encoding="utf-8")
    current_ts = (ROOT / "scripts/repair-2026-10-08/skb-jpg-journal-campaign.ts").read_text(encoding="utf-8")
    ts_blocks_before, ts_blocks_after = ts_owned_blocks(previous_ts), ts_owned_blocks(current_ts)
    require(ts_blocks_before == ts_blocks_after, "owned_receipt_or_scope_changed")
    diffs = {name: "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile="owned-v2/" + name, tofile="fsync-v3/" + name, n=2))
             for name, old, new in [("audit-jpg-journal-campaign.py", previous_py, current_py), ("skb-jpg-journal-campaign.ts", previous_ts, current_ts)]}
    static_checks = {
        "ts_registered_store_and_output_only_after_new_store_and_physical_checks": "mkdirSync(store,{recursive:false})" in current_ts and "demand(!existsSync(recipe.output),'jpg_new_metadata_output_only')" in current_ts and "ownedFlushRoots.add(resolve(store));ownedFlushRoots.add(resolve(output));" in current_ts,
        "ts_owned_roots_removed_in_finally": "ownedFlushRoots.delete(resolve(store));ownedFlushRoots.delete(resolve(output));" in current_ts,
        "ts_r_plus_and_unchanged_bytes_sha": "openSync(full,'r+')" in current_ts and "before.bytes===after.bytes&&before.sha256===after.sha256" in current_ts,
        "python_r_plus_b_identity_and_digest": "p.open('r+b')" in current_py and "(opened.st_ino,opened.st_dev,opened.st_size)==(before.st_ino,before.st_dev,before.st_size)" in current_py and "digest==file_sha(p)" in current_py,
        "python_private_grade_new_output_under_current_store": "output.parent==store" in current_py and "not output.exists()" in current_py and "_OWNED_FLUSH_OUTPUTS.add(output)" in current_py,
        "fixed_artifact_only_clean_grader_contract_preserved": old_functions["private_grade"].split("    receipt=", 1)[1] == new_functions["private_grade"].split("    receipt=", 1)[1],
        "private_configs_still_excluded": "item.name!=='config.yaml'" in current_ts and "if name=='config.yaml':continue" in current_py,
    }
    require(all(static_checks.values()), "static_delta_condition_failed")
    for name in ["jpg-paid-resource-admission-v1.ts", "jpg-journal-contract.ts"]:
        require((ARCHIVE / "scripts/repair-2026-10-08" / name).read_bytes() == (ROOT / "scripts/repair-2026-10-08" / name).read_bytes(), "unchanged_cash_or_contract_modified")

    require((checks["pass"], checks["fail"], checks["assertions"]) == (3, 0, 14), "control_counts")
    logs = [verify_pin(p) for run in checks["runs"] for p in [run["stdout"], run["stderr"]]]
    control_run = next(v for v in checks["runs"] if v["name"] == "control")
    require(control_run["status"] == 0 and control_run["error"] is None and control_run["signal"] is None, "control_child_not_closed_successfully")
    control_stderr = Path(control_run["stderr"]["path"]).read_text(encoding="utf-8")
    require("3 pass" in control_stderr and "0 fail" in control_stderr and "14 expect() calls" in control_stderr, "control_log_counts_mismatch")
    test_pin = verify_pin(checks["testPin"])
    test_text = Path(test_pin["path"]).read_text(encoding="utf-8")
    require("createJpgOwnedFlushFixture" in test_text and "m.flush_tree(root)" in test_text and "symlinkSync(target,link,'junction')" in test_text and "m.flush_tree(Path(sys.argv[1]).parent)" in test_text, "actual_source_bound_controls_missing")
    receipt_results = []
    for p in review["controls"]["realSourceBoundReceipts"]:
        p = verify_pin(p)
        v = read_json(p["path"])
        verify_pin(v["sourcePin"])
        require(v["sourcePin"] in sources and v["before"]["bytes"] == v["after"]["bytes"] and v["before"]["sha256"] == v["after"]["sha256"], "control_receipt_source_or_content")
        verify_pin(v["before"])
        verify_pin(v["after"])
        if "fsyncReturnedCount" in v:
            require(v["fsyncReturnedCount"] == 1 and v["bytesUnchanged"] is True and v["foreignError"] == "flush_not_self_owned" and v["junctionError"] == "flush_reparse" and v["outsideSourceUnchanged"] is True, "python_control_actual_boundary")
        else:
            require(v["fsyncReturned"] is True, "bun_control_fsync_not_returned")
        receipt_results.append({"pin": p, "value": v})
    red_pins = [verify_pin(p) for p in review["controls"]["redObservations"]]
    typecheck_run = next(v for v in checks["runs"] if v["name"] == "typecheck")
    typecheck_log = Path(typecheck_run["stdout"]["path"]).read_text(encoding="utf-8")
    require(typecheck_run["status"] == 1 and typecheck_log.count("error TS2339:") == 5 and all("scientific-journal-plan.ts" in line for line in typecheck_log.splitlines() if line), "typecheck_historical_diagnostics_not_preserved")

    historical_reports = [fixed(DOCS / "jpg-journal-independent-source-review-initial.json", (10426, "f8e840a778715c44e03627a6db552d2a72178e2fb66418b299984a1bebd04cc6")),
                          fixed(DOCS / "jpg-journal-independent-owned-delta-review.json", (8956, "9d95a3efbd999dc40e9d801869ffb622a0f3ad29ee26d7ffee8a6f5d5b332cb4"))]
    report = {
        "protocol": "jpg-journal-independent-final-source-review-v3",
        "atUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "validated": True,
        "validationScope": "Fixed-source delta, stored native control evidence, and explicit file Pin integrity. This is not a cold Docker or real-model execution certificate.",
        "formalPaidReady": False, "readyTaskIds": [], "blockingFindings": [],
        "ownerReview": review_pin, "checks": checks_pin,
        "sources": sources, "sourceSnapshots": snapshots,
        "executedSourcePins": {"count": len(execution), "mismatches": [], "observations": execution},
        "protectedScience": {"reference": science_pin, "count": len(protected), "mismatches": [], "observations": protected},
        "preservedHistory": {"baselineManifest": archive_pin, "savedCount": len(archived), "savedPins": archived, "previousReview": previous_review_pin, "independentReports": historical_reports, "redObservations": red_pins},
        "delta": {"pythonChangedFunctions": changed, "pythonAddedFunctions": added, "ownedGraphExactBytesUnchanged": True, "ownedProbeExactBytesUnchanged": True, "tsOwnedGraphInputsExactBytesUnchanged": True, "staticConditions": static_checks, "unifiedDiffs": diffs},
        "findings": [
            {"id": "N1", "priority": 1, "problem": "The original >=4 container count rejected legal no-output/budget-failure 2/3-CID runs.", "status": "resolved_in_exact_owned_v2_and_preserved_in_fsync_v3", "evidence": previous_review_pin, "historicalControlPins": historical_control_pins, "boundary": "The 7/19 synthetic owner controls belong to their fa749/5cf9 source set; unchanged owned_graph/probe and entry graph are compared byte for byte, rather than falsely rerunning or upgrading those controls."},
            {"id": "N2", "priority": 1, "problem": "Windows read-only rb/r handles made actual Python/Bun fsync fail with EBADF/EPERM before certification.", "status": "resolved_in_current_source_and_actual_F_native_controls", "evidence": checks_pin, "boundary": "Write access is limited to a new self-owned ordinary root and regular output. Hash/length are unchanged, original/source paths and actual junctions are rejected. This is not a power-loss guarantee."},
        ],
        "nativeControls": {"rerunByReviewer": False, "pass": 3, "fail": 0, "assertions": 14, "childExitCode": 0, "test": test_pin, "logPins": logs, "sourceBoundResults": receipt_results},
        "typecheck": {"exitCode": 1, "newSourceDiagnostics": 0, "frozenTransitiveDiagnostics": 5, "path": "scientific-journal-plan.ts", "originalFailureRetained": True},
        "staticContractAssessment": {
            "privateGrading": "Only fixed regular stat_ocr.xlsx or an explicit captured-absent/format verdict reaches the independent fixed full-image grader; original official tests/GT and clean interpreter remain private. No candidate snapshot or executable is used for grading.",
            "cash": "Admission f815 and contract b15 are unchanged. Frozen journal139a/raw-witness/CNY6ad/proofb1 remain explicit Pins. Fresh cash envelope is separate from legacy USD; 4 original unknowns remain carried, not settled. Source review alone is not an actual bill/receipt closure.",
            "lateAndDrain": "Gateway seal plus drain precedes stopped-candidate capture; provider/failed-journal late capture is retained and poison stops admission. Late tools/capture are declared budget failures rather than accepted late results. Background processes remain live until candidate stop.",
            "ownedRelease": "JPG family uses the canonical wx nonce and own source/raw/cash/owned/auditor graph. Exact candidate/grader IDs are rebuilt from bound receipts, checked against inventory and caller set, then independent PID/port/CID absence and fresh release checks are required. Scientific score wrappers are not fabricated.",
            "credentials": "Six exact host credentials must be scanned in the actual future run; private worker config exclusions are explicit. This review did not read keys, scan current secret values, or replace actual cold-mock credential/host-environment evidence.",
            "feedback": "CHECKS=6 caps explicit model verify only. Runtime automatic physical grading and independent final grading remain separately reported, with no equal-budget causal claim.",
            "crossFamily": "Shared canonical wx and unknown/active scope checks remain required. Future launchers must use the explicit cross-family preflight; the older frozen scientific scanner does not automatically know the new JPG registry.",
        },
        "experimentScope": {"sourceTaskCount": 87, "supportedTaskIds": ["jpg-ocr-stat"], "unsupportedTaskCount": 86, "actualNewColdMockComplete": False, "realModelResultsCertified": False, "oldSkillsBench85Point1Validated": False},
        "remaining": [
            "Root must run one new U/F cold Docker localmock using this exact source set, then independently close actual raw/source/CNY/credential/gateway/capture/private-grader/exact-owned evidence.",
            "Real-provider admission requires the active scientific paid family to close, a near-start fresh GET-only balance Pin (30min TTL), the fixed price Pin (24h and per-forward checks), explicit recipe cash envelope, current source-matching cold-mock certificate, and actual C/F resource floors.",
            "Native 3/14 and prior pure owner/contract controls cannot replace a cold container execution or prove generic namespace isolation for the other 86 tasks.",
        ],
        "reviewerScope": {"FReportWritesOnly": True, "originalOrRuntimeEdits": 0, "DockerOperations": 0, "modelCalls": 0, "providerQueries": 0, "productionLocks": 0, "PidOrPortProbes": 0, "CDEWrites": 0, "controlReruns": 0, "nativeExeRehashedInThisDelta": False,
            "metadataScopeDeviation": {"acknowledged": True, "description": "An earlier PowerShell read helper mistakenly assigned the read-only HOME variable, then enumerated user-directory filenames before exiting 1. It read filenames only, not those file contents or secret values, and performed no C/E/D writes or runtime edits. Fixed-path F-only reads resumed with task-specific variables. This is a reviewer metadata-read scope deviation, not an experiment/source mismatch."}},
        "reviewerScript": actual_pin(Path(__file__)),
    }
    raw = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    json_pin = write_new(OUT_JSON, raw)
    lines = [
        "JPG 最终独立源码复核已闭合。当前四源与审核件匹配，80 个 JPG 执行源、81 个科学保护源和 184 个旧版本归档文件逐项 SHA/长度一致；未发现新的源码阻挡。formalPaidReady 仍为 false。",
        "",
        "| 已确认问题 | 当前状态 | 证据与边界 |",
        "| --- | --- | --- |",
        "| 原容器数量 >=4 导致合法负例无法闭合 | 已修复，最终修订保留 | owned_graph/owned_probe、入口收据和容器集合输入与已审 exact-owned-v2 逐字相同。原 7 项 / 19 断言只属于其原源码；本次未重跑。 |",
        "| Windows 只读句柄 fsync 报 EBADF/EPERM | 已修复 | 新建自有普通输出使用 r+/r+b；原始三项实际 F-native 控制 3 pass、0 fail、14 断言、子进程退出 0。源码、目录及真实 junction 拒绝，文件长度/SHA 保持。未声称断电持久性。 |",
        "",
        "最终源：入口 a03704a6…、审计器 cb33c62c…；factory f815f002…、contract b15a108e…未变。控制记录对应这四个完整 SHA，实际结果文件和原日志再次只读核验通过。类型检查仍退出 1，五条诊断全部来自被冻结的 scientific-journal-plan.ts；没有把它改写为全绿。",
        "",
        "私有评分仍只转移固定 stat_ocr.xlsx（或已捕获的缺失/格式失败），使用完整固定任务镜像中的干净原解释器和私有官方测试。CNY、durable raw、晚回留证、封口、精确 owned nonce 和跨家族拒绝合同保持；本次没有运行 Docker、模型、网络或生产锁，也没有读取凭证。CHECKS=6 仅限制显式 verify，自动物理判卷及最终独立判卷另计。",
        "",
        "下一条件是由 root 对这套最终源码执行一次新的冷容器 U/F 零付费 mock 并独立审计实际工件，然后才可在科学付费家族闭合、余额/价格 TTL、显式现金预算与资源门均满足时评估真实单题运行。87/1/86 口径保留；本次不是模型成绩，也不认证旧 85.1%。",
        "",
        f"[独立 JSON]({str(OUT_JSON).replace(chr(92), '/')})，SHA `{json_pin['sha256']}`。源码、控制、历史失败和逐项观测 Pin 均在其中，原工件未改。",
        "",
        "审核期间曾因 PowerShell 只读 HOME 变量误用而列出用户目录文件名，随后退出 1；未读取这些文件内容、凭证或修改文件。该元数据读取范围偏差已单独记录，不作为实验数据或源码不一致。",
        "",
    ]
    md_pin = write_new(OUT_MD, "\n".join(lines).encode("utf-8"))
    print(json.dumps({"report": json_pin, "markdown": md_pin, "blockingFindings": 0, "formalPaidReady": False, "sourcePins": len(execution), "protectedSciencePins": len(protected), "archivedFiles": len(archived)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
