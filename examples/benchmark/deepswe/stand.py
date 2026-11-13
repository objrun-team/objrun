r"""DeepSWE service outside the engine. **Apptainer version** for Sherlock; the Docker version is in `stand.py.bak-docker-0929`.

    python3 stand.py [--port 7902] [--level 2] [--graders 4] [--selftest [TASK_ID...] [--jobs 4]] [--pull [TASK_ID...]]

The engine sees **three handles**:

    http://127.0.0.1:7902/place       Forward tool calls into the problem's container.
    http://127.0.0.1:7902/applies     First G node: does the submitted patch apply?
    http://127.0.0.1:7902/resolved    G root: does the official criterion report success?

Two additional endpoints finalize arm U:

    /grade  {place}    Grade `git diff --binary <base> HEAD` in the container (official collect command), without G.
    /stop   {place}    Stop the container and remove its overlay.

Handle names are URLs. The kernel POSTs JSON and receives JSON; there is no additional protocol.

## Why place routing belongs here

The handle referenced by workplace.identity defines how to reach a place (app/src/place/index.ts). Built-in fn:place.hops understands wsl/ssh/docker hop strings; this service uses Apptainer and its own `dsw:<run-name>/<problem-id>` addresses. Container startup and runtime injection stay in this process; the kernel needs no changes.

**Forwarded tools still use the kernel implementation.** `/rt`, bound into the container, is dist/tgengin-runtime-linux-x64: an MCP server containing app/src/tools/.

## Replacing Docker with Apptainer

See $SCRATCH/bench-feas/REPORT-deepswe.md and the 2026-09-29 self-tests for measured behavior.

- One SIF per problem (`images/<tid>.sif`, pulled from its pinned Docker image), with one instance per run.
- Use a **directory overlay** on /lscratch, removed at job completion. Do not use --writable-tmpfs, which consumes memory.
- Use --fakeroot --containall --no-home. **Without --no-home, fakeroot HOME=/root is hidden by empty tmpfs**, removing the image's /root toolchains.
- Use --no-mount tmp: --containall normally replaces /tmp and /var/tmp with memory tmpfs, **hiding the image's /tmp**. goreleaser stores GOMODCACHE/GOCACHE and Go 1.26.1 under /tmp/gomodcache; hiding them triggers network downloads and verdict 0. Without that mount, /tmp uses the image plus overlay on /lscratch and consumes no job memory.
- Use --no-mount /etc/localtime: Apptainer otherwise binds host PDT while Docker uses image UTC, shifting adaptix date tests by one day.
- **Network restriction uses --no-mount /etc/resolv.conf.** Apptainer cannot provide a network namespace here. Omitting the host resolver makes DNS fail with gaierror, matching Docker --network none failure behavior for curl/pip/git/go downloads, while loopback remains available. A prior dead-port HTTP proxy changed botocore errors from EndpointConnectionError to ProxyConnectionError and caused five false-negative gql tests, so it was abandoned. **Literal IPs remain reachable**, which Methods must disclose.
- fakeroot injects LD_PRELOAD=libfakeroot.so and LD_LIBRARY_PATH. Deno refuses child-process spawning with these variables (13 cliffy snapshot tests). Unset them before every container command; root status still comes from the user namespace.
- instance start does not accept --pwd. Every exec uses --pwd /app (the repository location for all 113 problems) and --cleanenv to exclude host service ports/paths from agent bash.
- Do not build grader images. Bind tasks/<tid>/tests to /tests read-only and run bash /tests/test.sh on the problem SIF. Record the tests-directory SHA-256 in results.
- **There is no PID namespace.** Apptainer starter is a child subreaper: when the main exec process exits normally, it reaps all descendants, including setsid/nohup children. SIGKILLing starter instead leaves /rt, faked, or test services orphaned. **Never SIGKILL starter**: close /rt stdin for graceful exit; on timeout kill descendants first and wait for starter to exit (run()).
- Containers share host loopback, making grader/engine ports reachable. Every grader POST checks the peer process's mount namespace and rejects container-origin requests (from_container). Arm-U statements omit handle URLs (send.ts).

### Deviations to disclose in Methods

Relative to the official harness and Docker F arm:
1. No network namespace: DNS is disabled by omitting resolv.conf, but literal IPs and shared host loopback remain reachable; the grader checks request origin.
2. No per-container cgroup limit (official: 2 CPUs, 8 GB). Use the Slurm job limit (33 CPUs, 256 GB) and --graders concurrency cap.
3. No PID namespace: kill -1 inside a container can reach the user's host processes. This has not occurred and cannot be prevented here.
4. /tmp uses an unlimited overlay, unlike official storage_mb=20480.
5. Arm U runs with Sherlock Apptainer; F uses WSL Docker. Both use T=7200 versus official 10800.
6. Model service differs: F (9-02) uses the official DeepSeek API; U uses OpenRouter pinned to BaseTen fp8 after the official V4 flash endpoint was removed on 9-10.

## Official grading unchanged

The official criterion is tests/test.sh + grader.py + config.json + test.patch. This file implements no grading decisions: it starts containers, retrieves patches, runs the official criterion, and reads reward.json.
Grading runs in **a separate clean container** (official environment_mode="separate"): problem SIF, empty overlay, read-only /tests bind. The working container neither participates nor resets, preserving its accumulated work.

## Feedback detail

--level selects note detail. **Each level is a separate experiment**; the engine is unaware of it, and G's structure stays fixed.

    0   Pass/fail only.
    1   Failed stage and counts (e.g. 12/44 new-behavior tests pass; all 2738 existing tests remain intact).
    2   Also names of failed tests.
    3   Also verbatim failure messages.

## solution/ stays inside this process

The reference patch tasks/<id>/solution/solution.patch is used only in self-tests, where it should pass. The official grader does not read it during grading. The corpus is under $TGENGIN_DSW_HOME/deep-swe/tasks and is never bound into a container."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import random
import re
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '_lib'))
from grader_status import require_result, fault_payload, can_cache_result

HOME_DIR = Path(os.environ.get("TGENGIN_DSW_HOME", Path.home() / ".cache" / "tgengin-deepswe"))
CORPUS = HOME_DIR / "deep-swe" / "tasks"
IMAGES = HOME_DIR / "images"
RUNTIME = HOME_DIR / "tgengin-runtime-linux-x64"
LOGS = HOME_DIR / "logs"
# Writable layers for working and grading containers. **Use /lscratch**, the node-local disk cleared when the job ends.
OVERLAYS = Path(os.environ.get("TGENGIN_DSW_OVERLAYS", f"/lscratch/{os.environ.get('USER', 'u')}/tgengin-dsw"))
WORKDIR = "/app"

# Preserve the official 1800-second grading limit (verifier.timeout_sec).
VERIFY_SECONDS = 1800

# Network-restriction switch. TGENGIN_DSW_NETWALL=0 disables it and allows container DNS resolution.
NETWALL = os.environ.get("TGENGIN_DSW_NETWALL", "1") != "0"
NO_MOUNT = ("--no-mount", "/etc/localtime,tmp" + (",/etc/resolv.conf" if NETWALL else ""))
ENV_PRELUDE = "unset LD_PRELOAD LD_LIBRARY_PATH; "

LEVEL = int(os.environ.get("TGENGIN_DSW_LEVEL", "2"))

os.environ.setdefault("APPTAINER_CACHEDIR", "/scratch/users/ehz0002/.apptainer")
os.environ.setdefault("APPTAINER_TMPDIR", f"/lscratch/{os.environ.get('USER', 'u')}/aptmp")

HOST_MNTNS = os.readlink("/proc/self/ns/mnt")


# ── Corpus ──


def load_corpus() -> dict[str, dict]:
    r"""Read metadata for all 113 problems. **Do not read answers**; solution/ is accessed only in self-tests."""
    if not CORPUS.is_dir():
        raise SystemExit(f"the task corpus is missing: {CORPUS}")
    book: dict[str, dict] = {}
    for d in sorted(CORPUS.iterdir()):
        toml = d / "task.toml"
        if not toml.is_file():
            continue
        t = tomllib.loads(toml.read_text(encoding="utf-8"))
        meta, env = t.get("metadata", {}), t.get("environment", {})
        agent = t.get("agent", {})
        book[d.name] = {
            "id": d.name,
            "language": meta.get("language", ""),
            "title": meta.get("display_title", ""),
            "repo": meta.get("repository_url", ""),
            "base_commit": meta.get("base_commit_hash", ""),
            "image": env.get("docker_image", ""),
            # **Use the official time limit when provided** ([agent] timeout_sec), without inventing a replacement. send.ts applies the run cap.
            "seconds": int(float(agent.get("timeout_sec", 10800))),
            "instruction": (d / "instruction.md").read_text(encoding="utf-8"),
            "dir": str(d),
        }
    return book


BOOK = load_corpus()

# Problems that cannot run on this machine are not submitted but **count as 0 in the report**. Removing them from the denominator would no longer measure successes among 113 problems. Document the **measured reason** for every exclusion.
SKIP = {
    "eicrud-keyset-pagination-cursor":
        "needs more than the default 1024 open files: its MongoDB dies with "
        "'MongoServerError: 24: Too many open files' and the reference solution grades 0/14 "
        "(14/14 once nofile is raised). Left as a 0 rather than changing the environment. "
        "(measured on the docker/WSL stand, 2026-09; not in the 112-task F-arm run either)",
}


def pick(n: int, seed: int) -> list[str]:
    r"""Select problems **deterministically**: identical (n, seed) gives the same batch. Remove excluded problems before sampling."""
    ids = [i for i in sorted(BOOK) if i not in SKIP]
    if n <= 0 or n >= len(ids):
        return ids
    return sorted(random.Random(seed).sample(ids, n))


# ── Processes: run a command without leaving orphans on timeout ──


def descendants(pid: int) -> list[int]:
    r"""All descendants of pid, deepest first. Traverse /proc/<pid>/task/*/children; without PID namespaces these are host PIDs."""
    out: list[int] = []
    stack = [pid]
    while stack:
        p = stack.pop()
        kids: list[int] = []
        try:
            for t in os.listdir(f"/proc/{p}/task"):
                with open(f"/proc/{p}/task/{t}/children") as f:
                    kids += [int(x) for x in f.read().split()]
        except OSError:
            continue
        out += kids
        stack += kids
    return out[::-1]


def kill_tree(pid: int, sig=signal.SIGKILL) -> int:
    r"""Kill pid's descendants, not pid itself: it is usually Apptainer starter, which cleans up and exits after observing its main process terminate."""
    n = 0
    for k in descendants(pid):
        try:
            os.kill(k, sig)
            n += 1
        except OSError:
            pass
    return n


class Ran:
    def __init__(self, returncode: int, stdout: str, stderr: str, timed_out: bool) -> None:
        self.returncode, self.stdout, self.stderr, self.timed_out = returncode, stdout, stderr, timed_out


def run(argv: list[str], timeout: float, stdin_text: str | None = None) -> Ran:
    r"""Replacement for subprocess.run. On timeout, **kill descendants first and wait for starter to exit**. subprocess.run SIGKILLs its direct child (starter), leaving test.sh and its services orphaned and able to write reward files to /logs later."""
    p = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = p.communicate(stdin_text, timeout=timeout)
        return Ran(p.returncode, out, err, False)
    except subprocess.TimeoutExpired:
        kill_tree(p.pid)
        try:
            out, err = p.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
        return Ran(-9, out or "", err or "", True)


def sh(*argv: str, timeout: float = 120) -> Ran:
    return run(list(argv), timeout)


# ── Apptainer: start, execute, stop ──


def task_id_of(name: str) -> str:
    r"""Extract the problem ID from <run-name>/<problem-id>; without a slash, the whole string is the problem ID."""
    return name.rsplit("/", 1)[-1]


def container_of(place: str) -> str:
    r"""Map place strings to container names: dsw:[<run-name>/]<problem-id>, with **one container per run**."""
    m = re.fullmatch(r"dsw:(?:([A-Za-z0-9._-]+)/)?([A-Za-z0-9._-]+)", place or "")
    if not m:
        raise ValueError(f"unrecognised place for this bench: {place} (expected dsw:[<run>/]<task-id>)")
    run_, tid = m.group(1), m.group(2)
    if tid not in BOOK:
        raise ValueError(f"no such task: {tid}")
    return f"dsw-{run_}-{tid}" if run_ else f"dsw-{tid}"


def sif_of(tid: str) -> Path:
    sif = IMAGES / f"{tid}.sif"
    if not sif.is_file():
        raise RuntimeError(f"no image for {tid}: {sif} (run pull.sh first)")
    return sif


def instance_running(name: str) -> bool:
    got = sh("apptainer", "instance", "list", "--json", name, timeout=60)
    try:
        return any(i.get("instance") == name for i in json.loads(got.stdout or "{}").get("instances", []))
    except Exception:
        return False


def exec_argv(name: str, *cmd: str, env: dict[str, str] | None = None) -> list[str]:
    r"""Build argv for a command inside a live container. Always include --pwd /app because instance start does not support --pwd and would otherwise default to /. Use --cleanenv to exclude host variables and prepend ENV_PRELUDE to remove fakeroot LD_* variables."""
    e = [x for k, v in {"TGENGIN_DSW_BOX": name, **(env or {})}.items() for x in ("--env", f"{k}={v}")]
    return ["apptainer", "exec", "--cleanenv", "--no-umask", "--pwd", WORKDIR, *e, f"instance://{name}",
            "sh", "-c", ENV_PRELUDE + 'exec "$@"', "sh", *cmd]


def cexec(name: str, *cmd: str, env: dict[str, str] | None = None, timeout: float = 120) -> Ran:
    return run(exec_argv(name, *cmd, env=env), timeout)


START_LOCK = threading.Lock()          # Serialize instance start calls.
NAME_LOCKS: dict[str, threading.Lock] = {}
NAME_LOCKS_LOCK = threading.Lock()


def name_lock(name: str) -> threading.Lock:
    with NAME_LOCKS_LOCK:
        return NAME_LOCKS.setdefault(name, threading.Lock())


def container_up(place: str) -> str:
    r"""Ensure the problem container is running, starting it if necessary with read-only SIF, directory overlay, and /rt bind.

    **Reuse an existing overlay directory**. Its path contains the run name, so a new run gets a new directory while accidental instance loss preserves the same run's workspace. Only /stop removes it."""
    name = container_of(place)
    tid = task_id_of(place.split(":", 1)[1])
    if instance_running(name):
        return name
    with name_lock(name):
        if instance_running(name):
            return name
        sif = sif_of(tid)
        if not RUNTIME.is_file():
            raise RuntimeError(f"the runtime binary is missing: {RUNTIME}")
        ov = OVERLAYS / name
        fresh = not (ov / "upper").is_dir()
        (ov / "upper").mkdir(parents=True, exist_ok=True)
        (ov / "work").mkdir(parents=True, exist_ok=True)
        with START_LOCK:
            r = sh(
                "apptainer", "instance", "start", "--fakeroot", "--containall", "--no-home", *NO_MOUNT,
                "--overlay", str(ov), "-B", f"{RUNTIME}:/rt:ro",
                str(sif), name, timeout=300,
            )
        if r.returncode != 0:
            raise RuntimeError(f"cannot start the instance for {tid}: {r.stderr.strip()[-400:]}")
        settle_git(name)
        print(f"[dsw] up {name} ({'fresh' if fresh else 'reused'} overlay)", flush=True)
        return name


def settle_git(name: str) -> None:
    r"""Images lack Git identity, so git commit would fail. /root/.gitconfig resides in the overlay and persists across exec calls."""
    for kv in (("user.email", "agent@tgengin.local"), ("user.name", "agent")):
        cexec(name, "git", "config", "--global", *kv, timeout=60)
    cexec(name, "git", "config", "--global", "--add", "safe.directory", WORKDIR, timeout=60)


def remove(name: str) -> None:
    r"""Close the runtime connection so /rt exits gracefully and starter reaps agent background processes, then stop the instance and remove the overlay."""
    with RUNTIMES_LOCK:
        rt = RUNTIMES.pop(name, None)
    if rt is not None:
        rt.close()
    sh("apptainer", "instance", "stop", name, timeout=120)
    shutil.rmtree(OVERLAYS / name, ignore_errors=True)


# ── Forwarding: speak MCP to the runtime inside the container ──


class Runtime:
    r"""A connection to the runtime in one container. **Each session has one stream**, so requests and responses are serialized under a lock."""

    INIT_TIMEOUT = 120
    CALL_TIMEOUT = 1500      # Maximum wait for one tool call (/rt bash has its own shorter limit).

    def __init__(self, name: str) -> None:
        self.name = name
        self.lock = threading.Lock()
        self.next_id = 0
        self.buf = b""
        self.proc = subprocess.Popen(
            exec_argv(name, "/rt"),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
        )
        try:
            self.rpc("initialize", {"protocolVersion": "2026-07-28"}, timeout=self.INIT_TIMEOUT)
        except Exception:
            self.close()
            raise

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        r"""Close stdin; /rt exits on EOF and its starter shuts down with it. Kill descendants if it has not exited after ten seconds."""
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            kill_tree(self.proc.pid)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def _readline(self, timeout: float) -> bytes:
        fd = self.proc.stdout.fileno()
        deadline = time.time() + timeout
        while b"\n" not in self.buf:
            left = deadline - time.time()
            if left <= 0:
                raise TimeoutError(f"the runtime in {self.name} did not answer within {timeout}s")
            r, _, _ = select.select([fd], [], [], min(left, 5))
            if not r:
                if not self.alive():
                    raise RuntimeError(f"the runtime in {self.name} exited")
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                raise RuntimeError(f"the runtime in {self.name} closed the pipe")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return line

    def rpc(self, method: str, params: dict, timeout: float | None = None) -> dict:
        with self.lock:
            self.next_id += 1
            req = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}
            self.proc.stdin.write((json.dumps(req) + "\n").encode())
            self.proc.stdin.flush()
            try:
                line = self._readline(timeout or self.CALL_TIMEOUT)
            except TimeoutError:
                # This session is unusable: any late response can no longer be matched. Close it and reopen on the next call.
                self.close()
                raise
            return json.loads(line)

    def call(self, tool: str, args: dict):
        out = self.rpc("tools/call", {"name": tool, "arguments": args})
        if "error" in out:
            raise RuntimeError(str(out["error"].get("message", out["error"])))
        res = out.get("result", {})
        # Return tool execution failures as **results**, not protocol errors: the caller is usually a model and can correct what it sees.
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
    r"""Reuse existing connections. Create a connection under **this task’s own lock**, without blocking other tasks."""
    name = container_up(place)
    with RUNTIMES_LOCK:
        rt = RUNTIMES.get(name)
    if rt is not None and rt.alive():
        return rt
    with name_lock(name):
        with RUNTIMES_LOCK:
            rt = RUNTIMES.get(name)
        if rt is not None and rt.alive():
            return rt
        rt = Runtime(name)
        with RUNTIMES_LOCK:
            RUNTIMES[name] = rt
        return rt


# ── Grading ──


def tests_digest(tid: str) -> str:
    r"""Fingerprint the files under `tests/` and record this in results and logs, so the exact hidden-test version can be checked."""
    h = hashlib.sha256()
    d = Path(BOOK[tid]["dir"]) / "tests"
    for f in sorted(d.rglob("*")):
        if f.is_file():
            h.update(f.name.encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:12]


def patch_of(place: str, tid: str, ref: str, autocommit: bool = False) -> str:
    r"""Collect the submitted commit as a patch with **the official collection command** (`[[verifier.collect]]`), replacing only `HEAD` with the submitted ref.

    **Do not start a container.** No container means that no tool was called for this task, so there is nothing to grade (as in the Docker version: exec into a nonexistent container fails)."""
    name = container_of(place)
    if not instance_running(name):
        raise RuntimeError(f"the container {name} is not running - the task never started, nothing to collect")
    base = BOOK[tid]["base_commit"]
    cexec(name, "git", "config", "--global", "--add", "safe.directory", WORKDIR, timeout=60)
    if autocommit:
        # **Finish the U arm by committing any uncommitted workspace changes.** In the smoke test, all three tasks reached submission without a single commit
        # (the model returned plain text / exhausted its budget, so the engine entered the submission step, which has no tools). The base..HEAD diff was empty and scored 0,
        # measuring commit habits rather than code. The F arm exposes the same problem through grading feedback and can retry; U gets no second chance.
        # Automatic commits are conservative (raise U and reduce Δ); disclose this in Methods.
        c = cexec(name, "sh", "-c", "git add -A && git commit -q -m 'tgengin hand-in' && echo COMMITTED || true", timeout=300)
        AUTOCOMMITTED[name] = "COMMITTED" in (c.stdout or "")
    r = cexec(name, "git", "diff", "--binary", base, ref, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"cannot read {ref} in {name}: {r.stderr.strip()[-300:]}")
    return r.stdout


AUTOCOMMITTED: dict[str, bool] = {}


def wipe(box: Path) -> None:
    r"""Log directory for the previous grading of this same candidate. `/logs` is a bind mount and the files belong to this user, so delete them directly."""
    shutil.rmtree(box, ignore_errors=True)
    if box.exists():
        raise RuntimeError(f"cannot clear the previous log directory: {box}")


def run_verifier(tid: str, patch: str) -> dict:
    r"""Grade once: task SIF + empty overlay + read-only `/tests` bind + `/logs` bind, running `bash /tests/test.sh`.
    One run produces one `reward.json` and one `ctrf.json`, read by both nodes."""
    sif = sif_of(tid)
    tests = Path(BOOK[tid]["dir"]) / "tests"
    key = hashlib.sha256(patch.encode()).hexdigest()[:16]
    box = LOGS / f"{tid}-{key}"
    wipe(box)
    (box / "artifacts").mkdir(parents=True, exist_ok=True)
    (box / "verifier").mkdir(parents=True, exist_ok=True)
    if patch:
        (box / "artifacts" / "model.patch").write_text(patch, encoding="utf-8")
    ov = OVERLAYS / "verify" / f"{tid}-{key}-{threading.get_ident()}"
    shutil.rmtree(ov, ignore_errors=True)
    (ov / "upper").mkdir(parents=True)
    (ov / "work").mkdir(parents=True)

    t0 = time.time()
    try:
        r = run(
            ["apptainer", "exec", "--fakeroot", "--containall", "--no-home", "--no-umask", "--pwd", WORKDIR, *NO_MOUNT,
             "--overlay", str(ov), "-B", f"{tests}:/tests:ro", "-B", f"{box}:/logs",
             "--env", f"TGENGIN_DSW_VERIFY={tid}-{key}",
             str(sif), "bash", "-c", ENV_PRELUDE + "exec bash /tests/test.sh"],
            timeout=VERIFY_SECONDS,
        )
        code, timed_out = r.returncode, r.timed_out
        (box / "verifier" / "test-stdout.txt").write_text((r.stdout + r.stderr)[-200000:], encoding="utf-8")
    finally:
        shutil.rmtree(ov, ignore_errors=True)
    took = round(time.time() - t0, 1)

    reward_file = box / "verifier" / "reward.json"
    base = {"seconds": took, "tests_sha": tests_digest(tid), "f2p_total": 0, "f2p_passed": 0, "p2p_total": 0, "p2p_passed": 0, "_tests": []}
    if timed_out or not reward_file.is_file():
        # **Distinguish three reasons grading cannot finish**: OOM / timeout / grader failure.
        why = f"timed out at {VERIFY_SECONDS}s" if timed_out else ("oom-killed" if code == 137 else f"the verifier exited {code}")
        return {**base, "reward": 0, "crashed": True, "why": why}
    try:
        out = json.loads(reward_file.read_text())
    except Exception as e:
        return {**base, "reward": 0, "crashed": True, "why": f"reward.json unreadable: {e}"}
    out["seconds"] = took
    out["tests_sha"] = base["tests_sha"]
    ctrf = box / "verifier" / "ctrf.json"
    try:
        out["_tests"] = json.loads(ctrf.read_text()).get("results", {}).get("tests", []) if ctrf.is_file() else []
    except Exception:
        out["_tests"] = []
    return out


CACHE: dict[tuple[str, str], dict] = {}
CACHE_LOCK = threading.Lock()

# **Maximum concurrent grading jobs.** With no cgroup limits, the service uses this gate to match the node’s capacity.
GRADERS = int(os.environ.get("TGENGIN_DSW_GRADERS", "4"))
GATE = threading.Semaphore(GRADERS)

# **Only one worker may grade a given patch at a time.** Later requests wait here, then read the cached result.
INFLIGHT: dict[tuple[str, str], threading.Event] = {}


def judge(place: str, tid: str, ref: str, autocommit: bool = False) -> dict:
    r"""Grade a candidate. **The cache key is patch content, not the commit hash.**"""
    try:
        patch = patch_of(place, tid, ref, autocommit=autocommit)
    except Exception as e:
        return {"reward": 0, "no_patch": True, "detail": str(e), "_tests": []}
    key = (tid, hashlib.sha256(patch.encode()).hexdigest())

    while True:
        with CACHE_LOCK:
            hit = CACHE.get(key)
            if hit is not None:
                return hit
            waiting = INFLIGHT.get(key)
            if waiting is None:
                mine = threading.Event()
                INFLIGHT[key] = mine
                break
        waiting.wait(timeout=VERIFY_SECONDS + 100)

    t0 = time.time()
    try:
        if not patch.strip():
            got = {"reward": 0, "empty": True, "_tests": []}
        else:
            with GATE:
                queued = round(time.time() - t0, 1)
                got = run_verifier(tid, patch)
                got["queued"] = queued
        got["_bytes"] = len(patch)
        if can_cache_result(got):
            with CACHE_LOCK:
                CACHE[key] = got
    finally:
        with CACHE_LOCK:
            INFLIGHT.pop(key, None)
        mine.set()
    print(
        f"[dsw] {tid} ref={ref[:12]} reward={got.get('reward')} "
        f"f2p={got.get('f2p_passed')}/{got.get('f2p_total')} "
        f"p2p={got.get('p2p_passed')}/{got.get('p2p_total')} patch={got['_bytes']}B "
        f"took={got.get('seconds', 0)}s queued={got.get('queued', 0)}s"
        + (f" why={got.get('why')}" if got.get("crashed") else "") + (" (empty)" if got.get("empty") else ""),
        flush=True,
    )
    return got


# ── note: feedback detail selected by --level ──


def note_of(tid: str, got: dict) -> dict | str:
    r"""Additional information on verdict 0. **The level controls detail**, while the response structure stays the same."""
    if LEVEL <= 0:
        return ""
    if got.get("no_patch"):
        return {"stage": "collect", "detail": got.get("detail", "")}
    if got.get("empty"):
        return {"stage": "collect", "detail": "the diff from the base commit to the commit you handed in is empty - nothing was committed"}
    if got.get("crashed"):
        return {"stage": "verifier", "detail": "the verifier produced no reward.json"}
    if got.get("apply_failed"):
        return {"stage": "apply", "detail": "the patch does not apply to a pristine checkout of the base commit"}

    note: dict = {
        "stage": "tests",
        "new_behaviours": f"{got.get('f2p_passed', 0)} of {got.get('f2p_total', 0)} pass",
        "existing_tests": f"{got.get('p2p_passed', 0)} of {got.get('p2p_total', 0)} still pass",
    }
    if LEVEL <= 1:
        return note

    tests = got.get("_tests", [])
    failed = [t for t in tests if t.get("status") != "passed"]
    note["failing"] = [t.get("name", "") for t in failed][:60]
    if LEVEL <= 2:
        return note
    note["failures"] = [
        {"name": t.get("name", ""), "message": (t.get("message") or "")[:2000]} for t in failed[:40]
    ]
    return note


# ── HTTP ────────────────────────────────────────────────────────────────────


def from_container(peer_port: int) -> tuple[bool, str]:
    r"""Whether this connection originated inside a container. Containers share the host loopback, so an agent can reach this endpoint with curl from its image.
    Find the process by the connecting local port (`ss -p` can inspect all of this user’s processes), then check whether its mount namespace is the host’s.
    If the process cannot be found or its namespace cannot be read, treat it as a container connection (this user’s host processes are readable)."""
    r = sh("ss", "-tnpH", f"( sport = :{peer_port} )", timeout=10)
    m = re.search(r"pid=(\d+)", r.stdout or "")
    if not m:
        return True, f"no process owns local port {peer_port}"
    pid = m.group(1)
    try:
        ns = os.readlink(f"/proc/{pid}/ns/mnt")
    except OSError as e:
        return True, f"pid {pid}: {e.__class__.__name__}"
    if ns != HOST_MNTNS:
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace")[:80]
        except OSError:
            cmd = "?"
        return True, f"pid {pid} [{cmd}] is in mount namespace {ns}"
    return False, ""


def task_of(body: dict) -> tuple[str, str, str]:
    r"""Extract the task, container, and submitted commit from the payload sent by the kernel."""
    inp = body.get("input") or {}
    task = inp.get("task") or {}
    tid = task_id_of(str(task.get("id", "")))
    place = str(task.get("place", "") or f"dsw:{tid}")
    result = inp.get("result")
    said = result.get("body") if isinstance(result, dict) else result
    if said is None:
        said = task.get("result")
    return tid, place, ("" if said is None else str(said)).strip()


def ref_of(said: str) -> str:
    r"""Extract the commit ref from the submission. **A single SHA is enough**; pass other input unchanged to git."""
    m = re.search(r"\b[0-9a-f]{7,40}\b", said)
    return m.group(0) if m else (said.splitlines()[-1].strip() if said else "")


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

    def do_GET(self):
        if self.path == "/health":
            self._send({"ok": True, "tasks": len(BOOK), "usable": len(BOOK) - len(SKIP),
                        "skipped": SKIP, "level": LEVEL, "graders": GRADERS, "backend": "apptainer",
                        "images": len(list(IMAGES.glob("*.sif"))) if IMAGES.is_dir() else 0,
                        "netwall": NETWALL, "no_mount": NO_MOUNT[1], "overlays": str(OVERLAYS)})
            return
        if self.path.startswith("/problems"):
            # **Problem endpoint: provide the problem statement, not the answer.**
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
                    "language": BOOK[i]["language"],
                    "title": BOOK[i]["title"],
                    "instruction": BOOK[i]["instruction"],
                    "base_commit": BOOK[i]["base_commit"],
                    "seconds": BOOK[i]["seconds"],
                }
                for i in pick(n, seed)
            ])
            return
        self._send({"error": f"no {self.path} here"}, 404)

    def do_POST(self):
        # **Reject all container-originated requests.** Grading, forwarding, and cleanup accept only the engine and arm scripts.
        inside, why = from_container(self.client_address[1])
        if inside:
            print(f"[dsw] refused {self.path} from inside a container: {why}", flush=True)
            self._send({"error": "not from here"}, 403)
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

        # ── U arm: after completion, grade container HEAD once (official collect command: diff base..HEAD), bypassing G; /stop cleans up ──
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
                got = require_result(judge(place, tid, str(body.get("ref") or "HEAD"), autocommit=body.get("autocommit", True) is not False))
                out = {k: v for k, v in got.items() if k != "_tests"}
                out["autocommitted"] = AUTOCOMMITTED.get(container_of(place), False)
                out["ran"] = not (got.get("no_patch") or got.get("crashed") or got.get("empty"))
                out["why"] = got.get("why") or got.get("detail") or ("empty patch" if got.get("empty") else "")
                self._send(out)
            except Exception as e:
                self._send(fault_payload(e), 503)
            return

        # ── The two nodes of G. **Grade once, read in two places.** ──
        if self.path in ("/applies", "/resolved"):
            tid, place, said = task_of(body)
            if tid not in BOOK:
                self._send({'error': 'UnknownTask'}, 422)
                return
            if not said:
                self._send({"value": False, "note": {"stage": "collect", "detail": "nothing was handed in - hand in the commit sha of your work"}})
                return
            try:
                got = require_result(judge(place, tid, ref_of(said)))
                if self.path == "/applies":
                    ok = not (got.get("no_patch") or got.get("empty") or got.get("apply_failed"))
                else:
                    feed = body.get("feed") or []
                    if feed and feed[0].get("value") is not True:
                        self._send({"value": False})
                        return
                    ok = int(got.get("reward", 0)) == 1
            except Exception as e:
                self._send(fault_payload(e), 503)
                return
            self._send({"value": ok} if ok else {"value": False, "note": note_of(tid, got)})
            return

        self._send({"error": f"no {self.path} here"}, 404)


# ── Self-tests ──


def selftest_one(tid: str) -> tuple[str, bool, str]:
    d = Path(BOOK[tid]["dir"])
    try:
        golden = (d / "solution" / "solution.patch").read_text(encoding="utf-8")
        a = run_verifier(tid, "")
        b = run_verifier(tid, golden)
    except Exception as e:
        return tid, False, f"{type(e).__name__}: {str(e)[:200]}"
    ok = int(a.get("reward", -1)) == 0 and int(b.get("reward", -1)) == 1
    line = (f"[{BOOK[tid]['language']:<10}] empty={a.get('reward')} golden={b.get('reward')} "
            f"f2p={b.get('f2p_passed')}/{b.get('f2p_total')} p2p={b.get('p2p_passed')}/{b.get('p2p_total')} "
            f"({a.get('seconds', 0)}s + {b.get('seconds', 0)}s)"
            + (f" why: {a.get('why') or b.get('why')}" if (a.get('crashed') or b.get('crashed')) else "")
            + (" apply_failed" if b.get("apply_failed") else ""))
    return tid, ok, line


def selftest(ids: list[str], jobs: int) -> int:
    r"""The reference solution must score 1 with the official grader; an empty patch must score 0. **A faulty installation fails here.** Run `jobs` tasks concurrently."""
    bad: list[str] = []
    t0 = time.time()
    print(f"selftest: {len(ids)} tasks, {jobs} at a time, no_mount={NO_MOUNT[1]}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        for tid, ok, line in pool.map(selftest_one, ids):
            if not ok:
                bad.append(tid)
            print(f"  {'ok  ' if ok else 'FAIL'} {tid:<52} {line}", flush=True)
    print(f"\n{len(ids) - len(bad)} of {len(ids)} tasks grade their own reference solution as solved ({time.time() - t0:.0f}s)")
    if bad:
        print("FAILED: " + " ".join(bad))
    return 1 if bad else 0


def main() -> int:
    global LEVEL, GRADERS, GATE
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("TGENGIN_DSW_PORT", "7902")))
    ap.add_argument("--level", type=int, default=LEVEL, help="how much the note field says: 0..3")
    ap.add_argument("--graders", type=int, default=GRADERS, help="how many verifier containers may run at once")
    ap.add_argument("--selftest", nargs="*", metavar="TASK_ID")
    ap.add_argument("--jobs", type=int, default=4, help="selftest: how many tasks at a time")
    ap.add_argument("--pull", nargs="*", metavar="TASK_ID", help="pull the images for these tasks (all usable if none given) and stop")
    a = ap.parse_args()
    LEVEL = a.level
    if a.graders != GRADERS:
        GRADERS = a.graders
        GATE = threading.Semaphore(GRADERS)
    LOGS.mkdir(parents=True, exist_ok=True)
    (OVERLAYS / "verify").mkdir(parents=True, exist_ok=True)

    if a.pull is not None:
        IMAGES.mkdir(parents=True, exist_ok=True)
        for tid in (a.pull or pick(0, 0)):
            sif = IMAGES / f"{tid}.sif"
            if sif.is_file():
                print(f"  have  {tid}", flush=True)
                continue
            r = sh("apptainer", "pull", "--disable-cache", str(sif), f"docker://{BOOK[tid]['image']}", timeout=1800)
            print(f"  {'pull' if r.returncode == 0 else 'FAIL'}  {tid}  {r.stderr.strip()[-200:] if r.returncode else ''}", flush=True)
        return 0

    if a.selftest is not None:
        return selftest(a.selftest or pick(4, 0), a.jobs)

    print(f"[dsw] {len(BOOK)} tasks | apptainer | note level {LEVEL} | {GRADERS} graders at once | "
          f"no_mount {NO_MOUNT[1]} | overlays {OVERLAYS} | http://127.0.0.1:{a.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
