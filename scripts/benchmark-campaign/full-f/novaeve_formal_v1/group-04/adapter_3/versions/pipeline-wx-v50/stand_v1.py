"""Authenticated twelve-task candidate factory and original private grading."""
import argparse
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import threading
import time
import traceback
import uuid

from docker_owned import OwnedDocker, ROOT, sha
from live_nginx import grade_live
from runtime_transport import stage_runtime, ship_runtime, call_tool
from snapshot_grader import grade_snapshot
from artifacts import capture_file


class AdmissionClosed(RuntimeError):
    pass


class Stand:
    def __init__(self, base_proof, output, token):
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.native = OwnedDocker(self.output, uuid.uuid4().hex)
        self.token = token
        assert len(token) >= 32
        proof = json.loads(Path(base_proof).read_bytes())
        assert proof["actualPrivateImportsValidated"] and proof["allOwnedBuildersClosed"]
        self.private_base = proof["immutablePrivateImageId"]
        self.context_path = Path(proof["contextManifest"]["path"])
        assert sha(self.context_path) == proof["contextManifest"]["sha256"]
        self.context = json.loads(self.context_path.read_bytes())
        self.tasks = {task["taskId"]: task for task in self.context["tasks"]}
        source = Path(proof["imagesPin"]["path"])
        assert sha(source) == proof["imagesPin"]["sha256"]
        self.images = {row["taskId"]: row["immutableImageId"] for row in json.loads(source.read_bytes())["records"]}
        assert len(self.tasks)==89
        if proof.get('protocol')=='terminal-ready-segment-v1':
            assert proof['fullPlanTaskCount']==89
            ready=proof['readyTaskIds'];assert ready and len(ready)==len(set(ready))
            assert set(ready)<=set(self.tasks) and set(ready)<=set(self.images)
            assert all(self.tasks[tid]['privateInterfaceImplemented'] for tid in ready)
            self.ready_task_ids=set(ready)
        else:
            assert set(self.tasks)==set(self.images)
            assert all(task['privateInterfaceImplemented'] for task in self.tasks.values()), 'Full private interfaces incomplete'
            self.ready_task_ids=set(self.tasks)
        self.runtime = stage_runtime(self.output / "runtime")
        self.places = {}
        self.gate = threading.RLock()
        self.rows = []
        self.fatal = None

    def persist(self):
        target = self.output / "stand-receipts.json"
        target.write_text(json.dumps({"protocol": "tb12-owned-authenticated-stand-v1",
                                     "createdAtUtc": datetime.now(timezone.utc).isoformat(),
                                     "ownerNonce": self.native.nonce, "rows": self.rows,
                                     "fatal": self.fatal, "openActors": self.native.open_actors(),
                                     "modelCallsInStand": 0, "authenticationTokenExcluded": True}, indent=2) + "\n", encoding="utf-8")

    def up(self, body):
        with self.gate:
            assert not self.places and not self.native.open_actors(), "Only one owned live candidate"
            task_id, place, attempt = body["taskId"], body["place"], body["attemptId"]
            assert task_id in self.ready_task_ids and body["arm"] == "F"
            assert re.fullmatch(r"tb12:[a-zA-Z0-9/_-]+", place)
            assert re.fullmatch(r"tb12-[a-zA-Z0-9/_-]+", attempt)
            task = self.tasks[task_id]
            from activation_guard import bound_control
            activation, _ = bound_control(ROOT)
            environment = dict(os.environ)
            internet = task["officialEnvironment"]["allow_internet"]
            if internet:
                assert activation['network']['dockerNetwork'] == 'bridge'
                environment.update({'HTTP_PROXY': activation['network']['httpProxy'], 'HTTPS_PROXY': activation['network']['httpsProxy']})
            cid, initial, create = self.native.create(
                "candidate-" + task_id, self.images[task_id], "/bin/sh", ["-c", "sleep 86400"],
                network="bridge" if task["officialEnvironment"]["allow_internet"] else "none",
                memory_mb=task["officialEnvironment"]["memory_mb"], cpus=task["officialEnvironment"]["cpus"],
                env_names=('HTTP_PROXY', 'HTTPS_PROXY') if internet else (), environment=environment,
                drop_capabilities=False)
            self.native.start(cid)
            runtime = ship_runtime(self.native, cid, self.runtime)
            namespaces = {}
            namespace_receipts = {}
            for name in ("pid", "mnt", "net"):
                observed = self.native.execute(cid, ["/usr/bin/readlink", "/proc/self/ns/" + name])
                namespaces[name], namespace_receipts[name] = self.native.text(observed), observed
            public_image = None
            protected = {}
            protected_paths = (["/app/oewn.sqlite", "/app/my-sql-query.sql"] if task_id == "query-optimize" else
                               ["/app/alice_calendar.ics", "/app/bob_calendar.ics", "/app/carol_calendar.ics"] if task_id == "constraints-scheduling" else [])
            for path in protected_paths:
                item = capture_file(self.native, cid, path, task["profile"]["artifacts"][path],
                                    self.output / "public-inputs" / uuid.uuid4().hex)
                assert item["exists"], "Protected public input missing before model"
                protected[path] = item
            if task_id == "query-optimize":
                assert protected["/app/oewn.sqlite"]["sha256"] == "89eab7555b6b86a74b8e0ee5a7db7beec0b2575a45cd2b22fe132eae79f5ad5a"
            if task_id == "chess-best-move":
                public_image = capture_file(self.native, cid, "/app/chess_board.png", 2 * 1024 ** 2,
                                            self.output / "public-inputs" / uuid.uuid4().hex)
                assert public_image["exists"]
            owner = {"cid": cid, "taskId": task_id, "attemptId": attempt, "arm": body["arm"],
                     "created": time.monotonic(), "deadline": None, "sealed": False,
                     "lock": threading.RLock(), "pendingGrade": None, "grades": 0,
                     "initialNamespaces": namespaces, "protectedInputs": protected}
            owner["storageFault"] = False
            self.places[place] = owner
            self.rows.append({"kind": "candidate-up", "place": place, "taskId": task_id,
                              "attemptId": attempt, "arm": body["arm"], "cid": cid,
                              "initialState": initial, "create": create, "runtime": runtime,
                              "initialNamespaces": namespaces, "namespaceReceipts": namespace_receipts,
                              "publicImage": public_image, "protectedInputs": protected})
            self.persist()
            return {"ok": True, "cid": cid, "taskId": task_id, "publicImage": public_image}

    def owner(self, place):
        assert place in self.places, "Unknown owned place"
        return self.places[place]

    def storage_observation(self, owner, place):
        size, receipt = self.native.writable_size(owner["cid"])
        exceeded = False
        owner["storageFault"] = False
        self.rows.append({"kind": "candidate-storage-observation", "place": place,
                          "sizeRwBytes": size, "limitBytes": None, "officialStorageProvenanceBytes": self.tasks[owner["taskId"]]["officialEnvironment"]["storage_mb"] * 1024 ** 2,
                          "boundarySampleOnly": True, "hardQuotaEnforced": False, "diskQuotaEnforced": False, "writableLayerHardLimitBytes": None, "userAuthorized": True,
                          "exceeded": exceeded, "receipt": receipt})
        self.persist()
        return exceeded

    def seal(self, place):
        owner = self.owner(place)
        with owner["lock"]:
            self.storage_observation(owner, place)
            owner["sealed"] = True
            state = self.native.assert_actor(owner["cid"])
            pause = None
            if owner["taskId"] != "nginx-request-logging" and not state["State"]["Paused"]:
                pause = self.native.pause(owner["cid"])
            self.rows.append({"kind": "candidate-seal", "place": place, "state": state, "pause": pause})
            self.persist()
            return {"sealed": True}

    def grade(self, owner, place, label):
        task = self.tasks[owner["taskId"]]
        output = self.output / "grades" / uuid.uuid4().hex
        grader = grade_live if task["taskId"] == "nginx-request-logging" else grade_snapshot
        record = grader(self.native, owner["cid"], task, self.context, self.context_path.parent, self.private_base, output)
        spaces = record["result"]["privateNamespaces"]
        assert all(spaces[name] != owner["initialNamespaces"][name] for name in ("pid", "mnt"))
        assert (spaces["net"] == owner["initialNamespaces"]["net"]) == (task["taskId"] == "nginx-request-logging")
        protected_matches = True
        if owner["protectedInputs"]:
            capsule = json.loads(Path(record["capsulePath"]).read_bytes())
            captured = {item["path"]: item for item in capsule["files"]}
            protected_matches = all(captured[path]["exists"] and captured[path]["sha256"] == initial["sha256"]
                                    for path, initial in owner["protectedInputs"].items())
        record["originalReward"] = record["result"]["reward"]
        record["protectedInputsUnchanged"] = protected_matches
        record["storageBoundaryExceeded"] = False
        record["policyReward"] = int(bool(record["originalReward"]) and protected_matches)
        owner["grades"] += 1
        self.rows.append({"kind": "grade", "place": place, "attemptId": owner["attemptId"],
                          "taskId": owner["taskId"], "arm": owner["arm"],
                          "invocationId": record["invocationId"], "label": label,
                          "labelSha256": hashlib.sha256(label.encode()).hexdigest(),
                          "gradePath": str(output / "grade.json"),
                          "gradeSha256": sha(output / "grade.json"), "originalReward": record["originalReward"],
                          "protectedInputsUnchanged": protected_matches, "policyReward": record["policyReward"]})
        state = self.native.assert_actor(owner["cid"])
        if not owner["sealed"] and state["State"]["Paused"]:
            self.native.unpause(owner["cid"])
        self.persist()
        return record

    def route(self, path, body):
        if path == "/close":
            canceled = [{"place": place, "pendingInvocation": owner["pendingGrade"]["record"]["invocationId"] if owner["pendingGrade"] else None}
                        for place, owner in self.places.items()]
            for cid, role, name in self.native.open_actors():
                removal, absence = self.native.remove(cid)
                self.rows.append({"kind": "owned-close", "cid": cid, "role": role,
                                  "removal": removal, "absence": absence})
            self.rows.append({"kind": "stand-close", "canceled": canceled, "fatalPreserved": self.fatal})
            self.places.clear()
            self.persist()
            return {"ok": True, "allExactOwnedActorsAbsent": not self.native.open_actors()}
        if self.fatal and path not in ("/stop", "/seal"):
            raise RuntimeError("Stand evidence fault has closed admission")
        if path == "/up":
            return self.up(body)
        place = body.get("place")
        if path in ("/ran", "/passed"):
            inp = body.get("input") or {}
            task_input = inp.get("task") or {}
            place = task_input.get("place")
            owner = self.owner(place)
            assert task_input.get("id") == owner["attemptId"], "Grader attempt mismatch"
            result = inp.get("result")
            label = result.get("body") if isinstance(result, dict) else result
            label = str(label if label is not None else task_input.get("result", "")).strip()
        else:
            owner = self.owner(place)
            label = str(body.get("said", "")).strip()
        with owner["lock"]:
            if path == "/begin":
                assert owner["deadline"] is None and not owner["sealed"]
                owner["deadline"] = time.monotonic() + self.tasks[owner["taskId"]]["agentSeconds"]
                self.rows.append({"kind": "candidate-begin", "place": place, "atUtc": datetime.now(timezone.utc).isoformat(), "officialAgentSeconds": self.tasks[owner["taskId"]]["agentSeconds"]})
                self.persist()
                return {"ok": True}
            if path == "/seal":
                return self.seal(place)
            if path == "/place":
                state = self.native.assert_actor(owner["cid"])
                if body.get("op") == "ping":
                    return {"alive": state["State"]["Running"] and not owner["sealed"]}
                if owner["sealed"] or owner["deadline"] is None or time.monotonic() >= owner["deadline"]:
                    raise AdmissionClosed("Candidate tool admission closed")
                self.storage_observation(owner, place)
                value, receipt = call_tool(self.native, owner["cid"], body["tool"], body.get("args") or {}, owner["deadline"])
                self.rows.append({"kind": "tool", "place": place, "tool": body["tool"], "nativeReceipt": receipt})
                self.storage_observation(owner, place)
                self.persist()
                return value
            if path == "/ran":
                assert owner["arm"] == "F" or owner["sealed"], "U receives only final grading"
                assert owner["pendingGrade"] is None, "Previous grade invocation not consumed"
                grade = self.grade(owner, place, label)
                owner["pendingGrade"] = {"label": label, "record": grade}
                self.rows.append({"kind": "ran-delivered", "place": place, "invocationId": grade["invocationId"], "value": True})
                self.persist()
                return {"value": True}
            if path == "/passed":
                pending = owner["pendingGrade"]
                assert pending is not None and pending["label"] == label, "Missing exact /ran binding"
                assert body.get("feed") and body["feed"][0].get("value") is True
                owner["pendingGrade"] = None
                grade = pending["record"]
                passed = bool(grade["policyReward"])
                self.rows.append({"kind": "passed-delivered", "place": place, "invocationId": grade["invocationId"], "value": passed})
                self.persist()
                return {"value": passed, **({} if passed else {"note": "The sealed candidate state did not pass all original tests."})}
            if path == "/stop":
                assert owner["pendingGrade"] is None
                removal, absence = self.native.remove(owner["cid"])
                self.rows.append({"kind": "candidate-stop", "place": place, "cid": owner["cid"], "removal": removal, "absence": absence})
                del self.places[place]
                self.persist()
                return {"ok": True, "exactCidAbsent": True}
            raise ValueError("Unsupported route")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-proof", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    token = os.environ.get("OBJRUN_TB12_STAND_TOKEN", "")
    stand = Stand(args.base_proof, args.output, token)
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
        def do_GET(self):
            if self.path == "/health":
                self.send({"ok": True, "protocol": "tb12-owned-authenticated-stand-v1",
                           "tasks": len(stand.tasks), "modelCallsInStand": 0, "authenticated": True})
            else:
                self.send({"error": "Unsupported"}, 404)
        def do_POST(self):
            if not hmac.compare_digest(self.headers.get("X-ObjRun-Grader-Token", ""), stand.token):
                self.send({"error": "Unauthorized"}, 401)
                return
            status = 200
            try:
                length = int(self.headers.get("Content-Length", "0"))
                assert 0 < length <= 1024 ** 2
                body = json.loads(self.rfile.read(length))
                value = stand.route(self.path, body)
            except AdmissionClosed:
                value, status = {"error": "CandidateAdmissionClosed"}, 409
            except BaseException as error:
                fault = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
                if stand.fatal is None:
                    stand.fatal = fault
                stand.rows.append({"kind": "stand-fault", "path": self.path,
                                   "atUtc": datetime.now(timezone.utc).isoformat(),
                                   "fault": fault, "firstFaultPreserved": stand.fatal})
                stand.persist()
                value, status = {"error": "OwnedStandFault", "type": type(error).__name__}, 503
            try:
                self.send(value, status)
            except (BrokenPipeError, ConnectionResetError) as error:
                # The route has already completed and its native receipts were
                # persisted. A departed client cannot poison future admission.
                stand.rows.append({"kind": "stand-response-disconnected", "path": self.path,
                                   "atUtc": datetime.now(timezone.utc).isoformat(),
                                   "status": status, "errorType": type(error).__name__,
                                   "responseSha256": hashlib.sha256(json.dumps(value).encode()).hexdigest()})
                stand.persist()
            if self.path == "/close" and status == 200:
                self.server.shutdown()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    stand.persist()
    print(json.dumps({"protocol": "tb12-stand-ready-v1", "pid": os.getpid(), "port": server.server_port,
                      "output": str(stand.output), "modelCalls": 0}), flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
        for cid, role, name in stand.native.open_actors():
            stand.native.remove(cid)
        stand.persist()
        stand.native.close()


if __name__ == "__main__":
    main()
