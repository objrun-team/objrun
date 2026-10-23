"""Host Java OPSIN 2.8 file-queue bridge. Contains no HTTP or network client."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
JAR = ROOT / ".phase1-data/opsin/opsin-cli-2.8.0-jar-with-dependencies.jar"
SHA = "d25bc08f41b8f6fcd6f35e18ab83f3b8d9218cdb003d55c5f74aaefe2e0c68ab"
DEFAULT_QUEUE = ROOT / "docs/repair-2026-10-08/legacy-opsin-bridge"


def atomic(path, value):
    staging = path.with_suffix(path.suffix + ".tmp")
    staging.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    # Windows/Docker bind readers briefly hold files without delete sharing.
    # Retrying the atomic rename preserves whole-JSON reads without killing the
    # bridge when a health check races a heartbeat write.
    deadline = time.monotonic() + 3
    while True:
        try:
            staging.replace(path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.02)


def main(queue):
    queue = queue.resolve()
    # All bridge writes must stay in the dedicated, named workspace queue.
    if queue != DEFAULT_QUEUE.resolve():
        raise ValueError("Unsupported bridge queue; use the owned legacy-opsin-bridge directory")
    if hashlib.sha256(JAR.read_bytes()).hexdigest() != SHA:
        raise ValueError("Pinned official OPSIN JAR digest mismatch")
    java = shutil.which("java")
    if not java:
        raise RuntimeError("Java unavailable")
    queue.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for key in ["JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"]:
        env.pop(key, None)
    java_version = subprocess.run([java, "-version"], capture_output=True, text=True, encoding="utf-8", env=env, check=True, timeout=20)
    profile = {"profile": "local-2.8", "version": "2.8.0", "jar_sha256": SHA,
        "cache_origin": "local OPSIN 2.8 only; fixed REST cache is not used for grading", "rest_fallback": False,
        "transport": "local filesystem queue", "external_requests": 0, "java_version": (java_version.stdout + java_version.stderr).strip()}
    atomic(queue / "profile.json", profile)
    completed, failed = 0, 0
    cache = {}
    heartbeat_at = 0
    while not (queue / "stop").exists():
        if time.monotonic() - heartbeat_at > 0.5:
            atomic(queue / "status.json", {"pid": os.getpid(), "heartbeat": time.time(), "completed": completed, "failed": failed, "external_requests": 0})
            heartbeat_at = time.monotonic()
        for request in sorted(queue.glob("*.request.json")):
            match = re.fullmatch(r"([0-9a-f]{32})\.request\.json", request.name)
            if not match:
                continue
            job = match[1]
            response_path = queue / f"{job}.response.json"
            if response_path.exists():
                continue
            started = time.monotonic()
            response = {"id": job, "profile": "local-2.8", "version": "2.8.0", "jar_sha256": SHA, "external_requests": 0}
            try:
                payload = json.loads(request.read_text(encoding="utf-8"))
                name = payload.get("name")
                if payload.get("id") != job or not isinstance(name, str) or not name or len(name) > 200 or "\n" in name or "\r" in name:
                    raise ValueError("Invalid bridge request")
                if name in cache:
                    smiles = cache[name]
                    response["cache_hit"] = True
                else:
                    inp, out = queue / f"{job}.name.txt", queue / f"{job}.smiles.txt"
                    inp.write_text(name + "\n", encoding="utf-8")
                    result = subprocess.run([java, "-Xmx256m", "-Dfile.encoding=UTF-8", "-Djava.net.useSystemProxies=false", "-jar", str(JAR), "-osmi", str(inp), str(out)],
                        capture_output=True, text=True, encoding="utf-8", env=env, timeout=12)
                    (queue / f"{job}.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
                    if result.returncode:
                        raise RuntimeError("OPSIN CLI nonzero exit")
                    lines = out.read_text(encoding="utf-8").splitlines()
                    if len(lines) != 1:
                        raise ValueError("OPSIN CLI output did not preserve one-line protocol")
                    smiles = lines[0]
                    cache[name] = smiles
                    response["cache_hit"] = False
                response.update({"valid": True, "recognized": bool(smiles), "smiles": smiles})
            except Exception as error:
                failed += 1
                response.update({"valid": False, "error": type(error).__name__, "smiles": None})
            completed += 1
            response["elapsed_seconds"] = round(time.monotonic() - started, 4)
            atomic(response_path, response)
        time.sleep(0.02)
    atomic(queue / "status.json", {"pid": os.getpid(), "stopped": True, "heartbeat": time.time(), "completed": completed, "failed": failed, "external_requests": 0})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    main(parser.parse_args().queue)
