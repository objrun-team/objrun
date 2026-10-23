from __future__ import annotations
import argparse
import ast
import hashlib
import json
import re
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"examples/benchmark/_lib"))
from grader_status import require_valid_verdict, fault_payload
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from controller import PROBLEMS, PILOT_IDS, score

PREFIXES = {}
CACHE = {}

def extract_code(text):
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    return (match.group(1) if match else text).strip()

def prompt(problem, index, previous, with_background=True):
    step = problem["sub_steps"][index]
    history = []
    for k, code in enumerate(previous):
        prior = problem["sub_steps"][k]
        history += [prior["step_description_prompt"], code]
    description = step["step_description_prompt"]
    if with_background:
        description += "\n" + step["step_background"]
    return "\n\n".join(["Write scientific Python code for the next substep. Keep the named function signature and return a complete Python definition. Previous code is this run's model output.", "Required imports:\n" + problem["required_dependencies"], *history, description, step["function_header"], step["return_line"], "Submit only Python code. Do not include tests or expected outputs."])

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass
    def send(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        if self.path == "/health":
            self.send({"ok": True, "variant": "SciCode-Verified v2", "problems": len(PROBLEMS), "pilotIds": PILOT_IDS})
        elif self.path == "/problems":
            self.send([{"id": pid, "steps": len(PROBLEMS[pid]["sub_steps"]), "name": PROBLEMS[pid]["problem_name"]} for pid in PILOT_IDS])
        else:
            self.send({"error": "not found"}, 404)
    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))
            if self.path == "/prepare":
                pid, index = str(body["problem"]), int(body["step"])
                if pid not in PILOT_IDS or len(body["previous"]) != index:
                    raise ValueError("invalid fixed pilot task")
                PREFIXES[body["task"]] = {"problem": pid, "step": index, "previous": list(body["previous"])}
                self.send({"prompt": prompt(PROBLEMS[pid], index, body["previous"]), "stepId": PROBLEMS[pid]["sub_steps"][index]["step_number"]})
                return
            if self.path == "/accept":
                pid = str(body["problem"])
                code = PROBLEMS[pid]["required_dependencies"] + "\n\n" + "\n\n".join(body["codes"])
                results = [require_valid_verdict(score(pid, k, code)) for k in range(len(PROBLEMS[pid]["sub_steps"]))]
                self.send({"passed": all(r["passed"] for r in results), "valid": True, "steps": results, "cumulativeCodeSha256": hashlib.sha256(code.encode()).hexdigest(), "candidateCodeSha256": [hashlib.sha256(c.encode()).hexdigest() for c in body["codes"]]})
                return
            if self.path not in ["/parsed", "/passed"]:
                self.send({"error": "not found"}, 404)
                return
            inp = body.get("input", {})
            task = inp.get("task", {})
            task_id = task.get("id")
            if task_id not in PREFIXES:
                self.send({"error": "task was not prepared"}, 422)
                return
            candidate = inp.get("result")
            text = candidate.get("body", "") if isinstance(candidate, dict) else candidate
            if text is None:
                text = task.get("result", "")
            code = extract_code(str(text))
            try:
                ast.parse(code)
                parsed = bool(code)
            except SyntaxError:
                parsed = False
            if self.path == "/parsed":
                self.send({"value": parsed, "note": "" if parsed else {"errorType": "SyntaxError"}})
                return
            setting = PREFIXES[task_id]
            problem = PROBLEMS[setting["problem"]]
            cumulative = problem["required_dependencies"] + "\n\n" + "\n\n".join([*setting["previous"], code])
            key = (task_id, setting["problem"], setting["step"], hashlib.sha256(cumulative.encode()).hexdigest())
            if key not in CACHE:
                verdict = require_valid_verdict(score(setting["problem"], setting["step"], cumulative))
                CACHE[key] = verdict
            verdict = require_valid_verdict(CACHE[key])
            self.send({"value": verdict["passed"], "note": "" if verdict["passed"] else {"errorType": verdict.get("errorType", "AssertionError")}})
        except Exception as error:
            self.send(fault_payload(error), 503)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=17921)
    args = parser.parse_args()
    print(json.dumps({"listening": args.port, "variant": "SciCode-Verified v2"}), flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
