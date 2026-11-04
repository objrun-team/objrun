"""Real authenticated TB stand, frozen MCP tools, and live official grading.

Only the audited cached nginx image is used. No LLM calls or image pulls.
Creates one candidate and sequential private graders; removes its own resources.
"""
import argparse
import hashlib
import importlib.util
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import urllib.error
import urllib.request
import uuid

from tb_live_isolation_probe import SPY

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "examples/benchmark/terminal-bench"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-only", action="store_true", help="final exact-source empty/oracle gate; live-service negative control is recorded separately")
    args = parser.parse_args()
    run_id = "stand-probe-" + uuid.uuid4().hex[:10]
    output = ROOT / "docs/repair-2026-10-08/tb-live-isolation" / run_id
    output.mkdir(parents=True)
    token = secrets.token_urlsafe(32)
    os.environ["TGENGIN_GRADER_TOKEN"] = token
    os.environ["TGENGIN_TB_CORPUS"] = str(ROOT / ".phase1-data/terminal-bench/vendor/terminal-bench-2-1/tasks")
    os.environ["TGENGIN_TB_HOME"] = str(output)
    os.environ["TGENGIN_TB_BACKEND"] = "docker"
    os.environ.pop("TGENGIN_UNSAFE_DIAGNOSTIC", None)
    frozen = {str(file.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(file.read_bytes()).hexdigest()
              for file in [BENCH / "stand.py", BENCH / "isolated_verifier.py", BENCH / "nginx_client.py", ROOT / "examples/benchmark/_lib/grader_status.py"]}
    sys.path.insert(0, str(BENCH))
    spec = importlib.util.spec_from_file_location("tb_stand_probe", BENCH / "stand.py")
    stand = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stand)
    stand.GRADERS, stand.GATE = 1, threading.Semaphore(1)
    stand.LOGS.mkdir(parents=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), stand.Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    place = "tb:" + run_id + "/nginx-request-logging"
    name = stand.container_of(place)
    report = {"runId": run_id, "llmRequests": 0, "imagePulls": False,
              "protocol": stand.isolated_verifier.PROTOCOL, "toolResults": {}, "phases": {}, "sourceHashes": frozen,
              "imageId": stand.isolated_verifier.IMAGE_ID, "officialSourceHashes": stand.isolated_verifier.SOURCE_HASHES,
              "runtimeManifestSha256": hashlib.sha256((BENCH / ".runtime/manifest.json").read_bytes()).hexdigest(),
              "validationScope": "final_frozen_empty_oracle" if args.gate_only else "empty_oracle_service_negative",
              "officialGradingValid": False}
    profile = stand.isolated_verifier.dependency_profile()
    if profile:
        report["dependencyProfile"] = {"id": profile["profileId"], "manifestSha256": profile["manifestSha256"]}
        report["dependencyArtifacts"] = [{"path": str(stand.isolated_verifier.DEPENDENCIES / asset["path"]), "name": asset["path"], "sha256": asset["sha256"]} for asset in profile["assets"]]
        report["dependencyArtifacts"].append({"path": str(stand.isolated_verifier.DEPENDENCIES / "manifest.json"), "name": "manifest.json", "sha256": profile["manifestSha256"]})
    else:
        report["dependencyProfile"] = {"id": "cold-network-original-image"}
    def save():
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    def request(path, data=None, authorized=True):
        headers = {"content-type": "application/json"}
        if authorized:
            headers["X-ObjRun-Grader-Token"] = token
        req = urllib.request.Request(origin + path, None if data is None else json.dumps(data).encode(), headers)
        try:
            with urllib.request.urlopen(req, timeout=960) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)
    def tool(name, args):
        code, value = request("/place", {"place": place, "tool": name, "args": args})
        assert code == 200, (name, code, value)
        report["toolResults"][name] = value
        return value
    try:
        code, health = request("/health", authorized=False)
        assert code == 200 and health["isolationReady"] and health["tasks"] == 89 and health["usable"] == 1
        assert health["supportedTaskIds"] == ["nginx-request-logging"] and health["graders"] == 1
        report["health"] = health
        assert request("/problems", authorized=False)[0] == 401
        code, problems = request("/problems")
        assert code == 200 and [problem["id"] for problem in problems] == ["nginx-request-logging"]
        assert token not in json.dumps(problems)
        report["problemTokenAbsent"] = True
        code, ping = request("/place", {"place": place, "op": "ping"})
        assert code == 200 and ping.get("alive"), (code, ping)
        rt = stand.runtime_of(place)
        definitions = rt.rpc("tools/list", {})["result"]["tools"]
        report["mcpToolNames"] = [definition["name"] for definition in definitions]
        assert {"bash", "read", "write", "edit", "glob", "grep"}.issubset(report["mcpToolNames"])
        got = tool("bash", {"command": "printf 'mcp-live\n'; pwd", "timeout_ms": 10000})
        assert got["code"] == 0 and "mcp-live" in got["stdout"] and "/app" in got["stdout"]
        tool("write", {"file_path": "/app/mcp-check.txt", "content": "before\n"})
        got = tool("read", {"file_path": "/app/mcp-check.txt"})
        assert got["lines"][0]["text"] == "before"
        tool("edit", {"file_path": "/app/mcp-check.txt", "old_string": "before", "new_string": "after"})
        assert "/app/mcp-check.txt" in tool("glob", {"pattern": "mcp-*.txt", "path": "/app"})["files"]
        assert tool("grep", {"pattern": "after", "path": "/app/mcp-check.txt"})["matches"][0]["text"] == "after"
        code, blocked = request("/place", {"place": place, "tool": "python_exec", "args": {"code": "print(1)"}})
        assert code == 500 and "six basic" in blocked["error"]
        report["unsupportedPythonExecExplicitlyBlocked"] = True
        # Docker bridge must not bypass the grader budget through a direct call.
        call = ("import urllib.request,urllib.error\n"
                "r=urllib.request.Request('http://host.docker.internal:" + str(server.server_port) + "/grade', b'{}', {'content-type':'application/json'})\n"
                "try:\n urllib.request.urlopen(r)\nexcept urllib.error.HTTPError as e:\n print(e.code)\n")
        probe = stand.cexec(name, "python3", "-c", call, timeout=15)
        assert probe.returncode == 0 and probe.stdout.strip() == "401", (probe.stdout, probe.stderr)
        report["unauthenticatedContainerGradeStatus"] = 401
        environment = stand.cexec(name, "env", timeout=10).stdout
        assert token not in environment and "TGENGIN_GRADER_TOKEN=" not in environment
        report["candidateTokenAbsent"] = True
        assert stand.sh("docker", "exec", "-d", name, "python3", "-c", SPY).returncode == 0
        for phase in (("empty", "oracle") if args.gate_only else ("empty", "oracle", "service-stopped")):
            if phase == "oracle":
                report["oracleExecutionCode"] = stand.run_oracle("nginx-request-logging", name)
                execution = stand.isolated_verifier.docker("exec", name, "cat", "/logs/agent/oracle.txt", timeout=15)
                (output / "oracle-execution.txt").write_text(execution.stdout + execution.stderr, encoding="utf-8")
                save()
                assert report["oracleExecutionCode"] == 0
            elif phase == "service-stopped":
                assert stand.cexec(name, "nginx", "-s", "stop", timeout=10).returncode == 0
            code, value = request("/grade", {"place": place, "said": phase})
            report["phases"][phase] = value
            save()
            assert code == 200 and value["ran"] is True and value["crashed"] is False, (code, value)
            assert value["namespaceBoundary"]["sameNetwork"] and value["namespaceBoundary"]["differentPid"] and value["namespaceBoundary"]["differentMount"]
            tests = json.loads((Path(value["box"]) / "ctrf.json").read_text(encoding="utf-8"))["results"]["tests"]
            value["valid"] = True
            value["completedTests"] = len(tests)
            value["passedTests"] = sum(test["status"] == "passed" for test in tests)
            assert value["completedTests"] == 8
            report["phases"][phase] = value
            save()
            assert value["reward"] == (1 if phase == "oracle" else 0), value
            print(json.dumps({"phase": phase, "reward": value["reward"], "seconds": value["seconds"]}), flush=True)
        spy = json.loads(stand.cexec(name, "cat", "/tmp/spy-observations.json", timeout=10).stdout)
        assert spy == {"privateFiles": False, "privateSecrets": False}, spy
        report["maliciousObserver"] = spy
        assert request("/stop", {"place": place}) == (200, {"ok": True})
        assert all(hashlib.sha256((ROOT / file).read_bytes()).hexdigest() == digest for file, digest in frozen.items()), "adapter source changed during the proof"
        report["officialGradingValid"] = True
        report["validated"] = True
        save()
        print(json.dumps({"validated": True, "report": str(output / "report.json")}), flush=True)
    except Exception as error:
        report["validated"] = False
        report["failure"] = type(error).__name__ + ": " + str(error)
        save()
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        stand.remove(name)
        for rt in stand.RUNTIMES.values():
            if rt.proc.poll() is None:
                rt.proc.kill()
            rt.proc.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
