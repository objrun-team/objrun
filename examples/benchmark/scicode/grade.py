"""Trusted tests run outside the candidate process; only numeric values cross RPC."""
from __future__ import annotations
import ast
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import traceback
sys.path.insert(0, "/worker")
import numpy as np
from codec import decode, encode

PRIVATE = Path("/root/oracle")
sys.path.insert(0, "/root/vendor")
from scicode.parse.parse import process_hdf5_to_tuple
import scicode
scicode.__path__.append("/root/scicode-extra/scicode")

class CandidateFailure(Exception):
    pass

class GraderFailure(Exception):
    pass

def unprivileged():
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)

def grade(request):
    code = request["code"]
    problem = request["problem"]
    step = request["step"]
    code_file = Path("/tmp/candidate.py")
    code_file.write_text(code, encoding="utf-8")
    code_file.chmod(0o644)
    try:
        parsed = ast.parse(code)
    except SyntaxError:
        return {"passed": False, "valid": True, "errorType": "SyntaxError"}
    functions = [node.name for node in parsed.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    worker = subprocess.Popen([sys.executable, "-I", "/worker/worker.py", str(code_file)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1, preexec_fn=unprivileged, env={"PATH": "/usr/local/bin:/usr/bin:/bin", "MPLCONFIGDIR": "/tmp/matplotlib", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
    def timed_out(*_):
        raise CandidateFailure("CandidateTimeout")
    signal.signal(signal.SIGALRM, timed_out)
    signal.alarm(int(request.get("seconds", 90)))
    calls = 0
    try:
        raw = worker.stdout.readline()
        if not raw:
            raise CandidateFailure("CandidateExited")
        hello = json.loads(raw)
        if not hello.get("ready"):
            return {"passed": False, "valid": True, "errorType": hello.get("errorType", "ExecutionError")}
        if hello.get("uid") != 65534:
            raise RuntimeError("candidate privilege boundary not established")
        def proxy(name):
            def invoke(*args, **kwargs):
                nonlocal calls
                calls += 1
                payload = {"function": name, "args": encode(args), "kwargs": encode(kwargs), "rng": encode(np.random.get_state())}
                worker.stdin.write(json.dumps(payload) + "\n")
                worker.stdin.flush()
                raw = worker.stdout.readline()
                if not raw:
                    raise CandidateFailure("CandidateExited")
                reply = json.loads(raw)
                if not reply.get("ok"):
                    if reply.get("errorType") == "UnsupportedScientificObject":
                        raise GraderFailure("UnsupportedScientificObject")
                    raise CandidateFailure(reply.get("errorType", "ExecutionError"))
                np.random.set_state(decode(reply["rng"]))
                try:
                    return decode(reply["value"])
                except Exception:
                    raise CandidateFailure("InvalidResult")
            return invoke
        namespace = {"__name__": "official_tests"}
        exec(problem["required_dependencies"], namespace)
        namespace.update({name: proxy(name) for name in functions})
        cases = step["test_cases"]
        targets = process_hdf5_to_tuple(step["step_number"], len(cases), str(PRIVATE / "test_data_cleaned.h5"))
        for index, test_case in enumerate(cases):
            namespace["target"] = targets[index]
            try:
                exec(compile(test_case, "official_test.py", "exec"), namespace)
            except CandidateFailure:
                raise
            except (GraderFailure, ImportError, OSError):
                raise
            except Exception as error:
                return {"passed": False, "valid": True, "errorType": type(error).__name__, "calls": calls}
        return {"passed": True, "valid": True, "calls": calls}
    except CandidateFailure as error:
        return {"passed": False, "valid": True, "errorType": str(error), "calls": calls}
    except AssertionError:
        return {"passed": False, "valid": True, "errorType": "AssertionError", "calls": calls}
    except Exception as error:
        return {"passed": False, "valid": False, "errorType": type(error).__name__, "calls": calls, "diagnostic": [{"file": frame.filename, "line": frame.lineno} for frame in traceback.extract_tb(error.__traceback__)]}
    finally:
        signal.alarm(0)
        if worker.poll() is None:
            worker.kill()
        worker.wait(timeout=5)

if __name__ == "__main__":
    try:
        result = grade(json.load(sys.stdin))
    except Exception as error:
        result = {"passed": False, "valid": False, "errorType": type(error).__name__, "diagnostic": [{"file": frame.filename, "line": frame.lineno} for frame in traceback.extract_tb(error.__traceback__)]}
    print(json.dumps(result), flush=True)
