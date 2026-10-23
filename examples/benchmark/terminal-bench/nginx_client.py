"""Private grader I/O shim. Never copied into the solving container."""
import json
import os
from pathlib import Path
import ssl
import subprocess
import urllib.error
import urllib.request

PATHS = {"/etc/nginx/conf.d/benchmark-site.conf", "/etc/nginx/nginx.conf", "/var/log/nginx/benchmark-access.log"}
COMMANDS = {("which", "nginx"), ("nginx", "-t")}
_EXISTS = Path.exists
_READ_TEXT = Path.read_text
_RUN = subprocess.run


def query(payload):
    context = ssl.create_default_context(cafile="/isolation/broker-ca.pem")
    request = urllib.request.Request(os.environ["OBJRUN_STATE_BROKER"], json.dumps(payload).encode(),
                                     {"content-type": "application/json", "X-ObjRun-State-Token": os.environ["OBJRUN_STATE_TOKEN"]})
    try:
        with urllib.request.urlopen(request, context=context, timeout=30) as response:
            return json.load(response)
    except Exception as error:
        # A broken adapter must never become a valid model rejection.
        Path("/logs/verifier/isolation-fault.json").write_text(json.dumps({"errorType": type(error).__name__}))
        raise RuntimeError("isolated state broker is unavailable") from None


def exists(path, *args, **kwargs):
    if str(path) in PATHS:
        return query({"op": "exists", "path": str(path)})["exists"]
    return _EXISTS(path, *args, **kwargs)


def read_text(path, *args, **kwargs):
    if str(path) in PATHS:
        result = query({"op": "read", "path": str(path)})
        if result["code"]:
            raise FileNotFoundError(str(path))
        return result["stdout"]
    return _READ_TEXT(path, *args, **kwargs)


def run(argv, *args, **kwargs):
    if isinstance(argv, (list, tuple)) and tuple(argv) in COMMANDS:
        if args or set(kwargs) - {"capture_output", "text"} or kwargs.get("capture_output") is not True or kwargs.get("text") is not True:
            raise RuntimeError("unsupported official command interface")
        result = query({"op": "command", "argv": list(argv)})
        return subprocess.CompletedProcess(argv, result["code"], result["stdout"], result["stderr"])
    return _RUN(argv, *args, **kwargs)


def install():
    Path.exists = exists
    Path.read_text = read_text
    subprocess.run = run

