"""Bounded narrow TLS observations of one live, exactly owned nginx candidate."""
from collections import Counter
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import secrets
import ssl
import threading
import uuid

from artifacts import stage_checker_image
from docker_owned import ROOT, sha

PATHS = {"/etc/nginx/conf.d/benchmark-site.conf", "/etc/nginx/nginx.conf", "/var/log/nginx/benchmark-access.log"}
COMMANDS = {("which", "nginx"), ("nginx", "-t")}


class LiveBroker:
    def __init__(self, native, candidate, output):
        self.native, self.candidate = native, candidate
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.token = secrets.token_urlsafe(32)
        self.calls, self.faults, self.receipts = Counter(), [], []
        source = ROOT / "examples/benchmark/terminal-bench/isolated_verifier.py"
        self.certificateSource = {"path": str(source), "sha256": sha(source)}
        spec = importlib.util.spec_from_file_location("tb12_trusted_certificate_helper", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        certificate, private_key = module.make_certificate(self.output)
        self.certificate = certificate
        self.lock = threading.Lock()
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def send(self, value, status=200):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def do_POST(self):
                if self.path != "/io" or not hmac.compare_digest(self.headers.get("X-ObjRun-State-Token", ""), owner.token):
                    self.send({"error": "Unauthorized"}, 401)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 8192:
                        raise ValueError("request length")
                    with owner.lock:
                        self.send(owner.query(json.loads(self.rfile.read(length))))
                except ValueError:
                    self.send({"error": "UnsupportedOperation"}, 422)
                except BaseException as error:
                    owner.faults.append({"type": type(error).__name__, "message": str(error)})
                    self.send({"error": "StateQueryFault"}, 503)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.timeout = 30
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(certificate), str(private_key))
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.url = f"https://host.docker.internal:{self.server.server_port}/io"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def query(self, request):
        if not isinstance(request, dict) or sum(self.calls.values()) >= 1024:
            raise ValueError("invalid or excessive observation")
        op = request.get("op")
        if op in ("exists", "read") and set(request) == {"op", "path"} and request["path"] in PATHS:
            argv = ["test", "-e", request["path"]] if op == "exists" else ["cat", request["path"]]
        elif op == "command" and set(request) == {"op", "argv"} and isinstance(request["argv"], list) and tuple(request["argv"]) in COMMANDS:
            argv = request["argv"]
        else:
            raise ValueError("unsupported observation")
        state = self.native.assert_actor(self.candidate)
        assert state["State"]["Running"] and not state["State"]["Paused"]
        receipt = self.native.command(["exec", self.candidate, *argv], timeout=20, stdout_limit=1024 ** 2)
        self.calls[op] += 1
        self.receipts.append({"request": request, "nativeReceipt": receipt})
        if op == "exists":
            return {"exists": receipt["exitCode"] == 0}
        return {"code": receipt["exitCode"], "stdout": Path(receipt["stdout"]["path"]).read_text(encoding="utf-8", errors="replace"),
                "stderr": Path(receipt["stderr"]["path"]).read_text(encoding="utf-8", errors="replace")}

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)
        assert not self.thread.is_alive()
        target = self.output / "broker-receipt.json"
        target.write_text(json.dumps({"protocol": "tb12-bounded-live-nginx-broker-v1", "candidateCid": self.candidate,
                                     "certificateHelper": self.certificateSource, "calls": dict(self.calls),
                                     "faults": self.faults, "receipts": self.receipts, "threadClosed": True,
                                     "port": self.server.server_port, "socketClosed": True,
                                     "tokenExcluded": True}, indent=2) + "\n", encoding="utf-8")


def grade_live(native, candidate, task, context, context_directory, private_base, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    invocation = uuid.uuid4().hex
    broker = LiveBroker(native, candidate, output / "broker")
    try:
        adapter_source = ROOT / "examples/benchmark/terminal-bench/nginx_client.py"
        adapter = output / "nginx_client.py"
        source = adapter_source.read_text(encoding="utf-8")
        assert source.count("/logs/verifier/isolation-fault.json") == 1
        adapter.write_text(source.replace("/logs/verifier/isolation-fault.json", "/tmp/isolation-fault.json"), encoding="utf-8")
        ca = output / "isolation"
        ca.mkdir()
        import shutil
        shutil.copyfile(broker.certificate, ca / "broker-ca.pem")
        config = {"protocol": "tb12-private-checker-config-v1", "taskId": task["taskId"],
                  "invocationId": invocation, "verifierSeconds": task["verifierSeconds"],
                  "packages": context["packages"], "officialTestHashes": task["officialTestHashes"],
                  "nginxAdapterSource": str(adapter), "nginxBrokerCaDirectory": str(ca)}
        capsule = {"files": [], "directories": []}
        image, staging = stage_checker_image(native, private_base, task, context_directory, capsule, config, output / "staging")
        environment = {**os.environ, "OBJRUN_STATE_BROKER": broker.url, "OBJRUN_STATE_TOKEN": broker.token}
        cid, initial, create = native.create(
            "private-checker-nginx", image, "/opt/checker/bin/python",
            ["-I", "-B", "/opt/tb12/checker/private_checker.py", "--config", "/opt/tb12/checker-config.json"],
            network="container:" + candidate, readonly=True,
            env_names=("OBJRUN_STATE_BROKER", "OBJRUN_STATE_TOKEN"), environment=environment)
        start = native.start(cid, attach=True, timeout=task["verifierSeconds"] + 30)
        final = native.assert_actor(cid)
        assert final["State"]["Status"] == "exited" and final["State"]["ExitCode"] == 0
        last = native.text(start).splitlines()[-1]
        assert last.startswith("TB12_RESULT:")
        result = json.loads(last[len("TB12_RESULT:"):])
        assert result["invocationId"] == invocation and result["taskId"] == task["taskId"]
        assert result["exitCode"] in (0, 1) and result["reward"] == int(result["exitCode"] == 0)
        assert {item["name"].split("::")[-1] for item in result["ctrf"]["results"]["tests"]} == set(task["staticTestNames"])
        assert not broker.faults, "Live state broker fault is infrastructure failure"
        removal, absence = native.remove(cid)
        receipt = {"protocol": "tb12-live-nginx-grade-v1", "invocationId": invocation, "candidateCid": candidate,
                   "checkerCid": cid, "initialState": initial, "create": create, "start": start,
                   "finalState": final, "result": result, "staging": staging, "image": image,
                   "removal": removal, "absence": absence, "liveServiceIsImmutableSnapshot": False}
        (output / "grade.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        return receipt
    finally:
        broker.close()
