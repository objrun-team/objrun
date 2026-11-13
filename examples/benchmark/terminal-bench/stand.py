r"""Terminal-Bench 2.1 service: an HTTP service outside the engine, running on a Docker host.

2026-10-08 isolation fix: the exact supported nginx-request-logging version can use an independent grader to inspect the live service. Other tasks and Apptainer lack a verified isolation protocol and are blocked in formal experiments. The --unsafe-diagnostic shared live-container protocol is for reproduction only and cannot produce valid scores. HTTP problem, tool, and grading endpoints require the host TGENGIN_GRADER_TOKEN.

    python3 stand.py [--port 7903] [--level 2] [--selftest [TASK_ID...]]

The engine sees **three handles**:

    http://127.0.0.1:7903/place     Where to work: forward tool calls into the task container.
    http://127.0.0.1:7903/ran       First node of G: did official tests/test.sh finish and write a reward?
    http://127.0.0.1:7903/passed    Root of G: is reward == 1?

Each handle is its own address. The kernel POSTs JSON and receives JSON; there is no additional protocol.

## The candidate is the final container state, not a file

Terminal-Bench has no Git repository or patch: tasks ask for a particular container state (install Windows 3.11, configure nginx logging, write /app/move.txt correctly…). Official grading defaults to **running `tests/test.sh` in the work container** (harbor `verifier.environment_mode` defaults to `shared`). Thus cand is the container itself at grading time. The solver’s submitted string only names the candidate, associating `ran` / `passed` with the same grading run; its content does not affect the decision.

**Do not snapshot.** `docker commit` cannot preserve running processes, and some of the 89 tasks test live services (nginx, pypi-server, kv-store-grpc, qemu-alpine-ssh…). Snapshots would score 0 for all of them, making tasks appear broken. The new independent nginx grader shares the service network and reads three files and two commands from the live container through a narrow interface, retaining service state without placing tests in the candidate.

## The official grader, unchanged

Each task’s `tests/test.sh` is the grader (install uv, run `pytest --ctrf`, and on success write `echo 1 > /logs/verifier/reward.txt`). This file implements no grading decisions: start the container, copy `tests/` into `/tests`, run `test.sh`, and read `reward.txt`. Parsing matches harbor `src/harbor/verifier/verifier.py::_parse_reward_text` (float, finite; an empty file is an error). If both files exist, `reward.json` takes precedence, as in harbor. The independent nginx protocol also checks completion of all eight fixed tests, source-file hashes, original image ID, namespaces, and narrow-interface failure states.

Diagnostic shared grading modifies the container: test.sh runs `apt-get install curl` and installs uv. Official runs grade only once, so this is immaterial there; here, intermediate `verify` calls add another layer each time. This is a property of the official grader and is not blocked.

## Diagnostic cleanup is not test isolation

Grading copies hidden tests into the solver’s container. Without cleanup, the next `bash` could run `cat /tests/test_outputs.py`, exposing the entire answer rather than any feedback level. The diagnostic path cleans /tests and /logs/verifier; Apptainer’s /stage transfer copies are also removed in upload’s finally block. **Tests remain visible during the tens of seconds grading runs**, because it is the same container and filesystem. This window cannot be eliminated here and must be recorded (see “boundary” in G.md).

## Network

All 89 official tasks set `allow_internet = true`, and **test.sh itself needs network access** (curl astral.sh to install uv, apt-get). Containers therefore cannot use `--network none`, unlike deepswe. The cost is that reference solutions are public on GitHub and accessible with curl inside the container. This is a gap in the official benchmark (which relies on canary strings and the honor system), beyond what this service can close.

## Feedback levels: how much this field reveals

`--level` determines detail in `note`. **Each level is a separate experiment**; the engine knows nothing about it, and G keeps the same shape.

    0   Pass/fail only.
    1   + Failed stage + counts (4 of 9 tests passed).
    2   + Failed tests (stable test#N indices).
    3   + Raw failure messages (explicit diagnostics only; rejected in formal mode).

## solution/ stays within this process

`tasks/<id>/solution/solve.sh` contains the reference solution. Use it only for self-tests (copy to `/solution` and run once as harbor `OracleAgent` does; it should score 1). Install the corpus in the service host’s home directory, outside the repository."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '_lib'))
from grader_status import require_result, fault_payload
import isolated_verifier

HOME_DIR = Path(os.environ.get("TGENGIN_TB_HOME", Path.home() / ".cache" / "tgengin-terminal-bench"))

# ── Backends: Docker or Apptainer ──
#
# **Keep the grader unchanged; replace only four container operations** (start, exec, upload, download). Sherlock has no Docker, only Apptainer 1.5 (no subuid; fakeroot uses a root-mapped namespace). Measurements are in $SCRATCH/bench-feas/REPORT-terminal-bench.md. Key points:
#
#   - One SIF per task (`images/<tid>.sif`, `apptainer pull docker://<pinned>`), one instance per run.
#   - Use a **directory overlay** (`--overlay <dir>` in /lscratch), not --writable-tmpfs (which uses memory).
#   - `--containall --no-home`: private /tmp; do not mount HOME over /root and hide image contents.
#   - Bind `/rt` and `/stage` (tests/solution transfer), and bind `/logs` to a host directory (as harbor does).
#   - `instance start` rejects `--pwd`; pass `--pwd <WORKDIR>` on every exec (parsed from the task Dockerfile).
#   - After startup, add a 3-line drop-in under /etc/apt/apt.conf.d/; otherwise test.sh apt-get fails spuriously because the _apt sandbox directory is unwritable.
#   - `--cpus/--memory` are unavailable (no cgroups under fakeroot); rely on whole-job Slurm limits. No PID namespace or network isolation (this benchmark already requires network access).
BACKEND = os.environ.get("TGENGIN_TB_BACKEND", "apptainer" if shutil.which("docker") is None and shutil.which("apptainer") else "docker")
IMAGES = HOME_DIR / "images"
STAGE = HOME_DIR / "stage"
OVERLAYS = Path(os.environ.get("TGENGIN_TB_OVERLAYS", f"/lscratch/{os.environ.get('USER', 'u')}/tgengin-tb"))
APT_DROPIN = "mkdir -p /tmp/ac/partial /tmp/al/partial; printf '%s\\n' 'APT::Sandbox::User \"root\";' 'Dir::Cache::archives \"/tmp/ac\";' 'Dir::State::lists \"/tmp/al\";' > /etc/apt/apt.conf.d/99sherlock"
CORPUS = Path(os.environ.get("TGENGIN_TB_CORPUS", HOME_DIR / "terminal-bench-2-1" / "tasks"))
RUNTIME = Path(os.environ.get("TGENGIN_TB_RUNTIME", HOME_DIR / "tgengin-runtime-linux-x64"))
NODE_RUNTIME = Path(__file__).with_name(".runtime")
LOGS = HOME_DIR / "logs"

LEVEL = int(os.environ.get("TGENGIN_TB_LEVEL", "2"))
GRADER_TOKEN = os.environ.get("TGENGIN_GRADER_TOKEN", "")
ALLOW_UNSAFE_DIAGNOSTIC = os.environ.get("TGENGIN_UNSAFE_DIAGNOSTIC", "") == "1"

# **How long to retain a grading result for the second node.** `ran` stores it and `passed` normally reads it
# within a second. Ten minutes accommodates a slow engine; after that, treat it as ungraded, since the container has changed.
RESULT_TTL = 600

# **Docker must be on PATH first.** The snap installation appears only on a login shell’s PATH (as in deepswe).
if shutil.which("docker") is None and Path("/snap/bin/docker").exists():
    os.environ["PATH"] = "/snap/bin:" + os.environ.get("PATH", "")


# ── Corpus ──


def workdir_of(dockerfile: Path) -> str:
    w = "/app"
    try:
        for line in dockerfile.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*WORKDIR\s+(\S+)", line)
            if m:
                w = m.group(1)
    except OSError:
        pass
    return w


def load_corpus() -> dict[str, dict]:
    r"""Load metadata for all 89 tasks. **Do not read answers**: `solution/` is accessed only during self-tests."""
    if not CORPUS.is_dir():
        raise SystemExit(f"the task corpus is missing: {CORPUS} (run setup.sh first)")
    book: dict[str, dict] = {}
    for d in sorted(CORPUS.iterdir()):
        toml = d / "task.toml"
        if not toml.is_file():
            continue
        t = tomllib.loads(toml.read_text(encoding="utf-8"))
        meta, env = t.get("metadata", {}), t.get("environment", {})
        agent, verifier = t.get("agent", {}), t.get("verifier", {})
        book[d.name] = {
            "id": d.name,
            "category": meta.get("category", ""),
            "difficulty": meta.get("difficulty", ""),
            "image": env.get("docker_image", ""),
            # Copy each task’s official resource limits into docker run. **Do not relax them.**
            "cpus": str(env.get("cpus", 1)),
            "memory_mb": int(env.get("memory_mb", 2048)),
            # **Use the official time limit when provided**; do not invent another value.
            "seconds": int(float(agent.get("timeout_sec", 900))),
            "verify_seconds": int(float(verifier.get("timeout_sec", 900))),
            "instruction": (d / "instruction.md").read_text(encoding="utf-8"),
            "dir": str(d),
            # Image WORKDIR (automatic in Docker; every Apptainer exec needs explicit --pwd). 86/89 use /app.
            "workdir": workdir_of(d / "environment" / "Dockerfile"),
        }
    return book


BOOK = load_corpus()

# **Tasks that cannot run on this machine: do not submit them, but count them as 0 in the scorecard.**
# Each entry must describe **what was measured**. Currently empty: no measurements yet.
SKIP: dict[str, str] = {}


def pick(n: int, seed: int) -> list[str]:
    r"""Select tasks **deterministically**: the same (n, seed) always selects the same batch."""
    ids = [i for i in sorted(BOOK) if i not in SKIP]
    if not ALLOW_UNSAFE_DIAGNOSTIC:
        ids = [i for i in ids if isolated_verifier.supports(BOOK[i])]
    if n <= 0 or n >= len(ids):
        return ids
    return sorted(random.Random(seed).sample(ids, n))


# ── docker ──────────────────────────────────────────────────────────────────


def apptainer_host_env(source: dict[str, str] | None = None) -> dict[str, str]:
    """--cleanenv does not discard APPTAINERENV injection or configured binds."""
    source = os.environ if source is None else source
    return {k: v for k, v in source.items()
            if not k.startswith(("APPTAINERENV_", "SINGULARITYENV_"))
            and k not in ("APPTAINER_BIND", "APPTAINER_BINDPATH", "SINGULARITY_BIND", "SINGULARITY_BINDPATH")}


def sh(*argv: str, **kw) -> subprocess.CompletedProcess:
    if argv and argv[0] == "apptainer":
        kw["env"] = apptainer_host_env(kw.get("env"))
    kw.setdefault("encoding", "utf-8")
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def require_isolation(tid: str | None = None) -> None:
    """Shared-live tests expose references to solver background processes."""
    if ALLOW_UNSAFE_DIAGNOSTIC:
        return
    if globals().get("LEVEL", 2) >= 3:
        raise RuntimeError("raw verifier failures are not permitted in formal experiments")
    private = globals().get("isolated_verifier")
    if BACKEND == "docker" and private is not None:
        approved = private.supports(BOOK.get(tid, {})) if tid else any(private.supports(task) for task in BOOK.values())
        if approved and private.image_ready() and private.dependency_ready():
            return
    raise RuntimeError("grader isolation is not verified for this task/image; the audited nginx live-state verifier is the only supported formal path")


def task_id_of(name: str) -> str:
    r"""Task ID in `<run-name>/<task-id>`. Without a slash, use the entire string (as in deepswe)."""
    return name.rsplit("/", 1)[-1]


def container_of(place: str) -> str:
    r"""Place string → container name: `tb:[<run-name>/]<task-id>`, **one container per run**."""
    m = re.fullmatch(r"tb:(?:([A-Za-z0-9._-]+)/)?([A-Za-z0-9._-]+)", place or "")
    if not m:
        raise ValueError(f"unrecognised place for this bench: {place} (expected tb:[<run>/]<task-id>)")
    run, tid = m.group(1), m.group(2)
    if tid not in BOOK:
        raise ValueError(f"no such task: {tid}")
    name = f"tb-{run}-{tid}" if run else f"tb-{tid}"
    TID_OF[name] = tid
    return name


# Container name → task ID (task IDs contain hyphens, so splitting the name cannot recover them).
TID_OF: dict[str, str] = {}
CREATED_CONTAINERS: set[str] = set()


def instance_running(name: str) -> bool:
    got = sh("apptainer", "instance", "list", "--json", name)
    try:
        return any(i.get("instance") == name for i in json.loads(got.stdout or "{}").get("instances", []))
    except Exception:
        return False


def exec_argv(name: str, *cmd: str, env: dict[str, str] | None = None) -> list[str]:
    r"""Execute a command argv inside a live container (both backends). `name` is the container name."""
    if BACKEND == "docker":
        e = [x for k, v in (env or {}).items() for x in ("-e", f"{k}={v}")]
        return ["docker", "exec", *e, name, *cmd]
    wd = BOOK[TID_OF[name]]["workdir"] if name in TID_OF else "/app"
    e = [x for k, v in (env or {}).items() for x in ("--env", f"{k}={v}")]
    return ["apptainer", "exec", "--cleanenv", "--no-umask", "--pwd", wd, *e, f"instance://{name}", *cmd]


def cexec(name: str, *cmd: str, env: dict[str, str] | None = None, **kw) -> subprocess.CompletedProcess:
    return sh(*exec_argv(name, *cmd, env=env), **kw)


def upload(name: str, src: Path, dst: str) -> subprocess.CompletedProcess:
    r"""Two backends for `docker cp src/. name:dst`. Apptainer: copy from the host into /stage, then cp into place inside the container."""
    if BACKEND == "docker":
        return sh("docker", "cp", f"{src}/.", f"{name}:{dst}")
    box = STAGE / name / dst.strip("/")
    shutil.rmtree(box, ignore_errors=True)
    try:
        shutil.copytree(src, box)
        for pth in box.rglob("*"):
            try:
                pth.chmod(pth.stat().st_mode | 0o444 | (0o111 if pth.is_dir() else 0))
            except OSError:
                pass
        return cexec(name, "sh", "-c", f"rm -rf {dst} && mkdir -p {dst} && cp -r /stage/{dst.strip('/')}/. {dst}")
    finally:
        # The instance has a persistent bind to this directory. Cleanup must
        # also run after a failed copy; failures invalidate the operation.
        if box.exists():
            shutil.rmtree(box)


def download_verifier(name: str, box: Path) -> None:
    r"""`docker cp name:/logs/verifier/. box`. Apptainer: /logs is bound to the host, so copy directly."""
    if BACKEND == "docker":
        sh("docker", "cp", f"{name}:/logs/verifier/.", str(box))
        return
    src = LOGS / "live" / name / "verifier"
    if src.is_dir():
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, box / f.name)


def remove(name: str) -> None:
    if BACKEND == "docker":
        if not ALLOW_UNSAFE_DIAGNOSTIC and name not in CREATED_CONTAINERS:
            present = sh("docker", "inspect", "--format", "{{.Id}}", name)
            if present.returncode == 0:
                raise RuntimeError("refusing to remove a container not created by this stand process")
            return
        result = sh("docker", "rm", "-f", name)
        if result.returncode:
            raise RuntimeError("cannot remove this stand's candidate container")
        CREATED_CONTAINERS.discard(name)
        return
    sh("apptainer", "instance", "stop", name)
    shutil.rmtree(OVERLAYS / name, ignore_errors=True)
    shutil.rmtree(STAGE / name, ignore_errors=True)


def container_up(place: str) -> str:
    r"""Start the task container if it is not running.

    Follow harbor `docker-compose-prebuilt.yaml`: pinned image + `sh -c "sleep infinity"`. **Do not add `--network none`**: official `allow_internet = true`, and test.sh itself needs network access."""
    name = container_of(place)
    tid = task_id_of(place.split(":", 1)[1])
    require_isolation(tid)
    if BACKEND == "apptainer":
        return instance_up(name, tid)
    with UP_LOCK:
        return docker_container_up(name, tid)


def docker_container_up(name: str, tid: str) -> str:
    """Serialize admission so two HTTP calls cannot exceed the single-candidate cap."""
    got = sh("docker", "inspect", "-f", "{{.State.Running}}", name)
    if got.returncode == 0 and not ALLOW_UNSAFE_DIAGNOSTIC and name not in CREATED_CONTAINERS:
        raise RuntimeError("a container with this task name already exists outside this stand; use a new run ID")
    if got.returncode == 0 and got.stdout.strip() == "true":
        return name
    if got.returncode == 0:
        if sh("docker", "rm", "-f", name).returncode:
            raise RuntimeError("cannot replace this stand's stopped candidate container")
    task = BOOK[tid]
    private_mode = not ALLOW_UNSAFE_DIAGNOSTIC and isolated_verifier.supports(task)
    if private_mode:
        if not runtime_ready():
            raise RuntimeError("the frozen-source Linux runtime assets are missing or changed")
        if shutil.disk_usage(LOGS).free < isolated_verifier.MIN_HOST_FREE_BYTES:
            raise RuntimeError("the host artifact disk has less than the reserved 1 GiB")
        active = sh("docker", "ps", "--filter", "label=objrun.tb.isolated-candidate=v1", "--format", "{{.Names}}")
        if active.returncode or active.stdout.strip():
            raise RuntimeError("isolated TB candidate capacity is occupied; publish one live-service task at a time")
    r = sh(
        "docker", "run", "-d", "--name", name,
        *( ["--pull", "never", "--label", "objrun.tb.isolated-candidate=v1", "--memory-swap", f"{task['memory_mb']}m"] if private_mode else [] ),
        "--cpus", task["cpus"], "--memory", f"{task['memory_mb']}m",
        isolated_verifier.IMAGE_ID if private_mode else task["image"], "sh", "-c", "sleep infinity",
    )
    if r.returncode != 0:
        raise RuntimeError(f"cannot start the container for {tid}: {r.stderr.strip()}")
    CREATED_CONTAINERS.add(name)
    # harbor mounts /logs, so it always exists there; without that mount, create it ourselves.
    try:
        result = sh("docker", "exec", name, "sh", "-c", "mkdir -p /logs/agent /logs/verifier")
        if result.returncode:
            raise RuntimeError("cannot prepare the candidate runtime directories")
        ship_runtime(name)
    except Exception:
        remove(name)
        raise
    return name


UP_LOCK = threading.Lock()


def instance_up(name: str, tid: str) -> str:
    r"""Apptainer container_up: read-only SIF + directory overlay + three binds."""
    require_isolation()
    with UP_LOCK:
        if instance_running(name):
            return name
        sif = IMAGES / f"{tid}.sif"
        if not sif.is_file():
            raise RuntimeError(f"no image for {tid}: {sif} (pull it first)")
        if not RUNTIME.is_file():
            raise RuntimeError(f"the runtime binary is missing: {RUNTIME} (run setup.sh first)")
        ov, stage, logs = OVERLAYS / name, STAGE / name, LOGS / "live" / name
        for d in (ov, stage):
            shutil.rmtree(d, ignore_errors=True)
        (ov / "upper").mkdir(parents=True)
        (ov / "work").mkdir(parents=True)
        stage.mkdir(parents=True)
        (logs / "agent").mkdir(parents=True, exist_ok=True)
        (logs / "verifier").mkdir(parents=True, exist_ok=True)
        r = sh(
            "apptainer", "instance", "start", "--cleanenv", "--fakeroot", "--containall", "--no-home",
            "--overlay", str(ov),
            "-B", f"{RUNTIME}:/rt:ro", "-B", f"{stage}:/stage:ro", "-B", f"{logs}:/logs",
            str(sif), name,
        )
        if r.returncode != 0:
            raise RuntimeError(f"cannot start the instance for {tid}: {r.stderr.strip()[-400:]}")
        # The apt _apt sandbox is unwritable under fakeroot: install a drop-in without modifying the image or test.sh.
        wd = BOOK[tid]["workdir"]
        cexec(name, "sh", "-c", f"mkdir -p {wd} /logs/agent /logs/verifier; {APT_DROPIN}")
        return name


def runtime_ready() -> bool:
    if RUNTIME.is_file():
        return True
    manifest = NODE_RUNTIME / "manifest.json"
    try:
        import hashlib
        expected = json.loads(manifest.read_text(encoding="utf-8"))
        def matches(file: Path, digest: str) -> bool:
            value = hashlib.sha256()
            with file.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    value.update(chunk)
            return value.hexdigest() == digest
        if set(expected["assets"]) != {"node", "runtime.mjs", "libstdc++.so.6", "libgcc_s.so.1"}:
            return False
        root = Path(__file__).resolve().parents[3]
        return (expected["tools"] == ["bash", "edit", "glob", "grep", "read", "write"]
                and all(matches(NODE_RUNTIME / file, digest) for file, digest in expected["assets"].items())
                and all(matches(root / file, digest) for file, digest in expected["frozenSources"].items()))
    except (OSError, ValueError, KeyError):
        return False


def ship_runtime(name: str) -> None:
    r"""Copy the kernel runtime into the container (`dist/tgengin-runtime-linux-x64`, an MCP server)."""
    if not RUNTIME.is_file():
        # Cross-compilation may be unavailable. These six basic tools are the
        # same frozen TypeScript implementation, bundled for the cached Node22.
        required = [NODE_RUNTIME / file for file in ("node", "runtime.mjs", "libstdc++.so.6", "libgcc_s.so.1")]
        if not runtime_ready() or not all(file.is_file() for file in required):
            raise RuntimeError("the frozen-source Linux runtime assets are missing")
        launcher = NODE_RUNTIME / "launcher.sh"
        launcher.write_text("#!/bin/sh\nexport LD_LIBRARY_PATH=/rt-lib\nexec /rt-node /rt-runtime.mjs\n", encoding="utf-8", newline="\n")
        if sh("docker", "exec", name, "mkdir", "-p", "/rt-lib").returncode:
            raise RuntimeError("cannot prepare the Linux runtime library directory")
        for src, dst in [(required[0], "/rt-node"), (required[1], "/rt-runtime.mjs"), (required[2], "/rt-lib/libstdc++.so.6"), (required[3], "/rt-lib/libgcc_s.so.1"), (launcher, "/rt")]:
            result = sh("docker", "cp", str(src), name + ":" + dst)
            if result.returncode:
                raise RuntimeError("cannot ship frozen-source runtime assets")
        if sh("docker", "exec", name, "chmod", "+x", "/rt", "/rt-node").returncode:
            raise RuntimeError("cannot make the Linux runtime executable")
        return
    if sh("docker", "exec", name, "test", "-x", "/rt").returncode == 0:
        return
    r = sh("docker", "cp", str(RUNTIME), f"{name}:/rt")
    if r.returncode != 0:
        raise RuntimeError(f"cannot ship the runtime into {name}: {r.stderr.strip()}")
    sh("docker", "exec", name, "chmod", "+x", "/rt")


# ── Forwarding: speak MCP to the runtime inside the container (copied from deepswe) ──


class Runtime:
    r"""A connection to the runtime in one container. **Each session has one stream**, so requests and responses are serialized under a lock."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.lock = threading.Lock()
        self.next_id = 0
        self.proc = subprocess.Popen(
            ["docker", "exec", "-i", name, "/rt"] if BACKEND == "docker" else exec_argv(name, "/rt"),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1, env=apptainer_host_env() if BACKEND == "apptainer" else None,
        )
        self.rpc("initialize", {"protocolVersion": "2026-07-28"})

    def alive(self) -> bool:
        return self.proc.poll() is None

    def rpc(self, method: str, params: dict) -> dict:
        with self.lock:
            self.next_id += 1
            req = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}
            self.proc.stdin.write(json.dumps(req) + "\n")
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(f"the runtime in {self.name} closed the pipe")
            return json.loads(line)

    def call(self, tool: str, args: dict):
        if not ALLOW_UNSAFE_DIAGNOSTIC and tool not in {"bash", "read", "write", "edit", "glob", "grep"}:
            raise RuntimeError("this audited container path supports the six basic filesystem/shell tools")
        with lock_of(self.name):
            out = self.rpc("tools/call", {"name": tool, "arguments": args})
        if "error" in out:
            raise RuntimeError(str(out["error"].get("message", out["error"])))
        res = out.get("result", {})
        if res.get("isError"):
            text = "".join(c.get("text", "") for c in res.get("content", []))
            raise RuntimeError(text or "the tool failed")
        if "structuredContent" in res:
            return res["structuredContent"]
        text = "".join(c.get("text", "") for c in res.get("content", []))
        try:
            return json.loads(text)
        except Exception:
            return text


