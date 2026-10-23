"""Trusted offline checker entry. Never installed in a solving/worker island."""
import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import sqlite3
import subprocess
import sys
import time


def install_openssl_worker_result(path):
    """Only the exact original script command is delegated to an untrusted island.

    Certificate parsing commands still run the frozen checker image's OpenSSL.
    The candidate script is never imported or executed by this checker.
    """
    result = json.loads(Path(path).read_bytes())
    assert result["protocol"] == "tb12-openssl-untrusted-worker-result-v1"
    assert isinstance(result["exitCode"], int)
    assert all(isinstance(result[key], str) and len(result[key].encode()) <= 1024 ** 2 for key in ("stdout", "stderr"))
    original = subprocess.run
    commands = {
        ("openssl", "rsa", "-in", "/app/ssl/server.key", "-text", "-noout"),
        ("openssl", "x509", "-in", "/app/ssl/server.crt", "-text", "-noout"),
        ("openssl", "x509", "-in", "/app/ssl/server.crt", "-noout", "-dates"),
        ("openssl", "x509", "-in", "/app/ssl/server.pem", "-text", "-noout"),
    }

    def run(argv, *args, **kwargs):
        if args or set(kwargs) != {"capture_output", "text"} or not kwargs["capture_output"] or not kwargs["text"]:
            raise RuntimeError("Unexpected official subprocess interface")
        if tuple(argv) == ("python", "/app/check_cert.py"):
            if result.get("encodingError"):
                error = result["encodingError"]
                raise UnicodeDecodeError(error["encoding"], base64.b64decode(error["objectBase64"], validate=True),
                                         error["start"], error["end"], error["reason"])
            return subprocess.CompletedProcess(argv, result["exitCode"], result["stdout"], result["stderr"])
        if tuple(argv) not in commands:
            raise RuntimeError("Command outside the frozen official OpenSSL interface")
        return original(argv, **kwargs, timeout=30)

    subprocess.run = run


def install_sqlite_guard():
    """Keep the original benchmark queries and PRAGMAs, prohibit mutation/extension.

    SQLite's read-only open and an authorizer protect both the pristine fixture
    and the candidate query. No candidate Python code or custom SQLite UDF runs.
    """
    original = sqlite3.connect
    blocked = {getattr(sqlite3, name) for name in (
        "SQLITE_CREATE_INDEX", "SQLITE_CREATE_TABLE", "SQLITE_CREATE_TEMP_INDEX",
        "SQLITE_CREATE_TEMP_TABLE", "SQLITE_CREATE_TEMP_TRIGGER", "SQLITE_CREATE_TEMP_VIEW",
        "SQLITE_CREATE_TRIGGER", "SQLITE_CREATE_VIEW", "SQLITE_DELETE", "SQLITE_DROP_INDEX",
        "SQLITE_DROP_TABLE", "SQLITE_DROP_TEMP_INDEX", "SQLITE_DROP_TEMP_TABLE",
        "SQLITE_DROP_TEMP_TRIGGER", "SQLITE_DROP_TEMP_VIEW", "SQLITE_DROP_TRIGGER",
        "SQLITE_DROP_VIEW", "SQLITE_INSERT", "SQLITE_UPDATE", "SQLITE_ATTACH",
        "SQLITE_DETACH", "SQLITE_ALTER_TABLE", "SQLITE_REINDEX", "SQLITE_ANALYZE",
        "SQLITE_CREATE_VTABLE", "SQLITE_DROP_VTABLE",
    )}
    allowed_pragmas = {("temp_store", "MEMORY"), ("cache_size", "-100000"), ("case_sensitive_like", "OFF"), ("optimize", None)}

    def authorize(action, first, second, database, trigger):
        if action in blocked:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and str(second).lower() in {"load_extension", "readfile", "writefile"}:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_PRAGMA and (str(first).lower(), str(second).upper() if second is not None else None) not in allowed_pragmas:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def connect(database, *args, **kwargs):
        if str(database) != "file:/app/oewn.sqlite?mode=ro" or kwargs.get("uri") is not True:
            raise RuntimeError("SQLite open outside the read-only original fixture")
        connection = original(database, *args, **kwargs)
        connection.enable_load_extension(False)
        connection.set_authorizer(authorize)
        return connection

    sqlite3.connect = connect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_bytes())
    assert config["protocol"] == "tb12-private-checker-config-v1"
    if "checkerSourceSha256" in config:
        assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == config["checkerSourceSha256"]
    task_id = config["taskId"]
    start_wall, start_mono = time.time(), time.monotonic()
    assert sys.version_info[:3] == (3, 13, 7)
    limit = int(config["verifierSeconds"])
    assert 0 < limit <= 3600
    resource.setrlimit(resource.RLIMIT_CPU, (limit, limit + 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    import pytest
    versions = {name: importlib.metadata.version(name) for name in config["packages"] if name != "chess"}
    for name, expected in config["packages"].items():
        if name != "chess":
            assert versions[name] == expected, (name, versions[name], expected)
    import chess
    assert chess.__version__ == config["packages"]["chess"]
    versions["chess"] = chess.__version__
    for name, expected in config["officialTestHashes"].items():
        path = Path("/tests") / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name
    if not args.collect_only:
        if task_id == "openssl-selfsigned-cert":
            install_openssl_worker_result("/opt/tb12/worker-result.json")
        elif task_id == "query-optimize":
            install_sqlite_guard()
        elif task_id == "nginx-request-logging":
            from nginx_client import install
            install()
    target = "/tmp/ctrf.json"
    command = ["-p", "ctrf.main", "--ctrf", target, "/tests/test_outputs.py", "-rA", "-o", "cache_dir=/tmp/pytest-cache"]
    if args.collect_only:
        command.insert(0, "--collect-only")
    exit_code = int(pytest.main(command))
    raw = Path(target).read_bytes() if Path(target).exists() else b""
    if len(raw) > 2 * 1024 ** 2:
        raise RuntimeError("CTRF receipt exceeded frozen capture boundary")
    ctrf = json.loads(raw) if raw else None
    assert not Path("/tmp/isolation-fault.json").exists(), "Private adapter transport fault"
    result = {"protocol": "tb12-private-checker-result-v1", "invocationId": config["invocationId"], "taskId": task_id, "collectOnly": args.collect_only, "exitCode": exit_code, "reward": int(exit_code == 0 and not args.collect_only), "ctrf": ctrf, "ctrfRawSha256": hashlib.sha256(raw).hexdigest(), "pythonVersion": sys.version, "pythonExecutable": sys.executable, "pythonExecutableSha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(), "checkerSourceSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "numericGuestPid": os.getpid(), "numericParentPid": os.getppid(), "procStatus": Path("/proc/self/status").read_text(), "mountInfoSha256": hashlib.sha256(Path("/proc/self/mountinfo").read_bytes()).hexdigest(), "packages": versions, "privateNamespaces": {name: os.readlink("/proc/self/ns/" + name) for name in ("pid", "mnt", "net")}, "wallStart": start_wall, "wallStop": time.time(), "monotonicSeconds": time.monotonic() - start_mono}
    # Final frame comes from trusted code after pytest; worker output remains JSON
    # string data. Host requires this final frame, invocation ID and actual exit.
    print("TB12_RESULT:" + json.dumps(result, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
