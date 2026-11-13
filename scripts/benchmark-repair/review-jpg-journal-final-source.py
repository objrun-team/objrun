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
    sources = [fixed(ROOT / "scripts/benchmark-repair" / name, pair) for name, pair in EXPECTED_SOURCES.items()]
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
    previous_py = (ARCHIVE / "scripts/benchmark-repair/audit-jpg-journal-campaign.py").read_text(encoding="utf-8")
    current_py = (ROOT / "scripts/benchmark-repair/audit-jpg-journal-campaign.py").read_text(encoding="utf-8")
    old_functions, new_functions = py_functions(previous_py), py_functions(current_py)
    changed = sorted(n for n in old_functions if n not in new_functions or old_functions[n] != new_functions[n])
    added = sorted(n for n in new_functions if n not in old_functions)
    require(set(changed) == expected_changed and added == ["create_owned_flush_fixture", "ordinary_owned_path"], "unexpected_python_semantic_delta")
    require(old_functions["owned_graph"] == new_functions["owned_graph"] and old_functions["owned_probe"] == new_functions["owned_probe"], "exact_owned_graph_changed")
    previous_ts = (ARCHIVE / "scripts/benchmark-repair/skb-jpg-journal-campaign.ts").read_text(encoding="utf-8")
    current_ts = (ROOT / "scripts/benchmark-repair/skb-jpg-journal-campaign.ts").read_text(encoding="utf-8")
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
        require((ARCHIVE / "scripts/benchmark-repair" / name).read_bytes() == (ROOT / "scripts/benchmark-repair" / name).read_bytes(), "unchanged_cash_or_contract_modified")

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
        "Final independent JPG source review is closed. The current four sources match the review artifacts; all 80 JPG execution sources, 81 protected scientific sources, and 184 archived old-version files match individually by SHA/length. No new source blocker was found. formalPaidReady remains false.",
        "",
        "| Confirmed issue | Current state | Evidence and boundary |",
        "| --- | --- | --- |",
        "| Original container count >=4 prevented closure for valid negative cases | Fixed; final revision retained | owned_graph/owned_probe, entry receipt, and container-set inputs are byte-identical to reviewed exact-owned-v2. Original 7 checks / 19 assertions apply only to their original source; they were not rerun here. |",
        "| Windows read-only-handle fsync raised EBADF/EPERM | Fixed | Newly created owned regular outputs use r+/r+b; original three actual F-native controls: 3 pass, 0 fail, 14 assertions, subprocess exit 0. Source, directory, and real junction are rejected; file lengths/SHAs are preserved. No power-loss durability claim is made. |",
        "",
        "Final sources: entry a03704a6…, auditor cb33c62c…; factory f815f002… and contract b15a108e… are unchanged. Control records correspond to these four complete SHAs; actual result files and original logs passed another read-only verification. Type checking still exits 1, with all five diagnostics from frozen scientific-journal-plan.ts; this was not rewritten as all-green.",
        "",
        "Private grading still transfers only pinned stat_ocr.xlsx (or a captured missing/format failure), using the clean original interpreter and private official tests in the complete pinned task image. CNY, durable raw data, late-response evidence, sealing, exact owned nonce, and cross-family rejection contracts are preserved. No Docker, model, network, or production-lock operations ran here, and no credentials were read. CHECKS=6 limits only explicit verify; automatic physical grading and independent final grading are counted separately.",
        "",
        "The next requirement is for root to execute one fresh cold-container U/F zero-cost mock with these final sources and independently audit the actual artifacts. Only then, after scientific paid-family closure, balance/price TTL, explicit cash budget, and resource gates are satisfied, may a real single-task run be assessed. The 87/1/86 scope is retained; this is not a model result and does not certify the old 85.1%.",
        "",
        f"[Independent JSON]({str(OUT_JSON).replace(chr(92), '/')}), SHA `{json_pin['sha256']}`. It contains sources, controls, historical failures, and individual observation pins; original artifacts are unchanged.",
        "",
        "During review, misuse of the read-only PowerShell HOME variable caused user-directory filenames to be listed, followed by exit 1. No file contents or credentials were read, and no files were modified. This metadata-read scope deviation is recorded separately; it is not treated as experimental data or a source inconsistency.",
        "",
    ]
    md_pin = write_new(OUT_MD, "\n".join(lines).encode("utf-8"))
    print(json.dumps({"report": json_pin, "markdown": md_pin, "blockingFindings": 0, "formalPaidReady": False, "sourcePins": len(execution), "protectedSciencePins": len(protected), "archivedFiles": len(archived)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
