"""Start/check/stop the owned ChemIQ local-OPSIN profile; no image download."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
QUEUE = ROOT / "docs/repair-2026-10-08/legacy-opsin-bridge"
NAME = "objrun-repair-chemiq-local-opsin"


def name_of(length_policy):
    return NAME if length_policy == "official-parsed" else NAME + "-raw-length"


def health(port, length_policy=None):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as response:
        record = json.load(response)
    if not record.get("ok") or record.get("opsin", {}).get("profile") != "local-2.8" or record["opsin"].get("rest_fallback") is not False:
        raise ValueError("Local ChemIQ health/profile mismatch")
    if length_policy is not None and record.get("length_policy", "official-parsed") != length_policy:
        raise ValueError("ChemIQ length policy mismatch")
    return record


def start(port, length_policy):
    status = json.loads((QUEUE / "status.json").read_text(encoding="utf-8"))
    if status.get("stopped") or time.time() - status["heartbeat"] > 30:
        raise RuntimeError("Start the local Java bridge before the grader")
    image = subprocess.run(["docker", "image", "inspect", "objrun-scicode:phase1", "--format", "{{.Id}}"], text=True, capture_output=True, check=True).stdout.strip()
    name = name_of(length_policy)
    command = ["docker", "run", "-d", "--name", name, "--label", "tgengin.repair-profile=local-opsin-2.8", "--label", "tgengin.chemiq-length-policy=" + length_policy, "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "1g", "--cpus", "2", "--pids-limit", "128", "--tmpfs", "/tmp:rw,nosuid,size=128m", "-p", f"127.0.0.1:{port}:{port}"]
    for source, target, readonly in [(ROOT / "examples/benchmark/chemiq/stand.py", "/app/chemiq/stand.py", True),
        (ROOT / ".phase1-data/chemiq", "/oracle", True), (ROOT / ".phase1-data/python-extras", "/extras", True), (QUEUE, "/opsin-jobs", False)]:
        command += ["--mount", f"type=bind,source={source},target={target}" + (",readonly" if readonly else "")]
    command += ["-e", "PYTHONPATH=/extras", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "TGENGIN_CHEMIQ_HOME=/oracle", "-e", "TGENGIN_CHEMIQ_OPSIN_PROFILE=local-2.8", "-e", "TGENGIN_CHEMIQ_OPSIN_JOBS=/opsin-jobs", "-e", "TGENGIN_CHEMIQ_LENGTH_POLICY=" + length_policy, image,
        "python", "/app/chemiq/stand.py", "--port", str(port), "--bind", "0.0.0.0", "--level", "0"]
    container = subprocess.run(command, text=True, capture_output=True, check=True).stdout.strip()
    deadline = time.monotonic() + 20
    while True:
        try:
            record = health(port, length_policy)
            break
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)
    manifest = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "container": name, "container_id": container, "image_id": image, "host_bridge_pid": status["pid"], "port": port, "health": record, "command": command,
        "adapter_sha256": hashlib.sha256((ROOT / "examples/benchmark/chemiq/stand.py").read_bytes()).hexdigest(), "wrapper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "external_candidate_transmission": "prohibited: local profile blocks requests.get before any REST call; queue and host Java are on this machine", "network": "HTTP published on host loopback only; no REST scoring fallback"}
    file = "legacy-chemiq-local-profile-service.json" if length_policy == "official-parsed" else "legacy-chemiq-local-profile-raw-length-service.json"
    (ROOT / "docs/repair-2026-10-08" / file).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "health", "stop"])
    parser.add_argument("--port", type=int, default=17917)
    parser.add_argument("--length-policy", choices=["official-parsed", "raw-input-length"], default="official-parsed")
    options = parser.parse_args()
    if options.action == "start":
        start(options.port, options.length_policy)
    elif options.action == "health":
        print(json.dumps(health(options.port, options.length_policy)))
    else:
        subprocess.run(["docker", "rm", "-f", name_of(options.length_policy)], check=True)
