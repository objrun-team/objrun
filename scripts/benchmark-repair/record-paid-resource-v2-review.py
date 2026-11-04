"""F-only closure of already completed controls. No API, lock, or model execution."""
from pathlib import Path
import datetime
import difflib
import gzip
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/repair-2026-10-08"
AREA = DOCS / "paid-resource-admission-v2-controls"

def pin(path):
    path = Path(path)
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

def write(path, value):
    Path(path).write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())

def main():
    hashes = {
        "paid-resource-admission-v2.ts": "1df00c4ad085014530cd9ff1d73730490867724acc54af3bd3966e4b400d48b5",
        "cny-cash-shadow-v2.ts": "6ad11d7b32b8aee895e620306107cd7864fd35c5413ab5aa3e13b8966338f334",
        "paid-resource-proof-v2.ts": "b1bacd465d2a76ca166e8048ac8ee83f152f6b9f21600770b39ec6a9864813fe",
        "paid-resource-admission-v2-abi.d.ts": "cc507bb41dc1d7d20ee2bbf4859d94dc787203738470c66424bd956610fa194e",
    }
    sources = [pin(ROOT / "scripts/benchmark-repair" / name) for name in hashes]
    for item in sources:
        assert item["sha256"] == hashes[Path(item["path"]).name]
    test = pin(ROOT / "test/benchmarks/paid-resource-admission-v2.test.ts")
    assert test["sha256"] == "26d5a92bfd2aabc5d87166023672ce724b77e50bd8f6ee7accaa4beebc90fa11"
    unchanged = []
    for name, expected in {
        "paid-campaign-lock.ts": "54f7092a7a4559c1fd97636cd51c89b241b4a5af6cc738284ccd009c50b4d9a2",
        "campaign-journal.ts": "139a28eadf4fd570c04796430a419bfbba6ec0cc8d14eb28c2a4ef480cc90a56",
        "campaign-contract.ts": "8ddbc1428a470ca18e5f6605f2bb48eccabc1bb5140ac777879601e4aec66305",
    }.items():
        item = pin(ROOT / "scripts/benchmark-repair" / name)
        assert item["sha256"] == expected
        unchanged.append(item)
    fault_pin = pin(DOCS / "scientific-campaign-deferred-fault.json")
    assert fault_pin["sha256"] == "b56760e02fc14725c7fede86457f6155cb3aa4fdeefa9001b2248282a1cb0357"
    fault = json.loads(Path(fault_pin["path"]).read_bytes())
    original = [fault_pin]
    for item in fault["identity"]["originalEvidenceFiles"]:
        if Path(item["path"]).name in {"manifest.json", "source.json", "summary.json", "api-ledger.json", "frozen-source.json", "frozen-source.zip"}:
            current = pin(ROOT / item["path"])
            assert current["sha256"] == item["before"]["sha256"] and current["bytes"] == item["before"]["bytes"]
            original.append(current)
    for row in fault["deferredCalls"]:
        current = pin(ROOT / row["requestGzip"]["path"])
        assert current["sha256"] == row["requestGzip"]["sha256"]
        raw = gzip.decompress(Path(current["path"]).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == row["requestGzip"]["rawSha256"]
        original.append(current)
    jpg = DOCS / "jpg-lifecycle-revisions/native-lifecycle-v2-2026-10-08/manifest.json"
    jpg_pin = pin(jpg)
    assert jpg_pin["sha256"] == "16bcc22d4f912124aa93c7958f887a8b647603f4dc2c62f04f1b142808fa6c8b"
    for entry in json.loads(jpg.read_bytes())["sources"]:
        assert pin(ROOT / entry["path"])["sha256"] == entry["sha256"]
    unchanged.append(jpg_pin)
    base_log = (AREA / "run-30.stderr.txt").read_text()
    delta_log = (AREA / "final-scanner-delta.stderr.txt").read_text()
    retry_log = (AREA / "fullraw-timeout-corrected.stderr.txt").read_text()
    assert "30 pass" in base_log and "0 fail" in base_log and "131 expect()" in base_log
    assert "6 pass" in delta_log and "1 fail" in delta_log and "timed out after 5000ms" in delta_log
    assert "1 pass" in retry_log and "0 fail" in retry_log and "2 expect()" in retry_log
    raw_scan = {"protocol": "paid-resource-v2-recorded-readonly-root-scan-v1", "sourcePins": sources,
                "scopeCount": 9, "rootScanValid": True, "elapsedMs": 48636,
                "productionLockAcquired": False, "modelCalls": 0,
                "evidenceOrigin": "Completed tools.exec_command Bun -e scanOtherPaidRuns(process.cwd(), read-only-factory-check); final session 66643 exited 0. This recorder does not rerun the scan.",
                "schemaMatrixPin": pin(AREA / "existing-schema-matrix.json")}
    write(AREA / "root-scan-result.json", raw_scan)
    frozen = AREA / "final-sources"
    frozen.mkdir(exist_ok=True)
    archived = []
    for item in [*sources, test]:
        target = frozen / (Path(item["path"]).name + ".snapshot")
        raw = Path(item["path"]).read_bytes()
        if target.exists():
            assert target.read_bytes() == raw
        else:
            target.write_bytes(raw)
        archived.append({**item, "snapshotPin": pin(target)})
    before = AREA / "pre-legacy-compat-v2/scripts__repair-2026-10-08__paid-resource-admission-v2.ts.snapshot"
    after = ROOT / "scripts/benchmark-repair/paid-resource-admission-v2.ts"
    diff = "".join(difflib.unified_diff(before.read_text().splitlines(True), after.read_text().splitlines(True), fromfile="0038-preserved-factory", tofile="1df0-final-factory"))
    (AREA / "scanner-compatibility.diff").write_bytes(diff.encode())
    outputs = [pin(AREA / name) for name in ["run-30.stdout.txt", "run-30.stderr.txt", "final-scanner-delta.stdout.txt", "final-scanner-delta.stderr.txt", "fullraw-timeout-corrected.stdout.txt", "fullraw-timeout-corrected.stderr.txt", "final-process-observation.json", "existing-schema-matrix.json", "root-scan-result.json", "scanner-compatibility.diff"]]
    report = {"protocol": "paid-resource-admission-v2-implementation-review-v1", "recordedAtUtc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "validatedStoredControls": True, "paidReady": False, "mode": "carry-science-oom-2026-10-08-v2",
              "sources": sources, "testSource": test, "sourceSnapshots": archived,
              "preservedOriginalEvidence": original, "unchangedProtectedSources": unchanged,
              "controls": [{"scope": "preserved 0038 factory, identical final cash/proof", "passed": 30, "failed": 0, "assertions": 131, "pid": 93820},
                           {"scope": "1df0 scanner/source-closure delta", "passed": 6, "failed": 1, "failure": "full old-raw scan exceeded Bun default 5s timeout; original invalid run retained", "assertions": 29, "pid": 104688},
                           {"scope": "same sole fullraw behavior with explicit 120s test timeout", "passed": 1, "failed": 0, "assertions": 2, "pid": 97000, "elapsedMs": 12330}],
              "localEvidenceLimits": {"externalModelCalls": 0, "networkCalls": 0, "dockerCalls": 0, "productionLockAcquired": False,
                                      "unitPidObservationsInjected": True, "unitAuditorReportsSyntheticFixtureOnly": True,
                                      "nativePidObservationPin": pin(AREA / "final-process-observation.json")},
              "productionReadOnlyScanner": raw_scan, "outputs": outputs,
              "responsibility": {"originalPendingCount": 4, "originalPendingPositions": [5470, 5471, 5473, 5475], "originalSettled": False,
                                 "originalUsdReserve": "1.258827", "carriedPeakCnyEstimate": "8.39218", "operatorHeadroomCny": "30",
                                 "oldBalanceSnapshotCny": "300.54", "oldSnapshotFutureEnvelopeCny": "262.14782", "oldBalanceIsFreshAdmissionEvidence": False,
                                 "actualBillingKnown": False, "foreignExchangeConversion": False},
              "admission": {"balancePin": "Explicit fresh GET-only v1 schema/source/CNY available pin, age <=30min at startup; never hardcoded to f444 or automatically fetched/refreshed",
                            "pricePin": "8c7942... fixed profile age <=24h at startup and each real beforeForward",
                            "selectedEnvelope": "Mandatory explicit recipe amount; no actual paid amount selected by this report",
                            "canonicalLock": ".phase1-data/owned-paid-campaign.lock.json wx + ownerNonce; no stale takeover",
                            "durability": "Exact frozen 139a journal start prefix+request gzip bytes/CRC/raw/compressed SHA+sequence, independent fsync of request/prefix/checkpoint and cash append/fsync/readback before forward",
                            "finish": "Full HTTP200 + no source fault + completionValid + exact raw usage/model; high CNY interval rate until actual durable capture/host time. Partial/HTTP500/missing usage retains max peak liability. Genuine inflight receipts retained after global poison.",
                            "release": "Exact source/raw/owner/cash Pins, fresh registered worker+original PID absence, independent cash+peer journal replay with zero new pending/unknown, real original+extra scientific score audit reports and matching final summary Pins"},
              "remainingConditions": ["Root and independent source review, new actual four-engine integration and mandatory auditor graph before paid startup",
                                      "Root must obtain a genuinely fresh balance pin and choose/freeze explicit recipe envelope; no new production API/lock was exercised here",
                                      "Formal release requires two scientific score certificates. A budget-only partial stop retains lock pending a separately reviewed financial-only abort contract; it cannot be called a whole score.",
                                      "F-only test failures preserve their own synthetic locks/files, not the production lock. No cleanup or relocation was performed.",
                                      "Historical no-raw 4/847-call exceptions certify only exact stored known USD fee metadata, not original wire, body completion or a CNY invoice. Two old full-raw schemas get absent-attempt compatibility only under exact metadata pins and every real wire/response check.",
                                      "Two historical empty scaffolds require exact ID and both directories completely empty. Empty markers do not certify zero historical calls; any new unknown empty/nonempty scope is refused.",
                                      "Cash historical-state summation remains O(N^2) CPU; cash metadata cap 256MiB, JSON pin cap 128MiB, request raw 4MiB, response raw 64MiB. No full ChemIQ816 scalability claim; future scale changes need another source version without shrinking denominators.",
                                      "Original fault statement paidRestartPermittedByThisReport=false remains unchanged; explicit new root-authorized policy carries responsibility instead of settling unknowns."],
              "reviewRecorder": pin(__file__)}
    write(DOCS / "paid-resource-admission-v2-review.json", report)
    print(json.dumps({"reportPin": pin(DOCS / "paid-resource-admission-v2-review.json"), "actualScanPin": pin(AREA / "root-scan-result.json"), "validatedStoredControls": True, "paidReady": False}))

if __name__ == "__main__":
    main()
