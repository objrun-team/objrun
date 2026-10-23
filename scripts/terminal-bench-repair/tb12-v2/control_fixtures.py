"""Private model-free controls. These fixtures never enter real candidate runs."""
import ast
import base64
import csv
import gzip
import json
import math
from pathlib import Path
import re
import struct
from datetime import datetime, timedelta

from docker_owned import ROOT, sha


def literal_assignment(source, name):
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError("Missing frozen literal control assignment")


def distribution(positive):
    n, k = 150000, 7
    if not positive:
        return [1 / n] * n
    def values(a):
        c = math.exp(-10) / n
        for _ in range(30):
            b = (1 - a - (n - k) * c) / (k - 1)
            c = math.exp((-n * (10 + math.log(n)) - math.log(a) - (k - 1) * math.log(b)) / (n - k))
        b = (1 - a - (n - k) * c) / (k - 1)
        forward = a * math.log(a) + (k - 1) * b * math.log(b) + (n - k) * c * math.log(c) + math.log(n)
        return forward, a, b, c
    lo, hi = 1 / k, 0.9
    assert values(lo)[0] < 10 < values(hi)[0]
    for _ in range(100):
        middle = (lo + hi) / 2
        if values(middle)[0] < 10:
            lo = middle
        else:
            hi = middle
    forward, a, b, c = values((lo + hi) / 2)
    result = [a] + [b] * (k - 1) + [c] * (n - k)
    assert abs(forward - 10) < 1e-10 and abs(math.fsum(result) - 1) < 1e-12
    return result


