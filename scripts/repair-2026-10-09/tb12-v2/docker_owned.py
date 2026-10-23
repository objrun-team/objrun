"""Bounded Docker transport with actual native exits and nonce/CID ownership.

No global prune/restart, image pulls, guessed-name deletions or paid-lock writes.
The command receipts contain only safe argv, never secret environment values.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid

from profiles import FAMILY, MAX_STREAM, MIN_HOST_C_FREE, MIN_HOST_F_FREE

ROOT = Path(__file__).resolve().parents[3]
DOCKER = r"D:\Program\resources\bin\docker.exe"
INSPECT = '{"Id":{{json .Id}},"Image":{{json .Image}},"Name":{{json .Name}},"State":{{json .State}},"HostConfig":{{json .HostConfig}},"Mounts":{{json .Mounts}},"Labels":{{json .Config.Labels}}}'


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 ** 2):
            value.update(chunk)
    return value.hexdigest()


class NativeFault(RuntimeError):
    def __init__(self, message, receipt):
        super().__init__(message)
        self.receipt = receipt


class OwnedDocker:
    def __init__(self, directory, nonce=None):
        self.directory = Path(directory).resolve()
        assert self.directory.is_relative_to(ROOT / "docs/repair-2026-10-09/tb12-preparation-v1") or self.directory.is_relative_to(ROOT / "docs/repair-2026-10-09/tb12-runs-v1")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.nonce = nonce or uuid.uuid4().hex
        assert re.fullmatch(r"[a-f0-9]{32}", self.nonce)
        self.source_sha = sha(Path(__file__))
        self.receipts = self.directory / "native-receipts"
        self.receipts.mkdir(exist_ok=True)
        self.database = self.directory / "owned-native.sqlite"
        self.db = sqlite3.connect(self.database, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS command(id INTEGER PRIMARY KEY, json TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS actor(cid TEXT PRIMARY KEY, role TEXT NOT NULL, name TEXT NOT NULL, image TEXT NOT NULL, closed INTEGER NOT NULL DEFAULT 0, json TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS image(id TEXT PRIMARY KEY, tag TEXT NOT NULL, json TEXT NOT NULL)")
        self.db.commit()
        self.lock = threading.RLock()

    def guard(self):
        assert sha(Path(__file__)) == self.source_sha, "Owned native source changed"
        observations = {drive: shutil.disk_usage(drive).free for drive in ("C:/", "F:/")}
        if observations["C:/"] < MIN_HOST_C_FREE or observations["F:/"] < MIN_HOST_F_FREE:
            raise RuntimeError("Observed host disk guard blocks new Docker activity: " + json.dumps(observations))
        return observations

    def command(self, args, timeout=60, stdout_limit=MAX_STREAM, environment=None, stdin=None):
        assert args[0] in {"version", "image", "ps", "pull", "create", "inspect", "start", "stop", "wait", "cp", "exec", "pause", "unpause", "commit", "rm"}
        assert args[0] != "image" or args[1] in {"inspect", "rm", "tag"}
        if args[0] == "pull" or args[:2] == ["image", "tag"]:
            public_path = ROOT / "docs/repair-2026-10-08/tb-twelve-public-image-pulls-fd2e444e83ca407ebc1e172e10b16ac8/images.json"
            assert sha(public_path) == "f0f8e6419d55ff395725125a3c709d190368e494c1e2e33aa5b14fb238b0fc4b"
            public = json.loads(public_path.read_bytes())["records"]
            if args[0] == "pull":
                assert len(args) == 2 and args[1] in {digest for row in public for digest in row["repoDigests"]}
            else:
                assert len(args) == 4 and args[2] in {row["immutableImageId"] for row in public}
                assert re.fullmatch("objrun/tb12-public-cache:" + self.nonce + "-[a-z0-9-]+", args[3])
        assert not any(value in {"prune", "restart", "--privileged", "--volumes-from", "--pid=host", "--network=host"} for value in args)
        with self.lock:
            index = self.db.execute("SELECT COALESCE(MAX(id),-1)+1 FROM command").fetchone()[0]
            prefix = self.receipts / f"command-{index:06d}"
            started, monotonic = datetime.now(timezone.utc).isoformat(), time.monotonic()
            record = {"protocol": "tb12-owned-native-command-v1", "family": FAMILY, "ownerNonce": self.nonce, "sourceSha256": self.source_sha, "index": index, "argv": [DOCKER, "--host", "npipe:////./pipe/dockerDesktopLinuxEngine", *args], "startedAtUtc": started, "nativePid": None, "exitCode": None, "closeObserved": False}
            self.db.execute("INSERT INTO command(id,json) VALUES(?,?)", (index, json.dumps(record)))
            self.db.commit()
        process = subprocess.Popen(record["argv"], stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
        record["nativePid"] = process.pid
        paths = [Path(str(prefix) + ".stdout"), Path(str(prefix) + ".stderr")]
        bounds = [stdout_limit, MAX_STREAM]
        totals, stored = [0, 0], [0, 0]
        overflow = threading.Event()
        faults = []

        def drain(stream, number):
            try:
                with paths[number].open("xb") as target:
                    while chunk := stream.read(65536):
                        totals[number] += len(chunk)
                        available = max(0, bounds[number] - stored[number])
                        target.write(chunk[:available])
                        stored[number] += min(available, len(chunk))
                        if len(chunk) > available:
                            overflow.set()
            except BaseException as error:
                faults.append(type(error).__name__)
                overflow.set()

        threads = [threading.Thread(target=drain, args=(stream, number), daemon=True) for number, stream in enumerate((process.stdout, process.stderr))]
        for thread in threads:
            thread.start()
        def write_input():
            try:
                process.stdin.write(stdin)
                process.stdin.close()
            except BaseException as error:
                faults.append("stdin:" + type(error).__name__)
                overflow.set()
        writer = None
        if stdin is not None:
            writer = threading.Thread(target=write_input, daemon=True)
            writer.start()
        timed_out = False
        try:
            while process.poll() is None:
                if overflow.is_set() or time.monotonic() - monotonic > timeout:
                    timed_out = time.monotonic() - monotonic > timeout
                    process.kill()
                    break
                time.sleep(0.02)
            code = process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            for thread in threads:
                thread.join(timeout=10)
            if writer is not None:
                writer.join(timeout=10)
            for stream in (process.stdout, process.stderr):
                stream.close()
        record.update({"exitCode": code, "closeObserved": all(not thread.is_alive() for thread in threads) and (writer is None or not writer.is_alive()), "timedOut": timed_out, "overflow": overflow.is_set(), "captureFaults": faults, "finishedAtUtc": datetime.now(timezone.utc).isoformat(), "monotonicSeconds": time.monotonic() - monotonic, "stdout": {"path": str(paths[0]), "bytesObserved": totals[0], "bytesStored": stored[0], "sha256": sha(paths[0])}, "stderr": {"path": str(paths[1]), "bytesObserved": totals[1], "bytesStored": stored[1], "sha256": sha(paths[1])}})
        with self.lock:
            self.db.execute("UPDATE command SET json=? WHERE id=?", (json.dumps(record), index))
            self.db.commit()
        if overflow.is_set() or faults or not record["closeObserved"] or timed_out:
            raise NativeFault("Native command capture/timeout failure", record)
        return record

    def checked(self, args, **kwargs):
        receipt = self.command(args, **kwargs)
        if receipt["exitCode"] != 0:
            raise NativeFault("Native command returned a nonzero exit", receipt)
        return receipt

    def text(self, receipt):
        return Path(receipt["stdout"]["path"]).read_text(encoding="utf-8").strip()

    def inspect(self, cid):
        assert re.fullmatch(r"[a-f0-9]{64}", cid)
        return json.loads(self.text(self.checked(["inspect", "--format", INSPECT, cid])))

    def writable_size(self, cid):
        self.assert_actor(cid)
        receipt = self.checked(["inspect", "--size", "--format", "{{json .SizeRw}}", cid], timeout=120)
        value = json.loads(self.text(receipt))
        assert isinstance(value, int) and value >= 0
        return value, receipt

    def assert_actor(self, cid):
        with self.lock:
            row = self.db.execute("SELECT role,name,image,closed FROM actor WHERE cid=?", (cid,)).fetchone()
        assert row and row[3] == 0, "Unknown or closed actor"
        actual = self.inspect(cid)
        labels = actual["Labels"]
        assert actual["Id"] == cid and actual["Name"].lstrip("/") == row[1]
        assert labels.get("objrun.tb12.owner") == self.nonce and labels.get("objrun.tb12.role") == row[0]
        assert labels.get("objrun.tb12.native-source") == self.source_sha
        assert not actual["HostConfig"].get("Binds")
        assert all(mount["Type"] == "tmpfs" and mount["Destination"] == "/tmp" for mount in actual["Mounts"])
        return actual

    def create(self, role, image, executable, arguments, network="none", memory_mb=2048, cpus=1, readonly=False, env_names=(), environment=None, drop_capabilities=True, storage_mb=None):
        self.guard()
        assert re.fullmatch(r"[a-z0-9-]+", role)
        assert re.fullmatch(r"sha256:[a-f0-9]{64}", image)
        assert network in {"none", "bridge"} or re.fullmatch(r"container:[a-f0-9]{64}", network)
        with self.lock:
            number = self.db.execute("SELECT COUNT(*) FROM actor").fetchone()[0]
        name = f"tb12-{self.nonce[:12]}-{role}-{number}"
        args = ["create", "--pull", "never", "--name", name, "--label", "objrun.tb12.owner=" + self.nonce, "--label", "objrun.tb12.role=" + role, "--label", "objrun.tb12.native-source=" + self.source_sha, "--network", network, "--cpus", str(cpus), "--memory", str(memory_mb) + "m", "--memory-swap", str(memory_mb) + "m", "--pids-limit", "256", "--security-opt", "no-new-privileges=true"]
        if drop_capabilities:
            args += ["--cap-drop", "ALL"]
        if storage_mb is not None:
            assert storage_mb == 10240
            args += ["--storage-opt", "size=10240m"]
        if readonly:
            args += ["--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777"]
        for key in env_names:
            assert re.fullmatch(r"[A-Z][A-Z0-9_]*", key)
            args += ["--env", key]
        args += ["--entrypoint", executable, image, *arguments]
        receipt = self.checked(args, environment=environment)
        cid = self.text(receipt)
        assert re.fullmatch(r"[a-f0-9]{64}", cid), "Create receipt missing an exact CID; preserve partial scope"
        with self.lock:
            self.db.execute("INSERT INTO actor(cid,role,name,image,json) VALUES(?,?,?,?,?)", (cid, role, name, image, json.dumps({"createReceipt": receipt})))
            self.db.commit()
        actual = self.assert_actor(cid)
        assert actual["Image"] == image and actual["HostConfig"]["NetworkMode"] == network
        assert actual["HostConfig"]["Memory"] == memory_mb * 1024 ** 2 and actual["HostConfig"]["ReadonlyRootfs"] == readonly
        with self.lock:
            self.db.execute("UPDATE actor SET json=? WHERE cid=?", (json.dumps({"createReceipt": receipt, "initialState": actual}), cid))
            self.db.commit()
        return cid, actual, receipt

    def upload(self, source, cid, destination):
        self.guard()
        self.assert_actor(cid)
        source = Path(source).resolve()
        assert source.is_relative_to(ROOT / "docs/repair-2026-10-09")
        assert str(destination).startswith("/") and ".." not in Path(destination).parts
        return self.checked(["cp", str(source), cid + ":" + destination])

    def start(self, cid, attach=False, timeout=60, stdout_limit=MAX_STREAM):
        self.guard()
        self.assert_actor(cid)
        return self.checked(["start", *(["-a"] if attach else []), cid], timeout=timeout, stdout_limit=stdout_limit)

    def stop(self, cid):
        self.assert_actor(cid)
        receipt = self.checked(["stop", "--time", "5", cid], timeout=20)
        assert not self.assert_actor(cid)["State"]["Running"]
        return receipt

    def execute(self, cid, argv, timeout=60):
        self.guard()
        actual = self.assert_actor(cid)
        assert actual["State"]["Running"] and not actual["State"]["Paused"]
        return self.checked(["exec", cid, *argv], timeout=timeout)

    def pause(self, cid):
        actual = self.assert_actor(cid)
        assert actual["State"]["Running"] and not actual["State"]["Paused"]
        receipt = self.checked(["pause", cid])
        assert self.assert_actor(cid)["State"]["Paused"]
        return receipt

    def unpause(self, cid):
        assert self.assert_actor(cid)["State"]["Paused"]
        receipt = self.checked(["unpause", cid])
        assert not self.assert_actor(cid)["State"]["Paused"]
        return receipt

    def commit(self, cid, role):
        self.guard()
        actual = self.assert_actor(cid)
        assert not actual["State"]["Running"] or actual["State"]["Paused"]
        assert re.fullmatch(r"[a-z0-9-]+", role)
        with self.lock:
            number = self.db.execute("SELECT COUNT(*) FROM image").fetchone()[0]
        tag = f"objrun/tb12-{role}:{self.nonce}-{number}"
        receipt = self.checked(["commit", "--no-pause", cid, tag], timeout=300)
        lines = self.text(receipt).splitlines()
        images = [line.strip() for line in lines if re.fullmatch(r"sha256:[a-f0-9]{64}", line.strip())]
        assert len(images) == 1 and lines[-1].strip() == images[0], "Commit output must end with exactly one image ID"
        image = images[0]
        with self.lock:
            self.db.execute("INSERT INTO image(id,tag,json) VALUES(?,?,?)", (image, tag, json.dumps({"sourceContainer": cid, "sourceState": actual, "receipt": receipt})))
            self.db.commit()
        return image, receipt

    def remove(self, cid):
        before = self.assert_actor(cid)
        receipt = self.checked(["rm", "-f", cid])
        absent = self.command(["inspect", "--format", INSPECT, cid])
        text = Path(absent["stderr"]["path"]).read_text(encoding="utf-8").lower()
        assert absent["exitCode"] != 0 and "no such object:" in text and cid in text, "CID absence not proven"
        with self.lock:
            previous = json.loads(self.db.execute("SELECT json FROM actor WHERE cid=?", (cid,)).fetchone()[0])
            previous.update({"beforeRemoval": before, "removalReceipt": receipt, "absenceReceipt": absent})
            self.db.execute("UPDATE actor SET closed=1,json=? WHERE cid=?", (json.dumps(previous), cid))
            self.db.commit()
        return receipt, absent

    def open_actors(self):
        return self.db.execute("SELECT cid,role,name FROM actor WHERE closed=0").fetchall()

    def close(self):
        assert not self.open_actors(), "Owned Docker actors still open"
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.close()
