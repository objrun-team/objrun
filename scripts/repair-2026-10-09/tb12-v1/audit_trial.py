"""Independent stdlib replay of raw TB trial evidence. No Docker/API execution."""
import argparse
from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import traceback


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 ** 2):
            result.update(block)
    return result.hexdigest()


def pin(path):
    path = Path(path).resolve()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}


def verified(reference):
    path = Path(reference["path"])
    assert path.is_file() and not path.is_symlink(), path
    if "bytes" in reference:
        assert path.stat().st_size == reference["bytes"], path
    assert digest(path) == reference["sha256"], path
    return path


def document(path):
    return json.loads(Path(path).read_bytes())


def expanded(path, maximum):
    with gzip.open(path, "rb") as stream:
        raw = stream.read(maximum + 1)
    assert len(raw) <= maximum, path
    return raw


def peak(start, stop):
    first = datetime.fromisoformat(start.replace("Z", "+00:00"))
    last = datetime.fromisoformat(stop.replace("Z", "+00:00"))
    assert last >= first
    first += timedelta(hours=8)
    last += timedelta(hours=8)
    day = first.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= last:
        if day.weekday() < 5:
            for begin, end in ((9, 12), (14, 18)):
                if last >= day + timedelta(hours=begin) and first <= day + timedelta(hours=end):
                    return True
        day += timedelta(days=1)
    return False


def replay_journal(home, provider_kind):
    folder = home / "provider"
    config_path = folder / "journal-config.json"
    config = document(config_path)
    assert config["protocol"] == "campaign-api-journal-v1"
    previous = digest(config_path)
    starts, finishes = {}, {}
    requests = responses = 0
    token_totals = {"prompt": 0, "completion": 0, "cacheHit": 0}
    cny = 0
    events = 0
    with (folder / "api-events.jsonl").open("rb") as stream:
        for line in stream:
            assert line.endswith(b"\n") and len(line) <= 65536
            event = json.loads(line)
            assert event["protocol"] == "campaign-api-journal-v1"
            assert event["eventSeq"] == events and event["previousEventSha256"] == previous
            previous = hashlib.sha256(line).hexdigest()
            events += 1
            seq, record = event["requestSeq"], event["record"]
            if event["kind"] == "start":
                assert seq not in starts and seq == len(starts)
                starts[seq] = record
                request_path = verified({"path": record["requestFile"], "sha256": record["requestCompressedSha256"]})
                raw = expanded(request_path, 4 * 1024 ** 2)
                assert hashlib.sha256(raw).hexdigest() == record["requestSha256"] and len(raw) == record["requestBytes"]
                body = json.loads(raw)
                assert body["model"] == "deepseek-flash" and body.get("stream") is not True
                assert body["temperature"] == 0 and body["seed"] == 42
                assert body["reasoning_effort"] == "none" and body["thinking"] == {"type": "disabled"}
                assert body["max_tokens"] == 8192
                upper = len(raw) + 2048 + len(body["messages"]) * 256
                assert abs(record["reservationUsd"] - (upper * 0.3 + 8192 * 1.2) / 1e6) < 1e-12
                requests += 1
            elif event["kind"] == "finish":
                assert seq in starts and seq not in finishes
                finishes[seq] = record
                assert record["requestSha256"] == starts[seq]["requestSha256"]
                if record["providerAttempted"]:
                    response_path = verified({"path": record["responseFile"], "sha256": record["responseCompressedSha256"]})
                    raw = expanded(response_path, 64 * 1024 ** 2)
                    assert hashlib.sha256(raw).hexdigest() == record["responseSha256"]
                    body = json.loads(raw)
                    assert record["httpStatus"] == 200 and body["usage"] == record["usage"]
                    assert body["model"] == record["servedModel"] and body["id"] == record["requestId"]
                    assert record["completionValid"] is True and not record.get("fault")
                    assert len(body["choices"]) == 1 and body["choices"][0]["finish_reason"] in ("stop", "tool_calls")
                    usage = body["usage"]
                    prompt, output = usage["prompt_tokens"], usage["completion_tokens"]
                    hit = usage.get("prompt_cache_hit_tokens", 0)
                    assert all(isinstance(value, int) and value >= 0 for value in (prompt, output, hit)) and hit <= prompt
                    if "prompt_cache_miss_tokens" in usage:
                        assert usage["prompt_cache_miss_tokens"] + hit == prompt
                    if provider_kind == "real-provider":
                        high = peak(record["startedAt"], record["finishedAt"])
                        cny += (prompt - hit) * (2000 if high else 1000) + hit * (40 if high else 20) + output * (8000 if high else 4000)
                        token_totals["prompt"] += prompt
                        token_totals["completion"] += output
                        token_totals["cacheHit"] += hit
                    responses += 1
                else:
                    assert record["confirmedNoForward"] is True and record["usdUpperBound"] == 0
            else:
                raise AssertionError("Unknown journal event")
    assert starts.keys() == finishes.keys()
    checkpoint = document(folder / "api-state.json")
    assert checkpoint["durablePrefix"]["eventCount"] == events and checkpoint["durablePrefix"]["lastSha256"] == previous
    cash = document(home / "cash/cash-close.json")
    verified(cash["configPin"])
    verified(cash["cashEventsPin"])
    assert cash["journalAccountingClosed"] is True and cash["journalValid"] is True and cash["releasePermitted"] is True
    assert cash["snapshot"]["pendingCount"] == cash["snapshot"]["newUnknownCount"] == 0
    assert int(cash["snapshot"]["newKnownEstimatedNanoCny"]) == cny
    return {"requests": requests, "responses": responses, "journalEvents": events, "newEstimatedNanoCny": str(cny), "tokens": token_totals}


