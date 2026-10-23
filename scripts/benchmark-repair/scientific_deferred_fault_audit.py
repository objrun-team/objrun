"""Read saved receipts and authorized copied SQLite metadata; never call a grader."""
from __future__ import annotations

import collections
import datetime as dt
import decimal
import gzip
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import time
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUN = "repair-2026-10-08T11-00-41-864Z"
META = ROOT / "docs/repair-2026-10-08/campaigns" / RUN
STORE = ROOT / ".phase1-data/repair" / RUN
COPY = ROOT / ".scratch/science1220-oom-readonly-snapshot"
DOC = ROOT / "docs/repair-2026-10-08"
SNAPSHOT_SHA = "932a203ef5de0b7c4f0becddcd03f522bfd11111682988f14c4a2441d1f6195a"
ARCHIVE_SHA = "1973bb8b4cd328bf025b4acc189987d2dc7b4c57ca8e30612bd473025864d339"
EXECUTION_SHA = "8c3380d084ab18b011215a1d5db65a6896e85874da07156706042c0caf7f6ba2"
ORIGINALS: dict[pathlib.Path, dict] = {}
STARTED = time.monotonic()


def require(ok: bool, label: str) -> None:
    if not ok:
        raise RuntimeError("Evidence gate failed: " + label)


def fingerprint(path: pathlib.Path) -> dict:
    require(path.is_file() and not path.is_symlink(), "regular evidence file")
    before = path.stat()
    h = hashlib.sha256()
    with path.open("rb") as src:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            h.update(block)
    after = path.stat()
    require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
            "file stable during SHA read")
    return {"bytes": after.st_size, "mtimeNs": after.st_mtime_ns, "sha256": h.hexdigest()}


def original(path: pathlib.Path) -> bytes:
    require(not any(x in path.name for x in ("h2h.sqlite", ".sqlite-wal", ".sqlite-shm")),
            "original SQLite must not be read")
    fp = fingerprint(path)
    if path in ORIGINALS:
        require(ORIGINALS[path] == fp, "repeat original read identity")
    ORIGINALS[path] = fp
    raw = path.read_bytes()
    require(len(raw) == fp["bytes"] and hashlib.sha256(raw).hexdigest() == fp["sha256"],
            "original read identity")
    return raw


def original_json(path: pathlib.Path):
    return json.loads(original(path))


def relative(path: pathlib.Path) -> str:
    return path.relative_to(ROOT).as_posix()


def provider_name(index: int, kind: str) -> str:
    return f"provider-{index}-{kind}.json.gz"


def safe_ledger_path(value: str, expected: pathlib.Path) -> None:
    require(pathlib.Path(value).resolve() == expected.resolve(), "exact fixed provider path")


def gzip_fingerprint(path: pathlib.Path) -> dict:
    fp = fingerprint(path)
    h = hashlib.sha256()
    n = 0
    with gzip.open(path, "rb") as src:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            n += len(block)
            h.update(block)
    require(fingerprint(path) == fp, "gzip stable through CRC and raw SHA")
    ORIGINALS[path] = fp
    return {"path": relative(path), **fp, "rawBytes": n,
            "rawSha256": h.hexdigest(), "gzipEofCrcVerified": True}


def utc_ms(value: int) -> str:
    return dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc).isoformat()


def route_for(item: dict) -> str:
    return f"{RUN}/{item['benchmark']}/{item['arm']}/{item['replica']}/{item['officialId']}"


def task_id_for(item: dict) -> str:
    return f"{RUN}/{item['benchmark']}/{item['arm']}{item['replica']}/{item['officialId']}"


def durable_new_report(path: pathlib.Path, raw: bytes) -> None:
    require(not path.exists(), "new report cannot overwrite previous evidence")
    tmp = path.with_name(path.name + ".owned.tmp")
    with tmp.open("xb") as sink:
        sink.write(raw)
        sink.flush()
        os.fsync(sink.fileno())
    os.replace(tmp, path)