RUNTIMES: dict[str, Runtime] = {}
RUNTIMES_LOCK = threading.Lock()


def runtime_of(place: str) -> Runtime:
    name = container_up(place)
    with RUNTIMES_LOCK:
        rt = RUNTIMES.get(name)
        if rt is not None and rt.alive():
            return rt
        rt = Runtime(name)
        RUNTIMES[name] = rt
        return rt


# ── Grading ──


def parse_reward(box: Path) -> float | None:
    r"""Read reward. **Match harbor `Verifier._parse_reward_text` / `_parse_reward_json`**:
    JSON takes precedence; parse text as float; empty, nonnumeric, or nonfinite values mean grading failed (return None)."""
    js, txt = box / "reward.json", box / "reward.txt"
    try:
        if js.is_file():
            if js.stat().st_size == 0:
                return None
            got = json.loads(js.read_text())
            vals = list(got.values()) if isinstance(got, dict) else [got]
            if not vals or any(not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")) for v in vals):
                return None
            # All 89 tasks write reward.txt; retain this branch only to match harbor’s precedence. Use the reward key if present.
            return float(got.get("reward", vals[0])) if isinstance(got, dict) else float(vals[0])
        if txt.is_file():
            if txt.stat().st_size == 0:
                return None
            v = float(txt.read_text())
            return v if v == v and v not in (float("inf"), float("-inf")) else None
    except (ValueError, TypeError):
        return None
    return None


def run_verifier(tid: str, name: str) -> dict:
    r"""Grade once inside the live container. **Official steps** (harbor `Verifier.verify`):

        tests/  →  /tests            (upload_dir)
        chmod +x /tests/test.sh      (as root)
        (/tests/test.sh) > /logs/verifier/test-stdout.txt 2>&1
        /logs/verifier/  →  local    (download_dir)

    Then add one step absent from the official flow: **delete /tests and /logs/verifier**."""
    require_isolation(tid)
    task = BOOK[tid]
    private = globals().get("isolated_verifier")
    if not ALLOW_UNSAFE_DIAGNOSTIC and private is not None and private.supports(task):
        return private.run_verifier(task, name, LOGS)
    tests = Path(task["dir"]) / "tests"
    box = LOGS / f"{tid}-{int(time.time() * 1000)}"
    box.mkdir(parents=True, exist_ok=True)

    cexec(name, "sh", "-c", "rm -rf /tests && mkdir -p /tests /logs/verifier && rm -rf /logs/verifier/*")
    # Use `tests/.`, not `tests`: the latter creates /tests/tests/.
    r = upload(name, tests, "/tests")
    if r.returncode != 0:
        return {"ran": False, "reward": 0.0, "crashed": True, "why": f"cannot upload tests: {r.stderr.strip()[-300:]}", "_tests": []}
    cexec(name, "chmod", "+x", "/tests/test.sh")

    code, timed_out = -1, False
    t0 = time.time()
    try:
        code = cexec(
            name, "sh", "-c", "(/tests/test.sh) > /logs/verifier/test-stdout.txt 2>&1",
            timeout=task["verify_seconds"],
        ).returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        # After a client timeout, test.sh keeps running in the container. Without killing it, it can write a reward
        # minutes later, causing the next grading call to read this run’s result.
        cexec(name, "sh", "-c", "pkill -f /tests/test.sh || true")
    took = round(time.time() - t0, 1)

    download_verifier(name, box)
    # **Delete immediately after collecting.** Hidden tests must not remain in the solver’s container.
    cexec(name, "sh", "-c", "rm -rf /tests /logs/verifier/*; true")

    reward = parse_reward(box)
    out: dict = {"seconds": took, "code": code, "box": str(box)}
    if reward is None:
        # **Distinguish three reasons grading cannot finish** (as in deepswe): OOM / timeout / grader failure.
        why = "oom-killed" if code == 137 else (f"timed out at {task['verify_seconds']}s" if timed_out else f"test.sh exited {code} without a readable reward")
        out.update({"ran": False, "reward": 0.0, "crashed": True, "why": why, "_tests": []})
    else:
        out.update({"ran": True, "reward": reward, "crashed": False})
        ctrf = box / "ctrf.json"
        try:
            out["_tests"] = json.loads(ctrf.read_text()).get("results", {}).get("tests", []) if ctrf.is_file() else []
        except Exception:
            out["_tests"] = []
    return out


# **Grade only one candidate per container at a time.** Concurrent uploads into /tests would prevent either run from seeing a complete test set.
LOCKS: dict[str, threading.Lock] = {}
LOCKS_LOCK = threading.Lock()

# `ran` stores the result here; `passed` reads it immediately afterward. Key = (container, submitted name).
RESULTS: dict[tuple[str, str], tuple[float, dict]] = {}

# **Maximum concurrent grading jobs.** Each task needs 1–4 CPUs and 2–8 GB; the service owns this gate (as in deepswe).
GRADERS = int(os.environ.get("TGENGIN_TB_GRADERS", "4"))
GATE = threading.Semaphore(GRADERS)


def lock_of(name: str) -> threading.Lock:
    with LOCKS_LOCK:
        return LOCKS.setdefault(name, threading.Lock())


def judge(place: str, tid: str, said: str) -> dict:
    r"""Grade a candidate: the container at this moment. **Do not cache**; container state can change every second."""
    name = container_up(place)
    with lock_of(name):
        t0 = time.time()
        with GATE:
            queued = round(time.time() - t0, 1)
            got = run_verifier(tid, name)
        got["queued"] = queued
        with LOCKS_LOCK:
            RESULTS[(name, said)] = (time.time(), got)
    n = len(got.get("_tests", []))
    k = sum(1 for t in got.get("_tests", []) if t.get("status") == "passed")
    print(
        f"[tb] {tid} said={said[:24]!r} ran={got.get('ran')} reward={got.get('reward')} "
        f"tests={k}/{n} took={got.get('seconds', 0)}s queued={queued}s"
        + (f" why={got.get('why')}" if got.get("crashed") else ""),
        flush=True,
    )
    return got


def judged(place: str, said: str) -> dict | None:
    r"""The result just produced by `ran`. Consume it once: the next round evaluates fresh container state."""
    name = container_of(place)
    with LOCKS_LOCK:
        hit = RESULTS.pop((name, said), None)
    if hit is None or time.time() - hit[0] > RESULT_TTL:
        return None
    return hit[1]


# ── note: feedback detail selected by --level ──


def note_of(got: dict) -> dict | str:
    r"""Additional information on verdict 0. **The level controls detail**, while the response structure stays the same."""
    if LEVEL <= 0:
        return ""
    if got.get("crashed"):
        return {"stage": "verifier", "detail": got.get("why", "the verifier produced no reward")}
    tests = got.get("_tests", [])
    failed = [t for t in tests if t.get("status") != "passed"]
    note: dict = {"stage": "tests"}
    if tests:
        note["tests"] = f"{len(tests) - len(failed)} of {len(tests)} pass"
    else:
        note["reward"] = got.get("reward", 0.0)
    if LEVEL <= 1:
        return note
    note["failing"] = ([t.get("name", "") for t in failed] if ALLOW_UNSAFE_DIAGNOSTIC
                       else [f"test#{i + 1}" for i, t in enumerate(tests) if t.get("status") != "passed"])[:60]
    if LEVEL <= 2:
        return note
    # Level 3: raw assertions. CTRF `message` is a one-line summary; `trace` is the full traceback.
    note["failures"] = [
        {"name": t.get("name", ""), "message": (t.get("message") or "")[:2000], "trace": (t.get("trace") or "")[:2000]}
        for t in failed[:40]
    ]
    return note


# ── HTTP ────────────────────────────────────────────────────────────────────


def task_of(body: dict) -> tuple[str, str, str]:
    r"""Extract the task, container, and submitted name from the kernel payload."""
    inp = body.get("input") or {}
    task = inp.get("task") or {}
    tid = task_id_of(str(task.get("id", "")))
    place = str(task.get("place", "") or f"tb:{tid}")
    result = inp.get("result")
    said = result.get("body") if isinstance(result, dict) else result
    if said is None:
        said = task.get("result")
    return tid, place, ("" if said is None else str(said)).strip()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # Suppress the noisy default access log.
        pass

    def _send(self, obj, code=200):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        if not GRADER_TOKEN:
            if ALLOW_UNSAFE_DIAGNOSTIC:
                return True
            self._send({"error": "GraderAuthenticationNotConfigured"}, 503)
            return False
        if not hmac.compare_digest(self.headers.get("X-ObjRun-Grader-Token", ""), GRADER_TOKEN):
            self._send({"error": "Unauthorized"}, 401)
            return False
        return True

    def do_GET(self):
        if self.path == "/health":
            ids = pick(0, 0)
            self._send({"ok": True, "tasks": len(BOOK), "usable": len(ids),
                        "skipped": SKIP, "level": LEVEL, "graders": GRADERS, "backend": BACKEND,
                        "isolationReady": BACKEND == "docker" and not ALLOW_UNSAFE_DIAGNOSTIC and LEVEL < 3 and bool(ids) and isolated_verifier.image_ready() and isolated_verifier.dependency_ready() and runtime_ready(),
                        "supportedTaskIds": ids, "protocol": isolated_verifier.PROTOCOL,
                        "unsupportedTaskCount": len(BOOK) - len(ids), "runtimeReady": runtime_ready(),
                        "runtimeExecutor": "compiled-bun" if RUNTIME.is_file() else "node-22.22.2-frozen-source-bundle",
                        "dependencyMode": "preseeded-offline-fixed" if isolated_verifier.DEPENDENCIES else "cold-network-original-image",
                        "dependencyReady": isolated_verifier.dependency_ready(),
                        "supportedTools": ["bash", "read", "write", "edit", "glob", "grep"],
                        "operationalLimits": {"writableBytesPerContainer": isolated_verifier.MAX_WRITABLE_BYTES,
                                              "captureBytesPerStream": isolated_verifier.MAX_CAPTURE_BYTES,
                                              "hostFreeBytesReserved": isolated_verifier.MIN_HOST_FREE_BYTES},
                        "maxLiveCandidates": 1, "unsafeDiagnostic": ALLOW_UNSAFE_DIAGNOSTIC,
                        "authenticated": bool(GRADER_TOKEN)})
            return
        if self.path.startswith("/problems"):
            if not self._authorized():
                return
            # **Problem endpoint: send the statement, not the answer.** No content from `solution/` is sent.
            n, seed = 0, 0
            if "?" in self.path:
                for kv in self.path.split("?", 1)[1].split("&"):
                    if kv.startswith("n="):
                        n = int(kv[2:] or 0)
                    elif kv.startswith("seed="):
                        seed = int(kv[5:] or 0)
            self._send([
                {
                    "id": i,
                    "category": BOOK[i]["category"],
                    "difficulty": BOOK[i]["difficulty"],
                    "instruction": BOOK[i]["instruction"],
                    "seconds": BOOK[i]["seconds"],
                    "cpus": BOOK[i]["cpus"],
                    "memory_mb": BOOK[i]["memory_mb"],
                    "workdir": BOOK[i]["workdir"],
                }
                for i in pick(n, seed)
            ])
            return
        self._send({"error": f"no {self.path} here"}, 404)

    def do_POST(self):
        if not self._authorized():
            return
        length = int(self.headers.get("content-length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            body = {}

        # ── Place: forward one tool call, or probe liveness ──
        if self.path == "/place":
            place = str(body.get("place", ""))
            try:
                if body.get("op") == "ping":
                    self._send({"alive": runtime_of(place).alive()})
                    return
                self._send(runtime_of(place).call(str(body.get("tool", "")), body.get("args") or {}))
            except Exception as e:
                self._send({"error": str(e)}, 500 if body.get("op") != "ping" else 200)
            return

        # ── U arm: grade final container state once after completion (without G, scorecard only); /stop cleans up ──
        if self.path in ("/grade", "/stop"):
            place = str(body.get("place", ""))
            try:
                tid = task_id_of(place.split(":", 1)[1])
                if self.path == "/stop":
                    remove(container_of(place))
                    self._send({"ok": True})
                    return
                if tid not in BOOK:
                    self._send({'error': 'UnknownTask'}, 422)
                    return
                got = require_result(judge(place, tid, str(body.get("said", "unaided"))))
                got.pop("_tests", None)
                self._send({"reward": got.get("reward", 0.0), "ran": got.get("ran"), **{k: v for k, v in got.items() if k != "reward"}})
            except Exception as e:
                self._send(fault_payload(e), 503)
            return

        # ── The two nodes of G. **Grade once, read in two places.** ──
        if self.path in ("/ran", "/passed"):
            tid, place, said = task_of(body)
            if tid not in BOOK:
                self._send({'error': 'UnknownTask'}, 422)
                return
            # The submission names the candidate; an empty name is allowed and becomes "done".
            said = said or "done"
            try:
                if self.path == "/ran":
                    got = require_result(judge(place, tid, said))
                    ok = bool(got.get("ran"))
                else:
                    # **Root.** Do not repeat an upstream failure.
                    feed = body.get("feed") or []
                    if feed and feed[0].get("value") is not True:
                        self._send({"value": False})
                        return
                    got = require_result(judged(place, said) or judge(place, tid, said))
                    ok = float(got.get("reward", 0.0)) == 1.0
            except Exception as e:
                self._send(fault_payload(e), 503)
                return
            self._send({"value": ok} if ok else {"value": False, "note": note_of(got)})
            return

        self._send({"error": f"no {self.path} here"}, 404)


# ── Self-tests ──


def run_oracle(tid: str, name: str) -> int:
    r"""Follow harbor `OracleAgent.run`: copy `solution/` into `/solution`, run `solve.sh`,
    set `DEBIAN_FRONTEND=noninteractive`, and use the official agent timeout."""
    task = BOOK[tid]
    sol = Path(task["dir"]) / "solution"
    cexec(name, "sh", "-c", "rm -rf /solution && mkdir -p /solution /logs/agent")
    r = upload(name, sol, "/solution")
    if r.returncode != 0:
        raise RuntimeError(f"cannot upload the solution: {r.stderr.strip()[-300:]}")
    cexec(name, "chmod", "+x", "/solution/solve.sh")
    try:
        return cexec(
            name, "sh", "-c", "(/solution/solve.sh) > /logs/agent/oracle.txt 2>&1",
            env={"DEBIAN_FRONTEND": "noninteractive"},
            timeout=task["seconds"],
        ).returncode
    except subprocess.TimeoutExpired:
        return -9


def selftest(ids: list[str]) -> int:
    r"""Two clean containers: one does nothing and should score 0; one runs the reference solution and should score 1. **A faulty installation fails here.**"""
    bad = 0
    for tid in ids:
        empty_place, oracle_place = f"tb:selftest-empty/{tid}", f"tb:selftest-oracle/{tid}"
        a = b = {"reward": -1}
        try:
            for p in (empty_place, oracle_place):
                remove(container_of(p))
            a = run_verifier(tid, container_up(empty_place))
            remove(container_of(empty_place))
            name = container_up(oracle_place)
            run_oracle(tid, name)
            b = run_verifier(tid, name)
        except Exception as e:
            print(f"  FAIL {tid:<40} {e}", flush=True)
        finally:
            for p in (empty_place, oracle_place):
                remove(container_of(p))
        ok = float(a.get("reward", -1)) == 0.0 and float(b.get("reward", -1)) == 1.0
        bad += 0 if ok else 1
        n = len(b.get("_tests", []))
        k = sum(1 for t in b.get("_tests", []) if t.get("status") == "passed")
        print(
            f"  {'ok  ' if ok else 'FAIL'} {tid:<40} [{BOOK[tid]['category']:<22}] "
            f"empty={a.get('reward')} oracle={b.get('reward')} tests={k}/{n} "
            f"({a.get('seconds', 0)}s + {b.get('seconds', 0)}s)",
            flush=True,
        )
    print(f"\n{len(ids) - bad} of {len(ids)} tasks grade their own reference solution as solved")
    return 1 if bad else 0


def main() -> int:
    global LEVEL, GRADERS, GATE, ALLOW_UNSAFE_DIAGNOSTIC
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("TGENGIN_TB_PORT", "7903")))
    ap.add_argument("--level", type=int, default=LEVEL, help="how much the note field says: 0..3")
    ap.add_argument("--graders", type=int, default=GRADERS, help="how many verifiers may run at once")
    ap.add_argument("--unsafe-diagnostic", action="store_true", default=ALLOW_UNSAFE_DIAGNOSTIC,
                    help="allow shared-live grading for diagnosis only; results are not valid isolated experiments")
    ap.add_argument("--selftest", nargs="*", metavar="TASK_ID")
    ap.add_argument("--pull", nargs="*", metavar="TASK_ID", help="pull the images for these tasks (all if none given) and stop")
    a = ap.parse_args()
    ALLOW_UNSAFE_DIAGNOSTIC = a.unsafe_diagnostic
    LEVEL = a.level
    if a.graders != GRADERS:
        GRADERS = a.graders
        GATE = threading.Semaphore(GRADERS)
    if not ALLOW_UNSAFE_DIAGNOSTIC:
        GRADERS = 1
        GATE = threading.Semaphore(1)
    LOGS.mkdir(parents=True, exist_ok=True)

    if a.pull is not None:
        for tid in (a.pull or sorted(BOOK)):
            img = BOOK[tid]["image"]
            if BACKEND == "apptainer":
                sif = IMAGES / f"{tid}.sif"
                have = sif.is_file()
                if not have:
                    IMAGES.mkdir(parents=True, exist_ok=True)
                    r = sh("apptainer", "pull", str(sif), f"docker://{img}")
                    if r.returncode != 0:
                        print(f"  FAIL {tid}: {r.stderr.strip()[-200:]}", flush=True)
                        continue
                print(f"  {'have' if have else 'pull'}  {tid}  {img}", flush=True)
                continue
            have = sh("docker", "image", "inspect", img).returncode == 0
            if not have:
                r = sh("docker", "pull", "-q", img)
                if r.returncode != 0:
                    print(f"  FAIL {tid}: {r.stderr.strip()[-200:]}", flush=True)
                    continue
            print(f"  {'have' if have else 'pull'}  {tid}  {img}", flush=True)
        return 0

    if a.selftest is not None:
        return selftest(a.selftest or pick(4, 0))

    require_isolation()
    if not GRADER_TOKEN and not ALLOW_UNSAFE_DIAGNOSTIC:
        raise SystemExit("TGENGIN_GRADER_TOKEN is required for authenticated grading")

    print(f"[tb] {'UNSAFE DIAGNOSTIC | ' if ALLOW_UNSAFE_DIAGNOSTIC else isolated_verifier.PROTOCOL + ' | '}{len(BOOK)} source tasks, {len(pick(0, 0))} supported | backend {BACKEND} | note level {LEVEL} | {GRADERS} graders at once | "
          f"http://127.0.0.1:{a.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
