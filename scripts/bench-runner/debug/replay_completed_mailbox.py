"""Read-only replay of an original checker-completion race. Never calls Docker."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--module", required=True)
    cli.add_argument("--ledger", required=True)
    args = cli.parse_args()
    database = sqlite3.connect(Path(args.ledger).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = [json.loads(row[0]) for row in database.execute("select json from command")]
    finally:
        database.close()
    failed = next(row for row in rows if row["index"] == 270)
    before = next(row for row in rows if row["index"] == 269)
    after = next(row for row in rows if row["index"] == 271)

    def text(receipt, stream="stdout"):
        item = receipt[stream]
        raw = Path(item["path"]).read_bytes()
        assert len(raw) == item["bytesStored"]
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        return raw.decode("utf-8")

    checker = failed["argv"][failed["argv"].index("exec") + 1]
    original_before, original_after = json.loads(text(before)), json.loads(text(after))
    assert original_before["Id"] == original_after["Id"] == checker
    assert original_before["State"]["Running"] is True
    assert original_after["State"]["Status"] == "exited"
    assert original_after["State"]["ExitCode"] == 0
    assert original_after["State"]["OOMKilled"] is False
    assert text(failed, "stderr").strip() == "Error response from daemon: container " + checker + " is not running"

    class RecordedNative:
        def command(self, argv, **kwargs):
            assert argv[:2] == ["exec", checker]
            assert argv[-2:] == ["55-1.request.json", "/tmp/pipeline-mailbox"]
            return failed

        def assert_actor(self, cid):
            assert cid == checker
            return original_after

        def text(self, receipt):
            return text(receipt)

        def guard(self):
            pass

    spec = importlib.util.spec_from_file_location("mailbox_under_test", args.module)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix="completed-mailbox-replay-") as output:
        try:
            request, evidence = module.capture_request(RecordedNative(), checker, "55-1.request.json", output, lambda: 30.0)
        except RuntimeError as fault:
            raise AssertionError("Original clean checker completion must not become Stand fatal: " + str(fault)) from fault
        assert request is None
        assert evidence, "Terminal race must retain real command evidence"
    print(json.dumps({"passed": True, "dockerCalls": 0, "modelCalls": 0, "gradeExecutions": 0, "replayedOriginalCommand": 270}))


if __name__ == "__main__":
    main()
