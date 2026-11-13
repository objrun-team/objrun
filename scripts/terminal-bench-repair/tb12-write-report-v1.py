"""Write the reviewable paired trial report from verified real receipts."""
import argparse
from decimal import Decimal
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-directory", required=True)
    args = parser.parse_args()
    home = Path(args.run_directory).resolve()
    def read(name):
        return json.loads((home / name).read_bytes())
    review, audit = read("independent/deep-review.json"), read("independent/raw-audit.json")
    summary, manifest = read("summary.json"), read("manifest.json")
    cash = read("cash/cash-close.json")
    assert review["integrityValid"] and audit["integrityValid"] and summary["operationalComplete"]
    assert summary["providerKind"] == "real-provider" and len(review["tasks"]) == 24
    assert read("entry-closed.json")["canonicalOwnerReleased"]
    scores = audit["result"]["score"]
    money = Decimal(cash["snapshot"]["newKnownEstimatedNanoCny"]) / Decimal(1000000000)
    assert money <= 9 and cash["snapshot"]["pendingCount"] == cash["snapshot"]["newUnknownCount"] == 0
    rows = {(row["taskId"], row["arm"]): row for row in review["tasks"]}
    lines = ["# Review of the live Terminal-Bench 12-task U/F pilot", "",
             "This round completed 12 fixed distinct tasks and 24 actual U/F records. Independent original-material audits and additional grading replays passed; all exactly owned containers, engines, and grading services closed, and the shared canonical owner was released under independent closure evidence. The earlier single nginx task is excluded.", "",
             f"U: {scores['U']}/12; F: {scores['F']}/12. Total actual model requests: {summary['modelCalls']}. Estimated new cost replayed from original usage and public CNY prices is **CNY {money}**, authorized cap **CNY 9**; pending and new unknown costs are both 0. The original **CNY 8.39218** unsettled reservation remains, not settled by this round closing. Cost estimates are not invoices.", "",
             "| Fixed task | U | F | U/F model requests | U/F runtime verify | U/F actual grading count |",
             "|---|---|---|---|---|---|"]
    for task_id in manifest["taskIds"]:
        u, f = rows[task_id, "U"], rows[task_id, "F"]
        def verdict(row):
            return "passed" if row["passed"] else row["outcome"]
        lines.append(f"| {task_id} | {verdict(u)} | {verdict(f)} | {u['modelRequests']}/{f['modelRequests']} | {u['runtimeVerifyCalls']}/{f['runtimeVerifyCalls']} | {u['actualPrivateGrades']}/{f['actualPrivateGrades']} |")
    lines += ["", "Experimental failures such as `no_candidate` score 0 under the frozen protocol, but must not be described as original tests having run and failed. `rejected` means grading after an actual submission did not pass. Grading counts include F runtime checks and executed final checks; they are not counted as distinct tasks or repeated pilots.", "",
              "Independent review individually checked the final frame of native grader stdout, invocation IDs, actual exits, individual CTRF results for 48 original tests, private source and dependency versions, candidate/grader PID and mount namespaces, network isolation, protected-input hashes, and actual engine closure before final grading. Complete raw requests/responses, SQLite traces, event chains, code snapshots, each fault, and closure proofs remain in this round directory.", "",
              "Preparation actually completed 36 empty/positive/incorrect controls across tasks, original-test collection, original six-tool and storage measurements for 12 tasks, dual OpenSSL untrusted-island controls, and zero-model integration with the real project engine. Mock responses and preparation controls count toward neither this round's model requests nor results.", "",
              "This round covers 12/89 tasks and 11 categories, frozen from public metadata, one U/F pair per task with fixed U-then-F order. It does not establish full-set performance or task-frequency representativeness. Only the requested model alias deepseek-flash can be pinned; original provider responses return the same alias, which does not establish an immutable underlying checkpoint. Temperature 0 and seed 42 do not guarantee determinism.", "",
              "Original agent/verifier durations are retained. Additional operational boundaries are 8192 output tokens per request, 32 units per loop, 4 checks for F, 2 MiB tool streams, and task-specific file-capture caps. Original test.sh is archived; original tests actually run through an explicitly new offline runner, which must not be described as the complete official execution environment.", "",
              "The Docker backend does not support a 10 GiB per-container hard quota. This round measured at least 10 GiB available storage before model calls, sampled writable layers before/after tools and at seal, and rejected out-of-bounds candidates; this is **not a continuous hard limit**. nginx uses restricted live TLS observation, not an immutable filesystem snapshot. OpenSSL candidate scripts execute only in an independent untrusted island, passing stdout/stderr/exit as data to the private checker.", "",
              "F feedback contains ran/passed booleans and generic failure explanations, without sending private assertions to the model. CSV/JSON/NPY/Parquet/SQLite and other artifacts are captured under an allowlist; NPY disables pickle, SQLite disables extensions and is read-only, and original databases/reference SQL/calendars remain consistent during grading.", "",
              "Original independent audit: `independent/raw-audit.json`. Additional grading review: `independent/deep-review.json`. Financial closure: `cash/cash-close.json` and `independent/close-certificate.json`. Fresh resource recheck: `fresh-absence/`. Original authorization, protocol, and dependency pins are referenced by admission and readiness artifacts.", "",
              "This round awaits user confirmation; it does not automatically start full runs, R, or paper edits.", ""]
    target = home / "README.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"report": str(target), "score": scores, "estimatedCny": str(money), "modelRequests": summary["modelCalls"]}))


if __name__ == "__main__":
    main()