def stage_control(task_id, control, output):
    assert control in ("positive", "wrong")
    positive = control == "positive"
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    task_root = ROOT / ".phase1-data/terminal-bench/vendor/terminal-bench-2-1/tasks" / task_id
    original = task_root / "tests/test_outputs.py"
    pins = [{"path": str(original), "sha256": sha(original)}]
    mapping = {}
    def write(name, data):
        target = output / name
        target.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
        mapping["/app/" + name] = str(target)
    if task_id == "chess-best-move":
        write("move.txt", "g2g4 e2e4\n" if positive else "a1a2\n")
    elif task_id == "log-summary-date-ranges":
        rows = literal_assignment(original, "EXPECTED_ROWS")
        if not positive:
            rows[0][2] = "0"
        target = output / "summary.csv"
        with target.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerows([["period", "severity", "count"], *rows])
        mapping["/app/summary.csv"] = str(target)
    elif task_id == "sqlite-db-truncate":
        write("recover.json", literal_assignment(original, "soln") if positive else [])
    elif task_id == "db-wal-recovery":
        names = ["apple", "banana", "cherry", "date", "elderberry", "fig", "grape", "honeydew", "kiwi", "lemon", "mango"]
        data = [{"id": index + 1, "name": name, "value": (150 if index == 0 else 250 if index == 1 else 0)} for index, name in enumerate(names)]
        if not positive:
            data[0]["value"] = 0
        write("recovered.json", data)
    elif task_id == "raman-fitting":
        write("results.json", {"G": {"x0": 1580.3 if positive else 0, "gamma": 9.06, "amplitude": 8382.69, "offset": 5561.03}, "2D": {"x0": 2670.08, "gamma": 17.52, "amplitude": 12314.42, "offset": 1239.09}})
    elif task_id == "distribution-search":
        target = output / "dist.npy"
        header = repr({"descr": "<f8", "fortran_order": False, "shape": (150000,)}).encode("ascii")
        header += b" " * ((64 - ((10 + len(header) + 1) % 64)) % 64) + b"\n"
        with target.open("xb") as stream:
            stream.write(b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header)
            for value in distribution(positive):
                stream.write(struct.pack("<d", value))
        mapping["/app/dist.npy"] = str(target)
    elif task_id == "regex-chess":
        source = task_root / "solution/solve.sh"
        pins.append({"path": str(source), "sha256": sha(source)})
        encoded = re.search(r"echo '([A-Za-z0-9+/=]+)' > solution.b64", source.read_text(encoding="utf-8"))
        assert encoded
        raw = gzip.decompress(base64.b64decode(encoded.group(1), validate=True))
        assert len(raw) <= 16 * 1024 ** 2
        data = json.loads(raw)
        write("re.json", data if positive else [])
    elif task_id == "constraints-scheduling":
        calendars = [(task_root / "environment/inputs" / name).read_text(encoding="utf-8") for name in ("alice_calendar.ics", "bob_calendar.ics", "carol_calendar.ics")]
        busy = []
        for calendar in calendars:
            busy.extend((datetime.strptime(start, "%Y%m%dT%H%M%SZ"), datetime.strptime(stop, "%Y%m%dT%H%M%SZ")) for start, stop in zip(re.findall(r"DTSTART:(\d{8}T\d{6}Z)", calendar), re.findall(r"DTEND:(\d{8}T\d{6}Z)", calendar)))
        instant = datetime(2024, 1, 15, 10)
        while instant < datetime(2024, 1, 20):
            end = instant + timedelta(hours=1)
            lunch = instant.replace(hour=12, minute=0)
            hard = instant.weekday() < 5 and instant.hour >= 10 and end <= instant.replace(hour=14, minute=0) and not (instant < lunch + timedelta(minutes=30) and end > lunch)
            if hard and not any(instant < stop and end > start for start, stop in busy):
                break
            instant += timedelta(minutes=1)
        assert instant < datetime(2024, 1, 20)
        if not positive:
            instant = datetime(2024, 1, 15, 3)
        text = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//TB12 private control//EN\nBEGIN:VEVENT\nUID:tb12-control\nSUMMARY:Team Planning Meeting\n"
        text += "DTSTART:" + instant.strftime("%Y%m%dT%H%M%SZ") + "\nDTEND:" + (instant + timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ") + "\n"
        text += "".join("ATTENDEE:mailto:" + person + "@example.com\n" for person in ("alice", "bob", "carol"))
        write("meeting_scheduled.ics", text + "END:VEVENT\nEND:VCALENDAR\n")
    else:
        raise ValueError("Positive/wrong fixture not implemented for " + task_id)
    (output / "fixture.json").write_text(json.dumps({"protocol": "tb12-private-control-fixture-v1", "taskId": task_id, "control": control, "sourcePins": pins, "files": [{"path": path, "stored": stored, "sha256": sha(Path(stored))} for path, stored in mapping.items()], "realCandidateUseForbidden": True}, indent=2) + "\n", encoding="utf-8")
    return mapping


def install_control(native, cid, task_id, control, output):
    """Reference scripts execute only in model-free candidate control islands."""
    if task_id not in ("openssl-selfsigned-cert", "multi-source-data-merger", "query-optimize", "nginx-request-logging"):
        for destination, source in stage_control(task_id, control, output).items():
            native.upload(source, cid, destination)
        return
    import shutil
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    source = ROOT / ".phase1-data/terminal-bench/vendor/terminal-bench-2-1/tasks" / task_id / "solution/solve.sh"
    frozen = output / "reference-solve.sh"
    shutil.copyfile(source, frozen)
    assert sha(source) == sha(frozen)
    original_sha = sha(frozen)
    native.upload(frozen, cid, "/tmp/tb12-private-reference.sh")
    executed = native.execute(cid, ["/bin/bash", "-c", "cd /app && /bin/bash /tmp/tb12-private-reference.sh"], timeout=600 if task_id == "nginx-request-logging" else 120)
    if control == "wrong":
        if task_id == "openssl-selfsigned-cert":
            native.execute(cid, ["/bin/chmod", "0644", "/app/ssl/server.key"])
        elif task_id == "nginx-request-logging":
            target = output / "wrong.txt"
            target.write_text("Incorrect control page\n", encoding="utf-8")
            native.upload(target, cid, "/var/www/html/index.html")
        else:
            target = output / "wrong.txt"
            target.write_text("{}" if task_id == "multi-source-data-merger" else "SELECT 1;\n", encoding="utf-8")
            native.upload(target, cid, "/app/conflicts.json" if task_id == "multi-source-data-merger" else "/app/sol.sql")
    (output / "fixture.json").write_text(json.dumps({"protocol": "tb12-private-control-reference-v1", "source": str(source), "sourceSha256": original_sha, "executedControlScriptSha256": sha(frozen), "originalInstallerActuallyExecuted": task_id == "nginx-request-logging", "taskId": task_id, "control": control, "executionReceipt": executed, "realCandidateUseForbidden": True}, indent=2) + "\n", encoding="utf-8")
