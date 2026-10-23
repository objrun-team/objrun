"""Create a separate adaptation work board; never change scores or dispatch work.

Existing audit files can lag active runs. This inventory assigns ownership only;
an unpaid-looking task still requires current receipt checks before publication.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / "docs/repair-2026-10-10/full-f-rerun"
OUTPUT = BASE / "efficient-resume-20261012/parallel-prep-20261013"
FUNCTIONS = {
    "pytorch-model-recovery", "pytorch-model-cli", "feal-differential-cryptanalysis",
    "portfolio-optimization", "largest-eigenval",
    "adaptive-rejection-sampler", "build-cython-ext", "caffe-cifar-10",
    "compile-compcert", "fix-ocaml-gc", "hf-model-inference", "make-doom-for-mips",
    "make-mips-interpreter", "mcmc-sampling-stan", "protein-assembly",
    "reshard-c4-data", "sam-cell-seg", "sqlite-with-gcov",
    "torch-pipeline-parallelism", "torch-tensor-parallelism",
}
SERVICES = {
    "git-multibranch", "kv-store-grpc", "break-filter-js-from-html", "filter-js-from-html",
    "configure-git-webserver", "headless-terminal", "install-windows-3.11",
    "mailman", "pypi-server", "qemu-alpine-ssh", "qemu-startup",
}


def read(path):
    return json.loads(path.read_bytes())


def pin(path):
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def main():
    tb, sb = BASE / "terminal-bench", BASE / "skillsbench"
    audit = read(tb / "actual-run-audit.json")
    manifest = read(tb / "manifest.json")
    sb_manifest = read(sb / "manifest.json")
    queue = read(sb / "task-queue-v2.json")
    valid = {t["officialId"] for t in audit["tasks"] if t.get("valid")}
    paid = Counter(q["taskId"] for r in audit["runs"] for q in r.get("requests", []))
    recoveries = {}
    for path in (tb / "finalization-recoveries").glob("*.json"):
        recovery = read(path)
        # Preserve the recovery as a separate record, not an extra raw score.
        if recovery.get("doNotRerun"):
            recoveries[recovery["taskId"]] = pin(path)
    rows = []
    for task in manifest["taskIds"]:
        if task in valid:
            status = "existing-valid-preserved"
        elif task in recoveries:
            status = "existing-recovery-preserved"
        elif paid[task]:
            status = "paid-attempt-preserved-needs-individual-review"
        elif task == "overfull-hbox":
            status = "reserved-for-original-chat"
        else:
            status = "adaptation-backlog-current-paid-check-required"
        owner = ("tb_function_adapters" if task in FUNCTIONS else
                 "tb_service_adapters" if task in SERVICES else
                 "original-chat" if task == "overfull-hbox" else "root")
        row = {"benchmark": "terminal-bench", "taskId": task,
               "status": status, "owner": owner,
               "auditedRequestsLowerBound": paid[task], "ready": False}
        if task in recoveries:
            row["recoveryPin"] = recoveries[task]
        rows.append(row)
    completed = set(queue["completed"])
    repair = set(queue["repair"])
    for task in sb_manifest["taskSchedule"]:
        task_id = task["taskId"]
        status = ("existing-valid-preserved" if task_id in completed else
                  "repair-history-review-required" if task_id in repair else
                  "adaptation-backlog-current-paid-check-required")
        rows.append({"benchmark": "skillsbench", "taskId": task_id,
                     "status": status, "owner": "sb_adapters", "ready": False})
    assert len(rows) == 176 and len({(r["benchmark"], r["taskId"]) for r in rows}) == 176
    report = {
        "protocol": "parallel-adaptation-work-board-v1",
        "atUtc": datetime.now(timezone.utc).isoformat(),
        "requestedSubagentModel": "gpt-6.1-sol", "requestedSubagentConcurrency": 16,
        "toolConcurrentAgentLimitIncludingRoot": 4, "activeSubagentAllocation": 3,
        "auditAtUtc": audit.get("atUtc"), "auditMayLagLiveRuns": True,
        "notAPublicationOrScoreLedger": True, "modelCalls": 0,
        "sourcePins": [pin(p) for p in [tb / "actual-run-audit.json", tb / "manifest.json",
                                        sb / "manifest.json", sb / "task-queue-v2.json"]],
        "counts": dict(Counter(r["status"] for r in rows)), "tasks": rows,
        "publicationRequirements": [
            "Fresh original paid/valid/recovery/active task checks, not this advisory board",
            "Original test semantics and budgets; candidate/private checker isolation",
            "Original collection and missing/reference/wrong qualification actually complete",
            "Six runtime tools verified and immutable source/evidence pins validated",
            "Publish through existing sole scheduler; never create a competing owner",
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "work-board.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT / "work-board.json"), "counts": report["counts"],
                      "readyClaimed": 0, "modelCalls": 0}))


if __name__ == "__main__":
    main()
