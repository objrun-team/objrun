"""Additional independent raw checker, namespaces and paired-result review.

Uses only stdlib file/SQLite reads. Never runs a model, container or candidate.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import traceback

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 ** 2):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-directory", required=True)
    args = parser.parse_args()
    home = Path(args.run_directory).resolve()
    def doc(path):
        return json.loads(Path(path).read_bytes())
    def verified(pin):
        path = Path(pin["path"])
        assert path.is_file() and not path.is_symlink() and sha(path) == pin["sha256"]
        if "bytes" in pin:
            assert path.stat().st_size == pin["bytes"]
        return path
    manifest, summary = doc(home / "manifest.json"), doc(home / "summary.json")
    tables, failure, grades_verified = [], None, 0
    try:
        assert summary["operationalComplete"] and summary["providerKind"] == "real-provider" and summary["recordedTaskRuns"] == 24
        audit = doc(home / "independent/raw-audit.json")
        assert audit["integrityValid"] and audit["result"]["taskRuns"] == 24
        certificate = doc(home / "independent/close-certificate.json")
        assert certificate["kind"] == "score-and-financial" and certificate["rawFinancialVerified"] and certificate["tokenSecretScanPassed"]
        for pin in certificate["inputPins"]:
            verified(pin)
        assert doc(home / "entry-closed.json")["canonicalOwnerReleased"]
        stand = doc(home / "stand-process/stand/stand-receipts.json")
        context = doc(verified(manifest["contextManifest"]))
        scope = doc(verified(manifest["officialScope"]))
        assert scope["taskCount"] == 12 and scope["taskIds"] == manifest["taskIds"]
        public_scope = {row["taskId"]: row for row in scope["records"]}
        for row in scope["records"]:
            for key in ("publicInputs", "environmentSourcePins", "rubricSourcePins"):
                for pin in row[key]:
                    verified(pin)
        tasks = {value["taskId"]: value for value in context["tasks"]}
        sources = {Path(pin["path"]).name: pin for pin in manifest["sourcePins"] if Path(pin["path"]).name == "private_checker.py"}
        candidates = {row["place"]: row for row in stand["rows"] if row["kind"] == "candidate-up"}
        original_grades = {}
        for row in stand["rows"]:
            if row["kind"] != "grade":
                continue
            record = doc(verified({"path": row["gradePath"], "sha256": row["gradeSha256"]}))
            start = record["start"]
            assert start["closeObserved"] and start["exitCode"] == 0 and not start["overflow"] and not start["timedOut"]
            assert not start["captureFaults"] and record["finalState"]["State"]["ExitCode"] == 0
            raw = verified(start["stdout"]).read_text(encoding="utf-8")
            final = raw.strip().splitlines()[-1]
            assert final.startswith("TB12_RESULT:")
            frame = json.loads(final[len("TB12_RESULT:"):])
            assert frame == record["result"]
            assert frame["checkerSourceSha256"] == sources["private_checker.py"]["sha256"]
            assert frame["invocationId"] == row["invocationId"] == record["invocationId"]
            assert frame["taskId"] == row["taskId"] and not frame["collectOnly"]
            assert frame["packages"] == context["packages"]
            assert frame["numericGuestPid"] > 0 and frame["numericParentPid"] >= 0
            assert frame["monotonicSeconds"] <= tasks[row["taskId"]]["verifierSeconds"] + 30
            expected = set(tasks[row["taskId"]]["staticTestNames"])
            results = frame["ctrf"]["results"]
            observed = results["tests"]
            assert len(observed) == len(expected) and {value["name"].split("::")[-1] for value in observed} == expected
            counts = {status: sum(value["status"] == status for value in observed) for status in ("passed", "failed", "skipped", "pending", "other")}
            assert results["summary"]["tests"] == len(expected)
            assert all(results["summary"][status] == count for status, count in counts.items())
            assert frame["reward"] == int(frame["exitCode"] == 0) == int(counts["passed"] == len(expected))
            candidate = candidates[row["place"]]
            private = frame["privateNamespaces"]
            public = candidate["initialNamespaces"]
            assert private["pid"] != public["pid"] and private["mnt"] != public["mnt"]
            assert (private["net"] == public["net"]) == (row["taskId"] == "nginx-request-logging")
            calibration = candidate["runtime"]["numericPidAndClockCalibration"]
            assert calibration["measuredBeforeAnyModel"] and calibration["guest"]["numericGuestPid"] > 0
            assert calibration["guest"]["availableStorageBytes"] >= 10240 * 1024 ** 2
            assert candidate["runtime"]["runningState"]["State"]["Pid"] > 0
            protected_matches = True
            if row["taskId"] != "nginx-request-logging":
                capsule = doc(record["capsulePath"])
                items = {item["path"]: item for item in capsule["files"]}
                protected_matches = all(items[path]["exists"] and items[path]["sha256"] == original["sha256"]
                                        for path, original in candidate["protectedInputs"].items())
                for item in items.values():
                    if item["exists"]:
                        assert sha(Path(item["stored"])) == item["sha256"]
            assert protected_matches == row["protectedInputsUnchanged"]
            exceeded = any(value["kind"] == "candidate-storage-observation" and value["place"] == row["place"] and value["exceeded"]
                           for value in stand["rows"][:stand["rows"].index(row)])
            assert row["policyReward"] == int(frame["reward"] and protected_matches and not exceeded)
            original_grades[row["invocationId"]] = (row, record)
            grades_verified += 1
        for row in stand["rows"]:
            if row["kind"] == "passed-delivered":
                assert row["value"] == bool(original_grades[row["invocationId"]][0]["policyReward"])
        for pin in summary["taskPins"]:
            task = doc(verified(pin))
            public = public_scope[task["officialId"]]
            instruction_pin = next(pin for pin in public["publicInputs"] if Path(pin["path"]).name == "instruction.md")
            prompt = verified(instruction_pin).read_text(encoding="utf-8") + "\n\nEvery bash/read/write/edit/glob/grep call runs inside your task container. Submit the completed filesystem or service state; your answer is only an attempt label. Official tests remain outside your container. Use verify only when offered."
            assert hashlib.sha256(prompt.encode()).hexdigest() == task["promptSha256"]
            assert task["agentSeconds"] == public["agentSeconds"] and task["verifierSeconds"] == public["verifierSeconds"]
            matches = [(row, record) for row, record in original_grades.values() if row["place"] == task["place"]]
            original_final = task["generation"]["kind"] != "experimental_failure"
            if original_final:
                assert matches
                final_row, final_record = matches[-1]
                assert task["acceptance"]["passed"] == bool(final_row["policyReward"])
                engine = doc(verified(task["engineClosePin"]))
                assert datetime.fromisoformat(final_record["start"]["startedAtUtc"]) >= datetime.fromisoformat(engine["closedAtUtc"].replace("Z", "+00:00"))
            else:
                assert not task["acceptance"]["passed"] and task["acceptance"]["outcome"] == task["generation"]["outcome"]
            verifies = sum(row["kind"] == "tool" and json.loads(row["body"]).get("name") == "verify" for row in task["trace"])
            assert task["arm"] == "F" or verifies == 0
            usage = {name: sum(call["usage"].get(key, 0) for call in task["calls"]) for name, key in
                     (("promptTokens", "prompt_tokens"), ("completionTokens", "completion_tokens"), ("cacheHitTokens", "prompt_cache_hit_tokens"))}
            tables.append({"taskId": task["officialId"], "arm": task["arm"], "passed": task["acceptance"]["passed"],
                           "outcome": task["acceptance"]["outcome"], "modelRequests": len(task["calls"]),
                           "runtimeVerifyCalls": verifies, "actualPrivateGrades": len(matches), **usage})
            tables[-1]["originalFinalGradePerformed"] = original_final
        assert len(tables) == 24 and len({row["taskId"] for row in tables}) == 12
    except BaseException as error:
        failure = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
    target = home / "independent/deep-review.json"
    target.write_text(json.dumps({"protocol": "tb12-independent-deep-review-v1", "runId": manifest["runId"],
                                 "integrityValid": failure is None, "failure": failure, "privateGradesVerified": grades_verified,
                                 "tasks": tables, "modelCallsByReviewer": 0, "candidateCodeExecuted": False,
                                 "dockerOperations": 0, "apiRequests": 0, "reviewerSourceSha256": sha(Path(__file__)),
                                 "hardStorageQuotaEnforced": False, "liveNginxIsImmutableSnapshot": False}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(target), "integrityValid": failure is None, "privateGradesVerified": grades_verified, "failure": failure}))
    if failure:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