def audit_native(home):
    database = home / "stand-process/stand/owned-native.sqlite"
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    commands = actors = 0
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        for index, raw in connection.execute("SELECT id,json FROM command ORDER BY id"):
            record = json.loads(raw)
            assert record["index"] == index and record["nativePid"] > 0
            assert record["closeObserved"] is True and not record["timedOut"] and not record["overflow"]
            assert not record["captureFaults"] and isinstance(record["exitCode"], int)
            assert record["argv"][1:3] == ["--host", "npipe:////./pipe/dockerDesktopLinuxEngine"]
            for name in ("stdout", "stderr"):
                reference = record[name]
                verified(reference)
                assert reference["bytesObserved"] == reference["bytesStored"] == Path(reference["path"]).stat().st_size
            commands += 1
        for cid, role, name, image, closed, raw in connection.execute("SELECT cid,role,name,image,closed,json FROM actor"):
            actor = json.loads(raw)
            assert closed == 1 and actor["initialState"]["Id"] == cid and actor["initialState"]["Image"] == image
            initial = actor["initialState"]
            assert initial["Labels"]["objrun.tb12.role"] == role and initial["Name"].lstrip("/") == name
            assert not initial["HostConfig"].get("Binds") and not initial["HostConfig"]["Privileged"]
            assert initial["HostConfig"]["Memory"] == 2048 * 1024 ** 2 and initial["HostConfig"]["NanoCpus"] == 1000000000
            assert initial["HostConfig"]["PidMode"] != "host"
            if role.startswith("private-checker") or role == "untrusted-openssl-worker":
                assert initial["HostConfig"]["ReadonlyRootfs"] and initial["HostConfig"]["CapDrop"] == ["ALL"]
            absent = actor["absenceReceipt"]
            assert absent["exitCode"] != 0
            stderr = Path(absent["stderr"]["path"]).read_text(encoding="utf-8").lower()
            assert "no such object:" in stderr and cid in stderr
            assert actor["removalReceipt"]["exitCode"] == 0
            actors += 1
    finally:
        connection.close()
    return {"nativeCommandsVerified": commands, "exactOwnedActorsVerifiedClosed": actors}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    home, output = Path(args.run_directory).resolve(), Path(args.output).resolve()
    manifest, summary = document(home / "manifest.json"), document(home / "summary.json")
    inputs = [pin(home / "manifest.json"), pin(home / "summary.json")]
    result, failure = {}, None
    try:
        assert manifest["protocol"] == "tb12-paired-trial-manifest-v1" and manifest["family"] == "terminal-bench-twelve-journal-v1"
        assert summary["operationalComplete"] is True and summary["fatal"] is None
        expected = [(task, arm) for task in manifest["taskIds"] for arm in ("U", "F")]
        assert len(summary["taskPins"]) == len(expected) == manifest["plannedTaskRuns"]
        if manifest["providerKind"] == "real-provider":
            assert len(manifest["taskIds"]) == 12 and len(expected) == 24
        source_notes = []
        for reference in manifest["sourcePins"]:
            source = Path(reference["path"])
            if digest(source) != reference["sha256"]:
                snapshot = home / "source-snapshots" / source.name
                if not snapshot.exists():
                    snapshot = home / "source-snapshots" / (reference["sha256"] + "-" + source.name)
                assert digest(snapshot) == reference["sha256"], source
                source_notes.append({"original": reference, "matchingSnapshot": pin(snapshot)})
            else:
                verified(reference)
        for reference in manifest["bundle"]["files"]:
            verified(reference)
        stand = document(home / "stand-process/stand/stand-receipts.json")
        assert not stand["openActors"] and stand["fatal"] is None
        grades, score = {}, {"U": 0, "F": 0}
        for row in stand["rows"]:
            if row["kind"] == "grade":
                path = verified({"path": row["gradePath"], "sha256": row["gradeSha256"]})
                receipt = document(path)
                value = receipt["result"]
                assert row["invocationId"] == value["invocationId"] == receipt["invocationId"]
                assert receipt["candidateCid"] in {r["cid"] for r in stand["rows"] if r["kind"] == "candidate-up"}
                assert value["exitCode"] in (0, 1) and value["reward"] == int(value["exitCode"] == 0)
                assert value["pythonVersion"].startswith("3.13.7") and value["numericGuestPid"] > 0
                assert value["pythonExecutableSha256"] == "73b68fc2dac176af16098180a2c98a03ee9f1f1b02db25d42d44d782e79e2330"
                grades[row["invocationId"]] = row
                inputs.append(pin(path))
            elif row["kind"] in ("ran-delivered", "passed-delivered"):
                assert row["invocationId"] in grades
        tasks = []
        for index, (reference, pair) in enumerate(zip(summary["taskPins"], expected)):
            task = document(verified(reference))
            assert task["index"] == index and (task["officialId"], task["arm"]) == pair
            assert task["generationValid"] is True and task["acceptance"]["valid"] is True
            assert task["candidateLabelSha256"] == hashlib.sha256(task["answer"].encode()).hexdigest()
            assert task["hostEngineClosedBeforeFinalGrade"] is True and task["sealedBeforeHostFinalGrade"] is True
            closed = document(verified(task["engineClosePin"]))
            assert closed["exitObserved"] is True and closed["closeObserved"] is True and not closed["captureFaults"]
            assert task["calls"] and all(call["finishedAt"] and call["httpStatus"] == 200 for call in task["calls"])
            db = sqlite3.connect((home / "workers" / (str(index) + "-" + task["arm"]) / "data/h2h.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
            try:
                count = db.execute("SELECT count(*) FROM agent_bot_msg WHERE instance LIKE ?", (task["taskId"] + "#%",)).fetchone()[0]
                assert count == len(task["trace"]), "Incomplete raw trace capture"
            finally:
                db.close()
            accepted = task["acceptance"]
            assert accepted["passed"] == (accepted["outcome"] == "passed")
            score[task["arm"]] += int(accepted["passed"])
            tasks.append({"officialId": task["officialId"], "arm": task["arm"], "passed": accepted["passed"], "outcome": accepted["outcome"]})
            inputs.append(reference)
        result = {"raw": replay_journal(home, manifest["providerKind"]), "native": audit_native(home),
                  "taskRuns": len(tasks), "distinctTaskCount": len(manifest["taskIds"]), "score": score, "tasks": tasks,
                  "matchingExecutedSources": source_notes}
    except BaseException as error:
        failure = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"protocol": "tb12-independent-raw-trial-audit-v1", "runId": manifest["runId"],
                                  "family": manifest["family"], "providerKind": manifest["providerKind"],
                                  "integrityValid": failure is None, "modelCallsByAuditor": 0,
                                  "apiRequestsByAuditor": 0, "dockerOperationsByAuditor": 0,
                                  "candidateCodeExecutedByAuditor": False, "result": result, "failure": failure,
                                  "inputPins": inputs, "auditorSourcePin": pin(Path(__file__)),
                                  "labelDigestIsFilesystemDigest": False}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output), "integrityValid": failure is None, "failure": failure, "modelCalls": 0}))
    if failure:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
