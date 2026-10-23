"""Portable independent ZIP byte and raw provider/cash-chain replay, stdlib only."""
import argparse
from datetime import datetime, timedelta
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile


def peak(start, stop):
    first = datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(hours=8)
    last = datetime.fromtimestamp(stop / 1000, first.tzinfo) + timedelta(hours=8)
    assert last >= first
    day = first.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= last:
        if day.weekday() < 5:
            for begin, end in ((9, 12), (14, 18)):
                if last >= day + timedelta(hours=begin) and first <= day + timedelta(hours=end):
                    return True
        day += timedelta(days=1)
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    archive, target = Path(args.archive).resolve(), Path(args.output).resolve()
    result = hashlib.sha256()
    with archive.open("rb") as stream:
        while block := stream.read(1024 ** 2):
            result.update(block)
    archive_sha = result.hexdigest()
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        manifest = json.loads(bundle.read("package-manifest.json"))
        assert manifest["distinctTaskCount"] == 12 and manifest["realTaskRuns"] == 24
        assert manifest["userBudgetCny"] == "9" and manifest["retainedOriginalUnknownCarryCny"] == "8.39218"
        entries = {row["archivePath"]: row for row in manifest["files"]}
        assert len(entries) == len(manifest["files"])
        assert set(bundle.namelist()) == set(entries) | {"package-manifest.json"}
        original = {row["originalPath"]: row["archivePath"] for row in manifest["files"]}
        for row in manifest["sourceAliases"]:
            assert entries[row["archivePath"]]["sha256"] == row["sha256"] and entries[row["archivePath"]]["bytes"] == row["bytes"]
            original[row["originalPath"]] = row["archivePath"]
        for name, row in entries.items():
            assert not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts and "\\" not in name
            assert bundle.getinfo(name).file_size == row["bytes"]
            digest = hashlib.sha256()
            with bundle.open(name) as stream:
                while block := stream.read(1024 ** 2):
                    digest.update(block)
            assert digest.hexdigest() == row["sha256"]
        def raw(path, expected=None):
            name = original[path]
            value = bundle.read(name)
            assert expected is None or hashlib.sha256(value).hexdigest() == expected
            return value
        def doc(name):
            return json.loads(bundle.read(name))
        def pinned(pin):
            return json.loads(raw(pin["path"], pin["sha256"]))
        config = doc("trial/provider/journal-config.json")
        previous = hashlib.sha256(bundle.read("trial/provider/journal-config.json")).hexdigest()
        starts, finishes = {}, {}
        journal = bundle.read("trial/provider/api-events.jsonl")
        lines = journal.splitlines(keepends=True)
        for index, line in enumerate(lines):
            assert line.endswith(b"\n")
            value = json.loads(line)
            assert value["eventSeq"] == index and value["previousEventSha256"] == previous
            previous = hashlib.sha256(line).hexdigest()
            seq, record = value["requestSeq"], value["record"]
            assert seq >= 0 and isinstance(seq, int)
            if value["kind"] == "start":
                assert seq not in starts and seq == len(starts)
                starts[seq] = record
                body_raw = gzip.decompress(raw(record["requestFile"], record["requestCompressedSha256"]))
                assert len(body_raw) <= 4 * 1024 ** 2 and hashlib.sha256(body_raw).hexdigest() == record["requestSha256"]
                body = json.loads(body_raw)
                assert body["model"] == "deepseek-flash" and body["temperature"] == 0 and body["seed"] == 42
                assert body["thinking"] == {"type": "disabled"} and body["reasoning_effort"] == "none" and body["max_tokens"] == 8192
            else:
                assert value["kind"] == "finish" and seq in starts and seq not in finishes
                finishes[seq] = record
                assert record["providerAttempted"] and record["httpStatus"] == 200 and record["completionValid"]
                body_raw = gzip.decompress(raw(record["responseFile"], record["responseCompressedSha256"]))
                assert len(body_raw) <= 2 * 1024 ** 2 and hashlib.sha256(body_raw).hexdigest() == record["responseSha256"]
                body = json.loads(body_raw)
                assert body["usage"] == record["usage"] and body["model"] == record["servedModel"] and body["id"] == record["requestId"]
        assert starts.keys() == finishes.keys()
        state = doc("trial/provider/api-state.json")
        assert state["durablePrefix"] == {"bytes": len(journal), "eventCount": len(lines), "lastSha256": previous}
        cash_close = doc("trial/cash/cash-close.json")
        cash_config = pinned(cash_close["configPin"])
        admission = pinned(cash_config["admissionPin"])
        for pin in admission["sourcePins"]:
            assert hashlib.sha256(raw(pin["path"])).hexdigest() == pin["sha256"]
        assert admission["owned"]["ownerNonce"] == cash_config["ownerNonce"] == cash_close["ownerNonce"]
        assert cash_config["envelopeNanoCny"] == admission["selectedNewEnvelopeNanoCny"] == "9000000000"
        assert cash_config["carryNanoCny"] == admission["carryNanoCny"] == "8392180000"
        events_raw = raw(cash_close["cashEventsPin"]["path"], cash_close["cashEventsPin"]["sha256"])
        cash_previous = cash_close["configPin"]["sha256"]
        cash_states = {}
        event_lines = events_raw.splitlines(keepends=True)
        for index, line in enumerate(event_lines):
            value = json.loads(line)
            assert line.endswith(b"\n") and value["eventSeq"] == index and value["previousEventSha256"] == cash_previous
            cash_previous = hashlib.sha256(line).hexdigest()
            data = value["data"]
            seq = data["requestSeq"]
            if value["kind"] == "start":
                assert seq not in cash_states and data["dispatchAllowed"]
                request = starts[seq]
                body_raw = gzip.decompress(raw(data["requestPin"]["path"], data["requestPin"]["sha256"]))
                body = json.loads(body_raw)
                assert hashlib.sha256(body_raw).hexdigest() == data["rawRequestSha256"] == request["requestSha256"]
                upper = len(body_raw) + 2048 + len(body["messages"]) * 256
                reservation = upper * 2000 + 8192 * 8000
                assert data["inputUpper"] == upper and data["outputLimit"] == 8192
                assert int(data["reservedNanoCny"]) == int(data["peakReservationNanoCny"]) == reservation
                assert sum(row["amount"] for row in cash_states.values()) + reservation <= 9000000000
                cash_states[seq] = {"amount": reservation, "finished": False}
            else:
                assert value["kind"] == "finish" and data["phase"] == "known" and seq in cash_states and not cash_states[seq]["finished"]
                assert data["source"]["kind"] == "journal-finish"
                begin, end = data["source"]["journalRef"]["finishOffset"], data["source"]["journalRef"]["finishEnd"]
                finish_line = journal[begin:end]
                assert hashlib.sha256(finish_line).hexdigest() == data["source"]["journalRef"]["finishLineSha256"]
                assert json.loads(finish_line)["record"] == finishes[seq]
                usage = finishes[seq]["usage"]
                high = peak(starts[seq]["startedAt"], data["hostCaptureWallUnixMs"])
                prompt, completion, hit = usage["prompt_tokens"], usage["completion_tokens"], usage.get("prompt_cache_hit_tokens", 0)
                assert all(isinstance(x, int) and x >= 0 for x in (prompt, completion, hit)) and hit <= prompt
                amount = (prompt - hit) * (2000 if high else 1000) + hit * (40 if high else 20) + completion * (8000 if high else 4000)
                assert data["observedUsage"] == usage and int(data["amountNanoCny"]) == amount
                cash_states[seq] = {"amount": amount, "finished": True}
        assert len(cash_states) == len(starts) and all(row["finished"] for row in cash_states.values())
        assert cash_close["cashPrefix"] == {"bytes": len(events_raw), "eventCount": len(event_lines), "lastSha256": cash_previous}
        known = sum(row["amount"] for row in cash_states.values())
        assert int(cash_close["snapshot"]["newKnownEstimatedNanoCny"]) == known <= 9000000000
        assert cash_close["snapshot"]["pendingCount"] == cash_close["snapshot"]["newUnknownCount"] == 0
        review = doc("trial/independent/deep-review.json")
        assert review["integrityValid"] and len(review["tasks"]) == 24
        score = {arm: sum(row["passed"] for row in review["tasks"] if row["arm"] == arm) for arm in ("U", "F")}
    target.write_text(json.dumps({"protocol": "tb12-portable-independent-package-review-v1", "integrityValid": True,
                                 "archive": str(archive), "archiveSha256": archive_sha, "exportedFilesVerified": len(entries),
                                 "rawProviderRequestsVerified": len(starts), "rawCashEventsVerified": len(event_lines),
                                 "newKnownEstimatedNanoCny": str(known), "score": score, "distinctTaskCount": 12, "realTaskRuns": 24,
                                 "modelCallsByReviewer": 0, "candidateCodeExecuted": False, "dockerOperations": 0,
                                 "invoice": False, "retainedOriginalUnknownCarryNanoCny": "8392180000"}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(target), "integrityValid": True, "modelCalls": 0}))


if __name__ == "__main__":
    main()
