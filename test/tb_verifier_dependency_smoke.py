"""Offline package smoke in a private original-image container; no candidate/GT."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "examples/benchmark/terminal-bench"
os.environ["TGENGIN_TB_VERIFIER_DEPS"] = str(BENCH / ".verifier-deps/uv095-python3137-v1")
SPEC = importlib.util.spec_from_file_location("tb_dependency_smoke", BENCH / "isolated_verifier.py")
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)


def main():
    profile = V.dependency_profile()
    name = "objrun-tb-dependency-smoke-" + uuid.uuid4().hex[:12]
    output = ROOT / "docs/repair-2026-10-08/tb-live-isolation" / ("dependency-smoke-" + uuid.uuid4().hex[:10])
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="public-dependency-smoke-", dir=output) as temporary:
        root = Path(temporary)
        (root / "conftest.py").write_text(V.DEPENDENCY_RECORD, encoding="utf-8")
        (root / "test_public.py").write_text("def test_public_package_smoke():\n assert True\n", encoding="utf-8")
        (root / "uv-env").write_text('export PATH="/root/.local/bin:$PATH"\n', encoding="utf-8")
        command = ("mkdir -p /root/.local/bin /logs/verifier; mv /tmp/uv /root/.local/bin/uv; mv /tmp/uvx /root/.local/bin/uvx; chmod +x /root/.local/bin/uv /root/.local/bin/uvx; "
                   "/root/.local/bin/uvx -p 3.13 -w pytest==8.4.1 -w requests==2.32.4 -w pytest-json-ctrf==0.3.5 pytest /smoke/test_public.py -q")
        created = False
        try:
            V.checked("create", "--pull", "never", "--name", name, "--network", "none", "--cpus", "1", "--memory", "2048m", "--memory-swap", "2048m",
                      *[value for key, value in profile["offlineEnvironment"].items() for value in ("-e", key + "=" + value)], V.IMAGE_ID, "bash", "-c", command)
            created = True
            V.checked("cp", str(V.DEPENDENCIES / "uv"), name + ":/tmp/uv")
            V.checked("cp", str(V.DEPENDENCIES / "uvx"), name + ":/tmp/uvx")
            V.checked("cp", str(V.DEPENDENCIES / "wheels") + "/.", name + ":/verifier-wheels")
            V.checked("cp", str(root) + "/.", name + ":/smoke")
            execution = V.docker("start", "-a", name, timeout=120)
            (output / "stdout.txt").write_text(execution.stdout + execution.stderr, encoding="utf-8")
            if execution.returncode:
                raise RuntimeError("offline package smoke failed: " + execution.stderr[-500:])
            V.checked("cp", name + ":/logs/verifier/dependency-versions.json", str(output / "versions.json"))
            versions = json.loads((output / "versions.json").read_text(encoding="utf-8"))
            assert versions["python"] == profile["python"] and versions["packages"] == profile["packages"], versions
            assert versions["uv"].split()[:2] == ["uv", profile["uv"]], versions
            assert versions["uvSha256"] == next(asset["sha256"] for asset in profile["assets"] if asset["path"] == "uv")
            report = {"validated": True, "scoreProduced": False, "candidateUsed": False, "privateInterpreter": True,
                      "network": "none", "imageId": V.IMAGE_ID, "profileId": profile["profileId"], "manifestSha256": profile["manifestSha256"],
                      "versions": versions, "llmRequests": 0, "imagePulls": False}
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({"validated": True, "report": str(output / "report.json"), "versions": versions}), flush=True)
        finally:
            if created:
                V.checked("rm", "-f", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
