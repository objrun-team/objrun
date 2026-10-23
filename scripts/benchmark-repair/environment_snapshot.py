"""Record owned grader containers and versions without reading credentials or answers."""
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
slugs = ["gpqa", "cmt", "aime", "chembench", "chemiq"]


def command(args):
    return subprocess.check_output(args, encoding="utf-8", timeout=30).strip()


containers = []
for slug in slugs:
    name = f"objrun-phase1-{slug}"
    raw = json.loads(command(["docker", "inspect", name]))[0]
    versions = json.loads(command(["docker", "exec", name, "python", "-c",
        "import json,platform,importlib.metadata as m; packages=['numpy','sympy','scipy','pandas','rdkit','requests','matplotlib']; "
        "known={d.metadata['Name'].lower():d.version for d in m.distributions()}; versions={p:known[p] for p in packages if p in known}; "
        "print(json.dumps({'python':platform.python_version(),'platform':platform.platform(),'packages':versions}))"]))
    file = ROOT / f"examples/benchmark/{slug}/{'grader.py' if slug == 'cmt' else 'stand.py'}"
    containers.append({"benchmark": slug, "name": name, "containerId": raw["Id"], "imageId": raw["Image"],
        "startedAt": raw["State"]["StartedAt"], "readOnlyRootfs": raw["HostConfig"]["ReadonlyRootfs"],
        "networkMode": raw["HostConfig"]["NetworkMode"], "ports": raw["NetworkSettings"]["Ports"],
        "memoryBytes": raw["HostConfig"]["Memory"], "nanoCpus": raw["HostConfig"]["NanoCpus"],
        "pidsLimit": raw["HostConfig"]["PidsLimit"], "user": raw["Config"]["User"],
        "command": raw["Config"]["Cmd"], "mounts": [{k: item[k] for k in ["Type", "Source", "Destination", "RW"]} for item in raw["Mounts"]],
        "versions": versions, "currentStandFileSha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        "standFileCaveat": "A bind-mounted source is loaded at process start; use the campaign start snapshot for the loaded version, not a later file digest."})
result = {"capturedAt": datetime.now(timezone.utc).isoformat(), "hostPlatform": platform.platform(),
          "bunVersion": command([sys.argv[1] if len(sys.argv) > 1 else "bun", "--version"]), "dockerServerVersion": command(["docker", "version", "--format", "{{.Server.Version}}"]),
          "containers": containers, "limits": ["Scientific solver tools exclude filesystem, execution and network access; a host-loopback binding alone does not certify software task isolation."]}
output = ROOT / "docs/repair-2026-10-08/environment.json"
output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"output": str(output), "containers": len(containers), "imageIds": sorted(set(r["imageId"] for r in containers))}))
