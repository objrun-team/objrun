"""Read frozen campaign artifacts; retain missing/invalid runs in every denominator."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGNS = ROOT / "docs/repair-2026-10-08/campaigns"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def summarize(path: Path) -> dict:
    manifest = read(path / "manifest.json")
    summary = read(path / "summary.json")
    ledger = read(path / "api-ledger.json")
    source = read(path / "source.json")
    regrade = read(path / "contract-regrade.json") if (path / "contract-regrade.json").exists() else None
    records = regrade["records"] if regrade else summary["records"]
    evidence_errors = []
    deferred = None
    deferred_path = path / "independent-deferred-closing-audit.json"
    if deferred_path.exists():
        deferred = read(deferred_path)
        valid_deferred = (deferred.get("run") == path.name and deferred.get("scoreCertificateValid") is True
            and deferred.get("integrityValid") is True and deferred.get("deferredClosingIdentityEvidence") is True
            and deferred.get("originalCampaignCompleted") is False and deferred.get("originalFatal") == "spawnSync docker ETIMEDOUT"
            and not deferred.get("errors") and not deferred.get("receiptErrors") and not deferred.get("taskErrors"))
        for name, item in deferred.get("inputArtifacts", {}).items():
            valid_deferred = valid_deferred and sha((path / name).read_bytes()) == item["sha256"]
        for item in deferred.get("taskChecks", []):
            valid_deferred = valid_deferred and sha((path / f"task-{item['index']}.json").read_bytes()) == item["artifact"]["sha256"]
        if not valid_deferred:
            evidence_errors.append("deferred_closing_certificate_invalid_or_stale")
        deferred = deferred if valid_deferred else None
    keys = [(r["benchmark"], r["officialId"], r["arm"], r["replica"]) for r in records]
    if len(keys) != len(set(keys)):
        evidence_errors.append("duplicate_task_arm_replica")
    allowed_keys = {(benchmark, task_id, arm, replica)
        for benchmark in manifest["benchmarks"]
        for task_id in manifest["datasets"][benchmark]["selectedTaskIds"]
        for arm in manifest["arms"]
        for replica in range(manifest["independentRReplicas"] if arm == "R" else 1)}
    if set(keys) - allowed_keys:
        evidence_errors.append("records_outside_frozen_plan")
    if (summary["completed"] or deferred) and set(keys) != allowed_keys:
        evidence_errors.append("completed_campaign_missing_planned_records")
    receipt_ids = [r.get("requestId") for r in ledger["calls"] if r.get("requestId")]
    if len(receipt_ids) != len(set(receipt_ids)):
        evidence_errors.append("duplicate_provider_request_id")
    all_artifacts = []
    for record in records:
        file = path / f"task-{record['index']}.json"
        task = read(file)
        if sha(str(task["answer"]).encode()) != task["candidateSha256"]:
            evidence_errors.append(f"candidate_digest:{record['index']}")
        # JS JSON.stringify uses compact UTF-8 JSON. Floats do not occur in these trace rows.
        trace_bytes = json.dumps(task["trace"], ensure_ascii=False, separators=(",", ":")).encode()
        if sha(trace_bytes) != task["traceSha256"]:
            evidence_errors.append(f"trace_digest:{record['index']}")
        if task["acceptance"] != record.get("originalAcceptance", record["acceptance"]):
            evidence_errors.append(f"acceptance_summary_mismatch:{record['index']}")
        all_artifacts.append({"path": file.name, "sha256": sha(file.read_bytes())})
    for name in ["manifest.json", "source.json", "summary.json", "api-ledger.json"]:
        file = path / name
        all_artifacts.append({"path": name, "sha256": sha(file.read_bytes())})
    if regrade:
        for item in regrade["baseInputs"]:
            if sha((path / item["path"]).read_bytes()) != item["sha256"]:
                evidence_errors.append(f"regrade_original_input_changed:{item['path']}")
        all_artifacts.append({"path": "contract-regrade.json", "sha256": sha((path / "contract-regrade.json").read_bytes())})
    if manifest.get("schemaVersion", 1) == 1 and not regrade:
        evidence_errors.append("pending_shared_contract_regrade")
    if (summary["completed"] or deferred) and abs(sum(c.get("usdUpperBound", 0) for c in ledger["calls"]) - ledger["recordedUsageUpperBoundUsd"]) > 1e-8:
        evidence_errors.append("provider_cost_receipts_do_not_reconcile")
    ready = bool(summary["completed"] and (not regrade or regrade["completed"]) and not summary.get("fatal") and not ledger.get("fatal")
                 and not sum(ledger.get("pending", {}).values()) and not evidence_errors)
    if deferred and not regrade:
        ready = bool(not sum(ledger.get("pending", {}).values()) and abs(ledger["reservedUpperBoundUsd"]) < 1e-8 and not evidence_errors)
        all_artifacts.append({"path": deferred_path.name, "sha256": sha(deferred_path.read_bytes())})
    complete_status = "deferred_runtime_closed" if deferred else "complete"
    groups = []
    for benchmark in manifest["benchmarks"]:
        official_ids = manifest["datasets"][benchmark]["selectedTaskIds"]
        expected = len(official_ids)
        for arm in manifest["arms"]:
            repetitions = range(manifest["independentRReplicas"] if arm == "R" else 1)
            for replica in repetitions:
                selected = [r for r in records if r["benchmark"] == benchmark and r["arm"] == arm and r["replica"] == replica]
                received_ids = [r["officialId"] for r in selected]
                if set(received_ids) - set(official_ids):
                    evidence_errors.append(f"foreign_task:{benchmark}:{arm}{replica}")
                valid = sum(r["acceptance"].get("valid", False) is True for r in selected)
                passed = sum(r["acceptance"].get("valid") is True and r["acceptance"].get("passed") is True for r in selected)
                pending_grading = sum(r["acceptance"].get("outcome") == "pending_after_all_generation" for r in selected)
                receipts = [c for r in selected for c in r["apiCalls"]]
                groups.append({"benchmark": benchmark, "arm": arm, "replica": replica,
                    "expectedTasks": expected, "recordedTasks": len(selected), "validTasks": valid,
                    "passedTasks": passed, "invalidOrMissingTasks": expected - valid,
                    "pendingFinalGradingTasks": pending_grading,
                    "missingTasks": len(set(official_ids) - set(received_ids)),
                    "scoreStatus": complete_status if ready and valid == expected else "incomplete",
                    "passedShareAllPlanned": passed / expected if ready and valid == expected else None,
                    "apiCalls": len(receipts), "inputTokens": sum(int(c.get("usage", {}).get("prompt_tokens", 0)) for c in receipts),
                    "outputTokens": sum(int(c.get("usage", {}).get("completion_tokens", 0)) for c in receipts),
                    "cachedInputTokens": sum(int(c.get("usage", {}).get("prompt_cache_hit_tokens", c.get("usage", {}).get("prompt_tokens_details", {}).get("cached_tokens", 0))) for c in receipts),
                    "usageUpperBoundUsd": sum(c.get("usdUpperBound", 0) for c in receipts),
                    "wallSecondsIncludingSettlement": sum(r["seconds"] for r in selected),
                    "candidateKinds": dict(Counter(r["candidateHow"] for r in selected))})
        if "R" in manifest["arms"]:
            r_by_id = {tid: [r for r in records if r["benchmark"] == benchmark and r["officialId"] == tid and r["arm"] == "R"] for tid in official_ids}
            complete_r = all(len(rs) == manifest["independentRReplicas"] and all(r["acceptance"].get("valid") is True for r in rs) for rs in r_by_id.values())
            groups.append({"benchmark": benchmark, "arm": "R_any_of_5", "replica": None,
                "expectedTasks": expected, "validTasks": sum(len(rs) == manifest["independentRReplicas"] and all(r["acceptance"].get("valid") is True for r in rs) for rs in r_by_id.values()),
                "passedTasks": sum(any(r["acceptance"].get("valid") is True and r["acceptance"].get("passed") is True for r in rs) for rs in r_by_id.values()),
                "pendingFinalGradingTasks": sum(any(r["acceptance"].get("outcome") == "pending_after_all_generation" for r in rs) for rs in r_by_id.values()),
                "scoreStatus": complete_status if ready and complete_r else "incomplete",
                "meaning": "Post-hoc any acceptance among five independent answers; no best answer was selected for generation or delivery."})
    return {"campaign": path.name, "profile": manifest["profile"], "completed": summary["completed"],
        "evidenceReady": ready and not evidence_errors, "sourceExecutionDigest": source["executionDigest"],
        "deferredRuntimeClosing": deferred_path.name if deferred else None,
        "originalFatal": summary.get("fatal") or ledger.get("fatal"),
        "manifestSha256": sha((path / "manifest.json").read_bytes()), "model": manifest["model"],
        "recordedUsageUpperBoundUsd": ledger["recordedUsageUpperBoundUsd"],
        "unresolvedReservedUpperBoundUsd": ledger["reservedUpperBoundUsd"], "plannedTaskRuns": summary["plannedTaskRuns"],
        "recordedTaskRuns": summary["recordedTaskRuns"], "providerCalls": len(ledger["calls"]),
        "evidenceErrors": evidence_errors, "groups": groups, "artifacts": all_artifacts,
        "acceptanceSource": "contract-regrade.json" if regrade else "native_campaign_contract", "limits": manifest["protocolLimits"] + (regrade["limits"] if regrade else [])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("campaigns", nargs="*")
    args = parser.parse_args()
    dirs = [CAMPAIGNS / name for name in args.campaigns] if args.campaigns else sorted(CAMPAIGNS.glob("*"))
    results = []
    for path in dirs:
        if not all((path / n).is_file() for n in ["manifest.json", "summary.json", "api-ledger.json", "source.json"]):
            continue  # Start failures with no manifest are not benchmark runs.
        report = summarize(path)
        (path / "analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        results.append(report)
    json_path = ROOT / "docs/repair-2026-10-08/new-results.json"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Actual run results after repair", "", "Reconstructed by summarize_campaigns.py from per-task evidence. All denominators were fixed before generation; missing or invalid runs are not removed.",
        "The new deepseek-flash baseline differs from the old 0731 model and tool protocol and cannot be backfilled into the old paper. Small batches validate the execution path; they cannot be extrapolated to full-set results.",
        "R any-of-5 is posthoc coverage across five independent answers; grading was not fed back to R, nor were answers selected for further generation.", ""]
    for report in results:
        state_label = "closed by later environment verification" if report["deferredRuntimeClosing"] else "complete evidence" if report["evidenceReady"] else "failed; original records retained" if report["originalFatal"] else "running or evidence awaiting verification"
        cost_label = f"recorded usage cost upper bound ${report['recordedUsageUpperBoundUsd']:.6f}"
        if report["unresolvedReservedUpperBoundUsd"] > 1e-8:
            cost_label += f", plus unclosed reservations ${report['unresolvedReservedUpperBoundUsd']:.6f}; complete actual cost unknown"
        lines += [f"## {report['campaign']}", "", f"State: {state_label}; task runs {report['recordedTaskRuns']}/{report['plannedTaskRuns']}; provider calls {report['providerCalls']}; {cost_label}.", "",
            "| Benchmark | Arm | Valid/planned tasks | Passed/planned tasks | State | Input/output tokens | Cost upper bound USD |", "|---|---|---|---|---|---|---|"]
        for g in report["groups"]:
            arm = f"R{g['replica'] + 1}" if g["arm"] == "R" else g["arm"]
            cost = f"{g['usageUpperBoundUsd']:.6f}" if "usageUpperBoundUsd" in g else "see total across five R runs"
            tokens = f"{g['inputTokens']}/{g['outputTokens']}" if "inputTokens" in g else "see total across five R runs"
            valid_label = f"{g['validTasks']}/{g['expectedTasks']}"
            passed_label = f"{g['passedTasks']}/{g['expectedTasks']}"
            if g.get("pendingFinalGradingTasks"):
                valid_label = f"original batch not jointly graded ({g['pendingFinalGradingTasks']} tasks recorded)" if report["originalFatal"] and not report["deferredRuntimeClosing"] else f"awaiting joint grading ({g['pendingFinalGradingTasks']} tasks generated)"
                passed_label = "awaiting grading"
            lines.append(f"| {g['benchmark']} | {arm} | {valid_label} | {passed_label} | {g['scoreStatus']} | {tokens} | {cost} |")
        lines += ["", f"Source execution digest: `{report['sourceExecutionDigest']}`. Original manifest/source/ledger/task JSON and data SQLite are retained in this run directory and `.phase1-data/repair/`.", ""]
        if report["deferredRuntimeClosing"]:
            lines += ["The original campaign retains `completed=false` and the Docker cleanup-query timeout. Later verification checked only the same container/image, read-only mounts, and actual dependency digests under the original frozen contract, without model calls or candidate reselection. See `independent-deferred-closing-audit.json` for the independent per-request/candidate/source audit and later observation time. Table results use this separate closure evidence without rewriting the original failure boundary.", ""]
    md_path = ROOT / "docs/repair-2026-10-08/new-results.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"campaigns": len(results), "evidenceErrors": {r['campaign']: r['evidenceErrors'] for r in results if r['evidenceErrors']}, "output": str(md_path)}, ensure_ascii=False))
    return int(any(r["evidenceErrors"] for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
