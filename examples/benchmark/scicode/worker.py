"""Unprivileged candidate process. No target data, tests, credentials or network."""
import contextlib
import io
import json
import os
import sys
sys.path.insert(0, "/worker")
import numpy as np
from codec import decode, encode

SAFE_ERRORS = {"SyntaxError", "TypeError", "ValueError", "NameError", "IndexError", "KeyError", "ZeroDivisionError", "AssertionError", "RuntimeError", "PermissionError", "FileNotFoundError"}
namespace = {"__name__": "candidate"}
try:
    code = open(sys.argv[1], encoding="utf-8").read()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        exec(compile(code, "candidate.py", "exec"), namespace)
except BaseException as error:
    print(json.dumps({"ready": False, "errorType": type(error).__name__ if type(error).__name__ in SAFE_ERRORS else "ExecutionError"}), flush=True)
    raise SystemExit(1)
print(json.dumps({"ready": True, "uid": os.getuid()}), flush=True)
for line in sys.stdin:
    try:
        request = json.loads(line)
        if "rng" in request:
            np.random.set_state(decode(request["rng"]))
        fn = namespace[request["function"]]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            answer = fn(*decode(request["args"]), **decode(request["kwargs"]))
        response = {"ok": True, "value": encode(answer), "rng": encode(np.random.get_state())}
    except BaseException as error:
        response = {"ok": False, "errorType": type(error).__name__ if type(error).__name__ in SAFE_ERRORS else "ExecutionError"}
    print(json.dumps(response), flush=True)