def main() -> None:
    names_before = sorted(p.name for p in META.glob("*.json"))
    metadata = {name: original_json(META / name) for name in names_before}
    manifest, source = metadata["manifest.json"], metadata["source.json"]
    ledger, summary = metadata["api-ledger.json"], metadata["summary.json"]
    require(len(names_before) == 263, "fixed original JSON inventory")
    require(manifest["campaign"] == ledger["campaign"] == summary["campaign"] == RUN,
            "campaign identity")
    require(manifest["sourceExecutionDigest"] == source["executionDigest"] == EXECUTION_SHA,
            "frozen execution digest")
    require(summary["completed"] is False and summary["plannedTaskRuns"] == 1220,
            "interrupted campaign identity")
    require(ledger["captureErrors"] == [], "saved capture error list")
    require(manifest["ratesPeakUsdPerMillion"] == {"input": 0.3, "cachedInput": 0.006, "output": 1.2}
            and manifest["maxTokensPerRequest"] == 8192, "frozen rates and output limit")
    schedule = manifest["taskSchedule"]
    schedule_sha = hashlib.sha256(json.dumps(schedule, ensure_ascii=False,
                                             separators=(",", ":")).encode()).hexdigest()
    require(schedule_sha == manifest["taskScheduleSha256"] == source["taskScheduleSha256"],
            "exact frozen schedule")
    require(len(schedule) == 1220 and [x["index"] for x in schedule] == list(range(1220)),
            "fixed schedule indices")
    schedule_by_id = {task_id_for(x): x for x in schedule}
    schedule_by_route = {route_for(x): x for x in schedule}
    require(len(schedule_by_id) == len(schedule_by_route) == 1220, "unique scheduled identities")

    archive_path = STORE / "frozen-source.zip"
    archive_raw = original(archive_path)
    require(ORIGINALS[archive_path]["sha256"] == ARCHIVE_SHA, "frozen ZIP SHA")
    selected_source = {}
    source_entries = {x["path"]: x for x in source["files"] + source["repairFiles"]}
    with zipfile.ZipFile(archive_path) as archive:
        for member in ("scripts/benchmark-repair/campaign-next.ts",
                       "scripts/benchmark-repair/campaign-contract.ts"):
            raw = archive.read(member)
            sha = hashlib.sha256(raw).hexdigest()
            require(sha == source_entries[member]["sha256"], "frozen source member SHA")
            selected_source[member] = {"sha256": sha, "bytes": len(raw)}
        runner = archive.read("scripts/benchmark-repair/campaign-next.ts").decode()
    del archive_raw
    formula = (
        "const inputUpper = Buffer.byteLength(raw) + 2048 + "
        "(Array.isArray(body.messages) ? body.messages.length * 256 : 0);"
    )
    require(formula in runner and
            "const reserve = (inputUpper * 0.3 + outputLimit * 1.2) / 1e6;" in runner,
            "actual frozen reservation formula")
    require(runner.index("record.httpStatus = response.status") < runner.index("await response.text()"),
            "HTTP header precedes body capture")
    require(runner.index("await response.text()") < runner.index("record.responseFile"),
            "saved response follows complete body")

    calls = ledger["calls"]
    require(len(calls) == 5476, "fixed ledger call count")
    unfinished = [i for i, c in enumerate(calls) if not c.get("finishedAt")]
    require(unfinished == [5470, 5471, 5473, 5475], "fixed unfinished calls")
    finished = [c for c in calls if c.get("finishedAt")]
    require(len(finished) == 5472 and all(c.get("costBasis") == "reported_usage" for c in finished),
            "saved finished usage basis")
    require(all("accountedUpperBoundUsd" in c and "usage" in c for c in finished),
            "finished costs and usage actually present")
    require(abs(sum(c["accountedUpperBoundUsd"] for c in finished) -
                ledger["recordedUsageUpperBoundUsd"]) < 1e-8, "finished original cost sum")
    require(summary["recordedUsageUpperBoundUsd"] == ledger["recordedUsageUpperBoundUsd"],
            "original summary and ledger cost agreement")
    call_routes = set(c["route"] for c in calls)
    require(call_routes <= schedule_by_route.keys(), "all provider routes scheduled")
    provider_names_before = sorted(p.name for p in STORE.iterdir() if p.name.startswith("provider-"))
    expected_names = sorted([provider_name(i, "request") for i in range(len(calls))] +
                            [provider_name(i, "response") for i, c in enumerate(calls)
                             if c.get("responseFile")])
    require(provider_names_before == expected_names and len(expected_names) == 10948,
            "exact complete provider gzip inventory; no orphan captures")
    gzip_inventory = []
    by_name = {}
    for pos, name in enumerate(provider_names_before, 1):
        match = re.fullmatch(r"provider-(\d+)-(request|response)\.json\.gz", name)
        require(match is not None, "fixed gzip name")
        index, kind = int(match[1]), match[2]
        path = STORE / name
        safe_ledger_path(calls[index][kind + "File"], path)
        item = gzip_fingerprint(path)
        require(item["rawSha256"] == calls[index][kind + "Sha256"],
                "provider raw SHA agrees with saved ledger")
        item.update({"ledgerPosition": index, "kind": kind})
        gzip_inventory.append(item)
        by_name[name] = item
        if pos % 2000 == 0:
            print(json.dumps({"progress": "saved-gzip-crc-sha", "verified": pos,
                              "total": len(expected_names)}), flush=True)

    deferred = []
    reserve_sum = decimal.Decimal(0)
    for index in unfinished:
        call = calls[index]
        req_path = STORE / provider_name(index, "request")
        with gzip.open(req_path, "rb") as src:
            raw = src.read()
        require(hashlib.sha256(raw).hexdigest() == call["requestSha256"],
                "unfinished raw request identity")
        body = json.loads(raw)
        require(isinstance(body.get("messages"), list) and body.get("max_tokens") == 8192,
                "saved raw wire request shape and output bound")
        messages = len(body["messages"])
        input_upper = len(raw) + 2048 + messages * 256
        reserve = (decimal.Decimal(input_upper) * decimal.Decimal("0.3") +
                   decimal.Decimal(body["max_tokens"]) * decimal.Decimal("1.2")) / 1_000_000
        reserve_sum += reserve
        response_path = STORE / provider_name(index, "response")
        require(not response_path.exists() and not call.get("responseFile")
                and not call.get("finishedAt") and not call.get("usage"),
                "no saved original response or completion")
        require(call["providerAttempted"] is True and ledger["pending"][call["route"]] == 1,
                "original provider-attempt and pending evidence")
        item = schedule_by_route[call["route"]]
        deferred.append({"ledgerPosition": index, "scheduleIndex": item["index"],
                         "benchmark": item["benchmark"], "arm": item["arm"],
                         "officialId": item["officialId"], "taskId": task_id_for(item),
                         "route": call["route"], "startedAt": call["startedAt"],
                         "providerAttempted": True, "httpHeaderStatus": call.get("httpStatus"),
                         "requestGzip": by_name[req_path.name], "rawRequestBytes": len(raw),
                         "messageCount": messages, "inputUpperBoundFromFrozenFormula": input_upper,
                         "outputLimit": 8192, "reservationUsdExact": str(reserve),
                         "originalResponseFile": call.get("responseFile"),
                         "expectedOriginalResponseFileExists": False, "originalFinishedAt": None,
                         "recoverableUsageFromOriginalResponse": None,
                         "actualUsage": None, "actualBilledUsd": None,
                         "faultType": "deferred_missing_complete_provider_receipt"})
    require(abs(float(reserve_sum) - ledger["reservedUpperBoundUsd"]) < 1e-9,
            "original aggregate reservation agreement")
    positive_pending = {k: v for k, v in ledger["pending"].items() if v > 0}
    require(positive_pending == {x["route"]: 1 for x in deferred}, "four pending routes only")

    snapshot_path = DOC / "science1220-oom-readonly-snapshot.json"
    snapshot_raw = original(snapshot_path)
    require(hashlib.sha256(snapshot_raw).hexdigest() == SNAPSHOT_SHA, "approved snapshot certificate")
    snapshot = json.loads(snapshot_raw)
    require(snapshot["validated"] is True and snapshot["originalFilesUnchanged"] is True
            and snapshot["files"] and len(snapshot["files"]) == 12
            and snapshot["sqliteOpened"] is False, "initial copy certificate")
    copy_identity = []
    for entry in snapshot["files"]:
        path = pathlib.Path(entry["copyPath"])
        require(path.resolve().is_relative_to(COPY.resolve()), "exact authorized copied DB path")
        require(path.relative_to(COPY).as_posix() == entry["relative"],
                "authorized snapshot relative path")
        before = fingerprint(path)
        is_shm = path.name.endswith("-shm")
        if not is_shm:
            require(before["sha256"] == entry["sha256"] and before["bytes"] == entry["bytes"],
                    "copied DB/WAL agrees with initial snapshot")
        copy_identity.append({"relative": entry["relative"], "initialCopy": {
            k: entry[k] for k in ("bytes", "mtimeNs", "sha256")},
            "beforeAudit": before, "copiedShmMayChange": is_shm})
    published = {}
    worker_counts = {}
    for worker in range(4):
        path = COPY / f"worker-{worker}/data/h2h.sqlite"
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            rows = connection.execute(
                "SELECT id, run, state, created_at, solve_seconds, result IS NULL "
                "FROM task WHERE run = ? ORDER BY id", (RUN,)).fetchall()
        finally:
            connection.close()
        worker_counts[str(worker)] = len(rows)
        for task_id, run, state, created_at, seconds, result_null in rows:
            require(run == RUN and task_id in schedule_by_id and task_id not in published,
                    "unique copied published task identity")
            item = schedule_by_id[task_id]
            published[task_id] = {"taskId": task_id, "scheduleIndex": item["index"],
                                 "benchmark": item["benchmark"], "arm": item["arm"],
                                 "replica": item["replica"], "officialId": item["officialId"],
                                 "worker": worker, "state": state,
                                 "createdAtMs": created_at, "createdAtUtc": utc_ms(created_at),
                                 "solveSeconds": seconds,
                                 "deadlineUtc": utc_ms(created_at + seconds * 1000),
                                 "resultNull": bool(result_null),
                                 "terminal": state in ("done", "failed")}
    records = summary["records"]
    require(len(records) == summary["recordedTaskRuns"] == 254, "fixed recorded result count")
    recorded_ids = set()
    for record in records:
        index = record["index"]
        require(record["taskId"] == task_id_for(schedule[index]) and
                record["taskId"] in published and record["taskId"] not in recorded_ids,
                "recorded result matches copied published schedule")
        require(record["worker"] == published[record["taskId"]]["worker"], "recorded worker identity")
        saved_task = metadata[f"task-{index}.json"]
        require({k: v for k, v in saved_task.items() if k != "trace"} == record,
                "original task JSON and original summary record agree")
        recorded_ids.add(record["taskId"])
    require(len(published) == 258 and worker_counts == {"0": 60, "1": 75, "2": 67, "3": 56},
            "fixed closed snapshot publication counts")
    classifications = []
    for item in schedule:
        task_id = task_id_for(item)
        cls = ("recorded" if task_id in recorded_ids else
               "published_without_record" if task_id in published else
               "not_published_in_all_four_closed_snapshots")
        row = {"scheduleIndex": item["index"], "benchmark": item["benchmark"],
               "arm": item["arm"], "replica": item["replica"], "officialId": item["officialId"],
               "taskId": task_id, "classification": cls,
               "hasOriginalProviderRoute": route_for(item) in call_routes}
        if task_id in published:
            row["copiedTaskMetadata"] = published[task_id]
        else:
            require(not row["hasOriginalProviderRoute"], "unpublished task has no provider route")
        classifications.append(row)
    counts = dict(collections.Counter(x["classification"] for x in classifications))
    require(counts == {"recorded": 254, "published_without_record": 4,
                      "not_published_in_all_four_closed_snapshots": 962},
            "schedule classification count")
    unpublished_records = [x for x in classifications if x["classification"] == "published_without_record"]
    require({x["taskId"] for x in unpublished_records} == {x["taskId"] for x in deferred}
            and all(x["copiedTaskMetadata"]["state"] == "claimed"
                    and x["copiedTaskMetadata"]["resultNull"] for x in unpublished_records),
            "four missing records correspond to deferred calls and claimed null tasks")

    for entry in copy_identity:
        after = fingerprint(COPY / entry["relative"])
        entry["afterAudit"] = after
        entry["unchangedDuringAudit"] = after == entry["beforeAudit"]
        if not entry["copiedShmMayChange"]:
            require(entry["unchangedDuringAudit"], "copied main DB and WAL unchanged")
    require(sorted(p.name for p in META.glob("*.json")) == names_before,
            "original JSON inventory unchanged")
    require(sorted(p.name for p in STORE.iterdir() if p.name.startswith("provider-")) ==
            provider_names_before, "original gzip membership unchanged")
    evidence_identity = []
    for path, before in ORIGINALS.items():
        after = fingerprint(path)
        require(before == after, "original evidence SHA/bytes/mtime unchanged")
        evidence_identity.append({"path": relative(path), "before": before, "after": after,
                                  "unchanged": True})
    by_arm = []
    for bench, arm in sorted(set((x["benchmark"], x["arm"]) for x in classifications)):
        subset = [x for x in classifications if x["benchmark"] == bench and x["arm"] == arm]
        by_arm.append({"benchmark": bench, "arm": arm, "planned": len(subset),
                       "counts": dict(collections.Counter(x["classification"] for x in subset))})
    report = {
        "protocol": "saved-scientific-campaign-deferred-fault-v1",
        "observedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "campaign": RUN, "validated": True, "type": "infrastructure_abort_with_unknown_provider_receipts",
        "fatalEvidence": {"localTaskStateGet": True, "httpStatus": 500, "error": "out of memory",
                          "taskId": f"{RUN}/cmt/F0/cmt-38",
                          "classification": "local_machine_task_state_get_failed",
                          "underlyingAllocationCause": None, "graderParserFaultEstablished": False,
                          "savedSummarySha256": ORIGINALS[META / "summary.json"]["sha256"]},
        "source": {"auditSourceSha256": fingerprint(pathlib.Path(__file__))['sha256'],
                   "executionDigest": EXECUTION_SHA, "archiveSha256": ARCHIVE_SHA,
                   "selectedFrozenMembers": selected_source,
                   "reservationRuleLines": [94, 95], "responseCaptureRuleLines": [124, 130],
                   "finallyRuleLines": [158, 164]},
        "campaignState": {"completed": False, "plannedTaskRuns": 1220, "recordedTaskRuns": 254,
                          "uniformPosthocFinalCompleted": False, "summaryGeneratedAt": summary["generatedAt"]},
        "cost": {"ledgerCalls": 5476, "finishedWithReportedUsage": 5472, "unfinished": 4,
                 "originalRecordedUsageUpperBoundUsd": ledger["recordedUsageUpperBoundUsd"],
                 "finishedAccountedSumUsd": sum(c["accountedUpperBoundUsd"] for c in finished),
                 "originalReservedUpperBoundUsd": ledger["reservedUpperBoundUsd"],
                 "reconstructedPendingReservationUsdExact": str(reserve_sum),
                 "inputUpperFormula": "raw UTF-8 request bytes + 2048 + messages count * 256",
                 "reservationFormula": "(inputUpper * 0.3 + outputLimit * 1.2) / 1000000",
                 "ratesPeakUsdPerMillion": manifest["ratesPeakUsdPerMillion"],
                 "frozenCampaignExposureUpperBoundUsd":
                     ledger["recordedUsageUpperBoundUsd"] + float(reserve_sum),
                 "priorCampaignCostUpperBoundUsd": ledger["priorCampaignCostUpperBoundUsd"],
                 "frozenAggregateGuardExposureUsd":
                     ledger["priorCampaignCostUpperBoundUsd"] +
                     ledger["recordedUsageUpperBoundUsd"] + float(reserve_sum),
                 "capUsd": ledger["capUsd"], "actualPendingBilledUsd": None,
                 "actualPendingTokenUsage": None,
                 "limitation": "Frozen protocol accounting and reservations are not a provider invoice or a guarantee of provider token compliance."},
        "deferredCalls": deferred,
        "providerGzip": {"files": len(gzip_inventory),
                         "requests": sum(x["kind"] == "request" for x in gzip_inventory),
                         "responses": sum(x["kind"] == "response" for x in gzip_inventory),
                         "compressedBytes": sum(x["bytes"] for x in gzip_inventory),
                         "rawBytes": sum(x["rawBytes"] for x in gzip_inventory),
                         "allEofCrcVerified": True, "allRawShaMatchLedger": True,
                         "allCompressedShaBeforeAfterMatch": True, "inventory": gzip_inventory},
        "schedule": {"taskScheduleSha256": schedule_sha, "counts": counts, "byBenchmarkArm": by_arm,
                     "workerPublishedCounts": worker_counts,
                     "publishedStates": dict(collections.Counter(x["state"] for x in published.values())),
                     "classifications": classifications,
                     "scope": "Publication is proved only against all four closed, WAL-aware authorized snapshots; terminal state is not a uniform final score."},
        "snapshot": {"certificateSha256": SNAPSHOT_SHA, "initialCertificateObservedAtUtc": snapshot["observedAtUtc"],
                     "initialCertificateSqliteOpened": False, "copiedMetadataSqliteOpenedForThisAudit": True,
                     "copyIdentity": copy_identity,
                     "limitation": "Root initial copy hashes predate earlier authorized copied-metadata probes. Copied SHM may change; originals were never opened or rehashed by this audit."},
        "identity": {"originalJsonFiles": len(names_before), "originalFrozenSourceArchives": 1,
                     "originalInputsUnchanged": True, "originalEvidenceFiles": evidence_identity},
        "boundaries": {"newProviderApiCalls": 0, "newModelCalls": 0, "newGraderCalls": 0,
                       "newPosthocScores": 0, "originalSqliteOpened": False,
                       "originalDbWalShmRead": False, "originalEvidenceModified": False,
                       "networkCalls": 0, "dockerMutations": 0, "paperChanges": 0,
                       "candidateExecutions": 0, "cmtParserDiagnostic": False,
                       "pendingFinishedOrUsageFabricated": False,
                       "paidRestartPermittedByThisReport": False},
        "elapsedSeconds": round(time.monotonic() - STARTED, 3),
    }
    md = [
        f"Campaign {RUN} stopped after 254 of 1220 saved result records. Uniform posthoc final scoring did not complete.",
        "",
        "The saved fatal is a local machine task-state GET for cmt/F0/cmt-38 returning HTTP 500 with out of memory. It does not establish a CMT grader/parser failure; the underlying allocation cause remains unknown.",
        "",
        f"The original ledger has 5476 calls: 5472 finished entries with reported usage and USD {ledger['recordedUsageUpperBoundUsd']:.12f} recorded accounting upper bound, plus four unfinished entries. All four lack their original response gzip, usage and finishedAt. Three have HTTP 200 headers only. The fourth still records providerAttempted=true. Actual pending usage and billed fees remain unknown.",
        "",
        "| Ledger position | Official task | Header status | Raw request bytes | Messages | Frozen input upper | Reservation USD |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for x in deferred:
        md.append(f"| {x['ledgerPosition']} | {x['officialId']} | {x['httpHeaderStatus']} | "
                  f"{x['rawRequestBytes']} | {x['messageCount']} | "
                  f"{x['inputUpperBoundFromFrozenFormula']} | {x['reservationUsdExact']} |")
    md += [
        "",
        f"The frozen runner computes inputUpper = raw UTF-8 bytes + 2048 + messages × 256; reserve = (inputUpper × 0.3 + 8192 × 1.2) / 1,000,000. The exact sum is USD {reserve_sum}, agreeing with the saved floating point reserved amount {ledger['reservedUpperBoundUsd']}. This is a reconstructed protocol reservation, not recovered billing. No missing receipt was replaced with zero, a usage guess or a fabricated finished marker.",
        "",
        f"Frozen campaign exposure is USD {report['cost']['frozenCampaignExposureUpperBoundUsd']:.12f}; with prior campaigns it is USD {report['cost']['frozenAggregateGuardExposureUsd']:.12f} against the original USD {ledger['capUsd']} guard. These are frozen accounting figures, not a provider invoice.",
        "",
        "| Schedule classification | Count | Evidence |",
        "|---|---:|---|",
        "| Saved original record | 254 | Original task JSON equals its summary record and matches copied published task identity |",
        "| Published without record | 4 | Closed SQLite/WAL snapshots show claimed, result NULL: schedule 233, 239, 251, 257 |",
        "| Not published in all four closed snapshots | 962 | No task row in any closed snapshot and no original provider route |",
        "",
        "The four missing records are cmt-38, cmt-39, cmt-41 and cmt-42. Snapshot task states total 228 done, 26 failed and 4 claimed. Terminal state does not establish a unified final score. The JSON report includes schedule IDs, creation/deadline metadata and classifications, without answer, ground truth or authentication fields.",
        "",
        f"All 10948 original provider gzip files (5476 requests, 5472 responses; {report['providerGzip']['compressedBytes']} compressed bytes) were inventoried. Every gzip reached verified EOF/CRC and its raw SHA matched the original ledger. The complete compressed SHA list and all original SHA/size/mtime before/after comparisons are in JSON. All 263 original metadata JSON files and the frozen-source ZIP remained identical.",
        "",
        f"Only the approved copied SQLite files were opened with mode=ro and query_only, including their copied WAL. Initial snapshot certificate SHA: {SNAPSHOT_SHA}. Main DB and WAL copy bytes match the initial certificate and stayed unchanged. Copied SHM initial/current hashes are recorded separately because earlier authorized metadata probes may already have changed it. Original DB, WAL and SHM were neither opened nor rehashed by this audit.",
        "",
        "No new API/model/grader calls, final scores, network actions, Docker mutations, proof executions or paper changes occurred. Original pending markers and restart guards remain authoritative; this report does not authorize a paid restart.",
        "",
    ]
    json_path = DOC / "scientific-campaign-deferred-fault.json"
    md_path = DOC / "scientific-campaign-deferred-fault.md"
    durable_new_report(json_path, (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    durable_new_report(md_path, "\n".join(md).encode())
    print(json.dumps({"validated": True, "cost": {k: v for k, v in report["cost"].items()
                                              if k not in ("limitation", "ratesPeakUsdPerMillion")},
                      "scheduleCounts": counts, "elapsedSeconds": report["elapsedSeconds"],
                      "json": {"path": str(json_path), **fingerprint(json_path)},
                      "markdown": {"path": str(md_path), **fingerprint(md_path)}}), flush=True)


if __name__ == "__main__":
    main()
