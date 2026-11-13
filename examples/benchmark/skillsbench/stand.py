r"""SkillsBench 1.1 service: an HTTP service outside the engine, running on a Docker host (WSL).

2026-10-08 isolation fix: this general service’s Docker snapshots execute candidate-modifiable bash/Python and cannot produce formal scores. Docker snapshots, Apptainer, and level 3 are diagnostic-only with --unsafe-diagnostic. Each diagnostic grading uses independent snapshot, instance, and log names to prevent cross-run overwrites. Formal private-output JPG grading uses a separate repair adapter; its original image, output files, interpreter, and actual control gates are verified separately. Problem, tool, and grading endpoints require the host TGENGIN_GRADER_TOKEN, which is never placed in tasks or containers. Formal level 2 returns stable test#N indices; original test names may contain parameterized expected values and are visible only in diagnostics.

    python3 stand.py [--port 7903] [--level 2] [--skills with|none] [--network official|none]
    python3 stand.py --pick 10 0          Select tasks (for setup.sh).
    python3 stand.py --build [TASK_ID...] Build images.
    python3 stand.py --selftest [TASK_ID...]

The engine sees **three handles**:

    http://127.0.0.1:7903/place       Where to work: forward tool calls into the task container.
    http://127.0.0.1:7903/verified    First node of G: official verifier/test.sh completed and wrote reward.txt.
    http://127.0.0.1:7903/passed      Root of G: reward == 1.0.

Each handle is its own address. The kernel POSTs JSON and receives JSON; there is no additional protocol.

## The candidate is container state

The problem statement fixes output paths (such as `/root/offer_letter_filled.docx`), which the official grader opens directly. The submission string is **ignored**: grading evaluates the files in the container at submission time. First `docker commit` the work container into a snapshot, then start a disposable container, copy official `verifier/` into `/verifier`, and run `test.sh`.

The official harness uses `verifier.service: main`, running in place in the work container. Snapshots serve one purpose: verify can be called several times per round, and test.sh reinstalls dependencies with `apt-get`/`uvx` each time, progressively contaminating the work container. The grader itself is unchanged.

## The official grader, unchanged

`tasks/<id>/verifier/test.sh` (+ pytest `test_outputs.py`) is the official grader; exit code 0 causes `echo 1 > /logs/verifier/reward.txt`. This file implements no grading decisions: it starts containers, snapshots them, runs the official grader, and reads `reward.txt`.

**Pass = reward == 1.0**, as defined by the paper and official oracle gate (`run_benchflow_integration.py:549`). Seven tasks write fractional rewards; leaderboard `mean(reward)` grants partial credit, but this service does not. The fractional reward goes in note.

## Feedback levels: how much this field reveals

    0   Pass/fail only.
    1   + Failed stage + reward value + pytest counts (81 tasks have ctrf.json).
    2   + Failed tests (test names).
    3   + Raw assertions: **leaks ground truth** (many messages contain expected values); upper-bound experiments only.

## Skills are this benchmark’s independent variable

The paper compares the same model with and without skills. `--skills with` copies `environment/skills/` into `/root/skills` and `/root/.claude/skills`, then includes skill names and descriptions in `/problems` for the batch script to append to the problem statement. The official harness injects a system prompt; our solver is not one of those harnesses, so this is our injection method. `--skills none` is the no-skill control. G has the same shape in both runs.

## oracle/ and verifier/ stay within this process

Reference solutions are used only for self-tests. Ground truth stays in `verifier/` and enters only the disposable grading container. **This is not isolation**, however: official work containers use `network_mode: public` for 86/87 tasks, and the entire benchmark is on GitHub. `--network none` is our control; enabling it changes the experiment from the leaderboard’s."""

from __future__ import annotations

import argparse
import hashlib
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
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '_lib'))
from grader_status import require_result, fault_payload

import yaml  # pyyaml installed by setup.sh: task.md frontmatter is YAML, which the standard library does not support.

HOME_DIR = Path(os.environ.get("TGENGIN_SKB_HOME", Path.home() / ".cache" / "tgengin-skillsbench"))
REPO = HOME_DIR / "skillsbench"
TASKS = REPO / "tasks"
RUNTIME = HOME_DIR / "tgengin-runtime-linux-x64"
LOGS = HOME_DIR / "logs"

# ── Backends: Docker or Apptainer (Sherlock) ──
# Keep the grader unchanged; replace only four container operations. Measurements: $SCRATCH/bench-feas/REPORT-skillsbench.md.
#   - Image: Dockerfile → def ($TGENGIN_SKB_HOME/def_of.py, direct spython translation + apt drop-in) → images/<tid>.sif.
#   - Work container: read-only SIF + **directory overlay** (/lscratch) + --containall --no-home (otherwise task files COPYed into /root are hidden).
#   - Snapshot: `cp -a` of the overlay directory (0.1 s), replacing docker commit; grading: disposable exec with snapshot overlay running official test.sh.
#   - Fingerprint: paths + mtime + sizes under upper/, replacing docker diff.
#   - Unavailable: --network none (no network namespace), --cpus/--memory (no cgroups).
BACKEND = os.environ.get("TGENGIN_SKB_BACKEND", "apptainer" if shutil.which("docker") is None and shutil.which("apptainer") else "docker")
IMAGES = HOME_DIR / "images"
DEFS = HOME_DIR / "defs"
STAGE = HOME_DIR / "stage"
OVERLAYS = Path(os.environ.get("TGENGIN_SKB_OVERLAYS", f"/lscratch/{os.environ.get('USER', 'u')}/tgengin-skb"))

LEVEL = int(os.environ.get("TGENGIN_SKB_LEVEL", "2"))
GRADER_TOKEN = os.environ.get("TGENGIN_GRADER_TOKEN", "")
ALLOW_UNSAFE_DIAGNOSTIC = os.environ.get("TGENGIN_UNSAFE_DIAGNOSTIC", "") == "1"
SKILLS = os.environ.get("TGENGIN_SKB_SKILLS", "with")      # with | none
NETWORK = os.environ.get("TGENGIN_SKB_NETWORK", "official")  # official | none

if shutil.which("docker") is None and Path("/snap/bin/docker").exists():
    os.environ["PATH"] = "/snap/bin:" + os.environ.get("PATH", "")


# ── Corpus ──


def split_task_md(text: str) -> tuple[dict, str]:
    r"""`task.md` = `---` YAML frontmatter `---` problem statement. The statement is everything the agent sees."""
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError("task.md has no frontmatter")
    return yaml.safe_load(m.group(1)) or {}, m.group(2).strip()


def workdir_of(dockerfile: Path) -> str:
    r"""The last Dockerfile WORKDIR is the agent’s cwd (66 tasks use /root, 15 use /app…).

    A variable form (`WORKDIR ${WORKSPACE}`) is captured literally; only one task has this. See the unverified items in G.md."""
    wd = "/root"
    for line in dockerfile.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\s*WORKDIR\s+(\S+)", line)
        if m:
            wd = m.group(1)
    return wd


def skills_of(d: Path) -> list[dict]:
    r"""Each skill’s name and description (SKILL.md frontmatter). **Send only these two fields**; the solver reads the body itself."""
    out = []
    for s in sorted((d / "environment" / "skills").glob("*/SKILL.md")):
        try:
            fm, _ = split_task_md(s.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            fm = {}
        out.append({"name": str(fm.get("name") or s.parent.name), "description": str(fm.get("description") or "")})
    return out


def load_corpus() -> dict[str, dict]:
    r"""Load metadata for all 87 tasks. **Read neither oracle/ nor verifier/**; copy them into a disposable container only during grading."""
    if not TASKS.is_dir():
        raise SystemExit(f"the task corpus is missing: {TASKS} (run setup.sh first)")
    book: dict[str, dict] = {}
    for d in sorted(TASKS.iterdir()):
        md = d / "task.md"
        if not md.is_file():
            continue
        fm, body = split_task_md(md.read_text(encoding="utf-8"))
        meta, env = fm.get("metadata", {}) or {}, fm.get("environment", {}) or {}
        book[d.name] = {
            "id": d.name,
            "category": str(meta.get("category", "")),
            "difficulty": str(meta.get("difficulty", "")),
            "instruction": body,
            # **Use the official time limit when provided**; do not invent another value.
            "seconds": int(float((fm.get("agent") or {}).get("timeout_sec", 1800))),
            "verify_seconds": int(float((fm.get("verifier") or {}).get("timeout_sec", 1800))),
            "cpus": str(env.get("cpus", 1)),
            "memory": f"{int(env.get('memory_mb', 4096))}m",
            # Only bike-rebalance among the 87 tasks has no-network; the rest are public.
            "network": str(env.get("network_mode", "public")),
            "workdir": workdir_of(d / "environment" / "Dockerfile"),
            "skills": skills_of(d),
            "dir": str(d),
        }
    return book


BOOK = load_corpus()

# **Tasks that cannot run on this machine.** Do not submit them; count them as 0 in the scorecard. Each entry must describe what was measured.
# Method: `stand.py --selftest` (empty container scores 0 and official oracle scores 1), three rounds on 2026-09-28/29, recorded in
# $TGENGIN_SKB_HOME/{selftest.out,selftest3.out}. Of 87 tasks, 76 passed, 9 failed self-tests, and 2 lacked translated Apptainer definitions.
SKIP: dict[str, str] = {
    # Self-test failures: the official oracle does not score 1.0 in the Apptainer container.
    "crystallographic-wyckoff-position-analysis": "selftest: oracle=0.0",
    "exceltable-in-ppt": "selftest: oracle=0.0",
    "fix-druid-loophole-cve": "selftest: verifier exited 255 without writing reward.txt (oracle=0.0)",
    "fix-erlang-ssh-cve": "selftest: oracle=0.0",
    "gravitational-wave-detection": "selftest: oracle=0.0",
    "python-scala-translation": "selftest: oracle=0.0",
    "setup-fuzzing-py": "selftest: oracle=0.66 (partial credit only)",
    # Image cannot be built.
    "debug-trl-grpo": "image build: downloads HF model at build time, no network in apptainer build",
    "lean4-proof": "image build: elan installs into host $HOME, `lean: not found` in container",
    # Multistage Dockerfile / bugswarm base not translated by def_of.py.
    "fix-build-agentops": "no apptainer def: multi-stage / bugswarm base image not translated",
    "fix-build-google-auto": "no apptainer def: multi-stage / bugswarm base image not translated",
}


def pick(n: int, seed: int) -> list[str]:
    r"""Select problems **deterministically**: identical (n, seed) gives the same batch. Remove excluded problems before sampling."""
    ids = [i for i in sorted(BOOK) if i not in SKIP]
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
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def require_isolation() -> None:
    if ALLOW_UNSAFE_DIAGNOSTIC:
        return
    if BACKEND != "docker":
        raise RuntimeError("formal SkillsBench grader isolation is disabled: Apptainer shares host network/process access; this generic stand only supports explicit --unsafe-diagnostic")
    raise RuntimeError("formal SkillsBench grading is disabled: the Docker snapshot executes candidate-controlled bash/Python; use a separately verified original-image output grader, or explicit --unsafe-diagnostic for old diagnostics")


def isolation_status() -> dict:
    return {"isolationReady": False, "formalGradingEnabled": False, "supportedTaskIds": [],
            "isolationReason": "Docker snapshot executes candidate-controlled bash/Python" if BACKEND == "docker" else "Apptainer host network/process boundary is unverified",
            "protocol": "skb-generic-snapshot-diagnostic-only", "unsafeDiagnostic": ALLOW_UNSAFE_DIAGNOSTIC}


def task_id_of(name: str) -> str:
    r"""Task ID in `<run-name>/<task-id>`. As in deepswe, task.id is globally unique while the task identifier remains constant across runs."""
    return name.rsplit("/", 1)[-1]


def container_of(place: str) -> str:
    r"""Place string → container name: `skb:[<run-name>/]<task-id>`, one container per run."""
    m = re.fullmatch(r"skb:(?:([A-Za-z0-9._-]+)/)?([A-Za-z0-9._-]+)", place or "")
    if not m:
        raise ValueError(f"unrecognised place for this bench: {place} (expected skb:[<run>/]<task-id>)")
    run, tid = m.group(1), m.group(2)
    if tid not in BOOK:
        raise ValueError(f"no such task: {tid}")
    name = f"skb-{run}-{tid}" if run else f"skb-{tid}"
    TID_OF[name] = tid
    return name


TID_OF: dict[str, str] = {}


def env_digest(tid: str) -> str:
    r"""Fingerprint `environment/` for the image tag. Using only the name would silently reuse an old image after a corpus update."""
    h = hashlib.sha256()
    d = Path(BOOK[tid]["dir"]) / "environment"
    for f in sorted(d.rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(d)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:12]


def task_image(tid: str) -> str:
    r"""Task image: official `environment/Dockerfile`, with `environment/` as context. **There is no official registry; build every image locally.**"""
    if BACKEND == "apptainer":
        sif = IMAGES / f"{tid}.sif"
        if sif.is_file():
            return str(sif)
        d = Path(BOOK[tid]["dir"]) / "environment"
        deff = DEFS / f"{tid}.def"
        if not deff.is_file():
            raise RuntimeError(f"no def for {tid}: {deff} (def_of.py could not translate its Dockerfile)")
        print(f"[skb] building {sif} …", flush=True)
        IMAGES.mkdir(parents=True, exist_ok=True)
        r = sh("apptainer", "build", "--force", "--fakeroot", str(sif), str(deff), cwd=str(d), timeout=3600)
        if r.returncode != 0:
            raise RuntimeError(f"cannot build the image for {tid}: {r.stderr.strip()[-400:]}")
        return str(sif)
    tag = f"skb-task-{tid}:{env_digest(tid)}"
    if sh("docker", "image", "inspect", tag).returncode == 0:
        return tag
    d = Path(BOOK[tid]["dir"]) / "environment"
    print(f"[skb] building {tag} …", flush=True)
    r = sh("docker", "build", "-q", "-t", tag, str(d), timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(f"cannot build the image for {tid}: {r.stderr.strip()[-400:]}")
    return tag


def network_of(tid: str) -> str:
    r"""If `--network none` is enabled, use none for every task; otherwise follow each task’s official declaration."""
    if NETWORK == "none" or BOOK[tid]["network"] == "no-network":
        return "none"
    return "bridge"


def container_up(place: str) -> str:
    r"""Start the task container if it is not running. Follow official task.md for CPU, memory, and network settings."""
    require_isolation()
    name = container_of(place)
    tid = task_id_of(place.split(":", 1)[1])
    if BACKEND == "apptainer":
        return instance_up(name, tid)
    got = sh("docker", "inspect", "-f", "{{.State.Running}}", name)
    if got.returncode == 0 and got.stdout.strip() == "true":
        return name
    if got.returncode == 0:
        sh("docker", "rm", "-f", name)
    it = BOOK[tid]
    r = sh(
        "docker", "run", "-d", "--name", name,
        "--network", network_of(tid), "--cpus", it["cpus"], "--memory", it["memory"],
        "-w", it["workdir"],
        task_image(tid), "sleep", "infinity",
    )
    if r.returncode != 0:
        raise RuntimeError(f"cannot start the container for {tid}: {r.stderr.strip()}")
    ship_runtime(name)
    if SKILLS == "with":
        ship_skills(name, tid)
    return name


UP_LOCK = threading.Lock()


def instance_running(name: str) -> bool:
    got = sh("apptainer", "instance", "list", "--json", name)
    try:
        return any(i.get("instance") == name for i in json.loads(got.stdout or "{}").get("instances", []))
    except Exception:
        return False


def exec_argv(name: str, *cmd: str) -> list[str]:
    wd = BOOK[TID_OF[name]]["workdir"] if name in TID_OF else "/root"
    return ["apptainer", "exec", "--cleanenv", "--no-umask", "--pwd", wd, f"instance://{name}", *cmd]


def cexec(name: str, *cmd: str, **kw) -> subprocess.CompletedProcess:
    return sh(*exec_argv(name, *cmd), **kw)


def instance_up(name: str, tid: str) -> str:
    r"""Apptainer container_up: read-only SIF + directory overlay + /rt and /stage binds. Place skills in upper/ before startup."""
    require_isolation()
    with UP_LOCK:
        if instance_running(name):
            return name
        sif = task_image(tid)
        if not RUNTIME.is_file():
            raise RuntimeError(f"the runtime binary is missing: {RUNTIME} (run setup.sh first)")
        ov, stage = OVERLAYS / name, STAGE / name
        for d in (ov, stage):
            shutil.rmtree(d, ignore_errors=True)
        (ov / "upper").mkdir(parents=True)
        (ov / "work").mkdir(parents=True)
        stage.mkdir(parents=True)
        if SKILLS == "with":
            src = Path(BOOK[tid]["dir"]) / "environment" / "skills"
            if src.is_dir():
                for dst in ("root/skills", "root/.claude/skills"):
                    shutil.copytree(src, ov / "upper" / dst, dirs_exist_ok=True)
        r = sh(
            "apptainer", "instance", "start", "--cleanenv", "--fakeroot", "--containall", "--no-home",
            "--overlay", str(ov), "-B", f"{RUNTIME}:/rt:ro", "-B", f"{stage}:/stage:ro",
            sif, name,
        )
        if r.returncode != 0:
            raise RuntimeError(f"cannot start the instance for {tid}: {r.stderr.strip()[-400:]}")
        cexec(name, "sh", "-c", f"mkdir -p {BOOK[tid]['workdir']} /logs/agent /logs/verifier")
        return name


def upload(name: str, src: Path, dst: str) -> subprocess.CompletedProcess:
    r"""`docker cp src/. name:dst`: Apptainer transfers through /stage."""
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
        if box.exists():
            shutil.rmtree(box)


def remove(name: str) -> None:
    if BACKEND == "docker":
        sh("docker", "rm", "-f", name)
        return
    sh("apptainer", "instance", "stop", name)
    shutil.rmtree(OVERLAYS / name, ignore_errors=True)
    shutil.rmtree(STAGE / name, ignore_errors=True)


def ship_runtime(name: str) -> None:
    r"""Copy the kernel’s runtime into the container (an MCP server with the same tools as the kernel host)."""
    if not RUNTIME.is_file():
        raise RuntimeError(f"the runtime binary is missing: {RUNTIME} (run setup.sh first)")
    if sh("docker", "exec", name, "test", "-x", "/rt").returncode == 0:
        return
    r = sh("docker", "cp", str(RUNTIME), f"{name}:/rt")
    if r.returncode != 0:
        raise RuntimeError(f"cannot ship the runtime into {name}: {r.stderr.strip()}")
    sh("docker", "exec", name, "chmod", "+x", "/rt")


def ship_skills(name: str, tid: str) -> None:
    r"""Copy `environment/skills/` into two container paths: `/root/skills` (referenced by the problem statement) and `/root/.claude/skills` (the agentskills convention).

    Official CONTRIBUTING says not to bake skills into images but to inject them at harness runtime; this is that injection."""
    src = Path(BOOK[tid]["dir"]) / "environment" / "skills"
    if not src.is_dir():
        return
    for dst in ("/root/skills", "/root/.claude/skills"):
        sh("docker", "exec", name, "mkdir", "-p", dst)
        r = sh("docker", "cp", f"{src}/.", f"{name}:{dst}")
        if r.returncode != 0:
            raise RuntimeError(f"cannot ship skills into {name}: {r.stderr.strip()}")


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
            text=True, bufsize=1, env=apptainer_host_env() if BACKEND == "apptainer" else None,
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


def wipe(box: Path, image: str) -> None:
    r"""Clear the previous log directory. Grading containers create /logs directories as root, so an ordinary host user cannot delete them; use a container."""
    shutil.rmtree(box, ignore_errors=True)
    if box.exists() and BACKEND == "docker":
        sh("docker", "run", "--rm", "--network", "none", "-v", f"{box}:/logs", image,
           "sh", "-c", "rm -rf /logs/..?* /logs/.[!.]* /logs/*")
        shutil.rmtree(box, ignore_errors=True)
    if box.exists():
        raise RuntimeError(f"cannot clear the previous log directory: {box}")


def run_verifier(tid: str, image: str, key: str) -> dict:
    r"""Run the official grader on `image` (a work-container snapshot, or the original image during self-tests).

    Follow the official harness: `verifier/` → `/verifier`, run `bash /verifier/test.sh`, then read `/logs/verifier/reward.txt`. Add `cleanup_conftests` (enabled as hardening in all 87 task.md files): remove agent-created `conftest.py` before grading, since a single conftest can hijack pytest. BenchFlow’s exact removal scope was not found; here remove only top-level files in /, cwd, and /root (see unverified items in G.md)."""
    require_isolation()
    it = BOOK[tid]
    box = LOGS / f"{tid}-{key}"
    wipe(box, image)
    (box / "verifier").mkdir(parents=True, exist_ok=True)
    os.chmod(box, 0o777)
    os.chmod(box / "verifier", 0o777)

    name = f"skb-verify-{tid}-{key}"
    if BACKEND == "apptainer":
        return run_verifier_apptainer(tid, image, key, box)
    sh("docker", "rm", "-f", name)
    # **Remove only top-level files** (one level in /, cwd, and /root): these locations can hijack pytest in /verifier.
    # Recursive deletion would also remove the task repository’s own conftest.py and break software-engineering grading.
    cleanup = f"find / {it['workdir']} /root -maxdepth 1 -name conftest.py -type f -delete 2>/dev/null; "
    r = sh(
        "docker", "create", "--name", name,
        # Use the work container’s network settings for grading: 57 test.sh scripts need apt-get / curl uv and fail themselves without network access.
        "--network", network_of(tid), "--cpus", it["cpus"], "--memory", it["memory"],
        "-v", f"{box}:/logs", "-w", it["workdir"],
        image, "bash", "-c", cleanup + "bash /verifier/test.sh",
    )
    if r.returncode != 0:
        return {"reward": 0.0, "crashed": True, "why": f"cannot create the verifier container: {r.stderr.strip()[-300:]}"}
    r = sh("docker", "cp", f"{Path(it['dir']) / 'verifier'}/.", f"{name}:/verifier")
    if r.returncode != 0:
        sh("docker", "rm", "-f", name)
        return {"reward": 0.0, "crashed": True, "why": f"cannot copy the verifier in: {r.stderr.strip()[-300:]}"}

    # Use the task’s official `verifier.timeout_sec` unchanged. Do not raise on timeout: failure to read
    # reward.txt already leads to 0 through the existing path.
    code, timed_out = -1, False
    t0 = time.time()
    try:
        r = sh("docker", "start", "-a", name, timeout=it["verify_seconds"])
        code = r.returncode
        (box / "verifier" / "test-stdout.txt").write_text(r.stdout[-200000:], encoding="utf-8")
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        sh("docker", "rm", "-f", name)
    took = round(time.time() - t0, 1)

    reward_file = box / "verifier" / "reward.txt"
    out: dict = {"seconds": took, "exit": code}
    if not reward_file.is_file():
        # Distinguish three missing-result causes: OOM (137), timeout, and grader failure.
        out.update(reward=0.0, crashed=True,
                   why="oom-killed" if code == 137 else (f"timed out at {it['verify_seconds']}s" if timed_out else f"the verifier exited {code} without writing reward.txt"))
        return out
    try:
        out["reward"] = float(reward_file.read_text().strip())
    except ValueError:
        out.update(reward=0.0, crashed=True, why=f"reward.txt is not a number: {reward_file.read_text()[:40]!r}")
        return out
    ctrf = box / "verifier" / "ctrf.json"
    try:
        out["_tests"] = json.loads(ctrf.read_text()).get("results", {}).get("tests", []) if ctrf.is_file() else []
    except Exception:
        out["_tests"] = []
    return out


def finish_verifier(it: dict, box: Path, code: int, timed_out: bool, took: float) -> dict:
    r"""Read reward.txt (shared finalization for both backends)."""
    reward_file = box / "verifier" / "reward.txt"
    out: dict = {"seconds": took, "exit": code}
    if not reward_file.is_file():
        out.update(reward=0.0, crashed=True,
                   why="oom-killed" if code == 137 else (f"timed out at {it['verify_seconds']}s" if timed_out else f"the verifier exited {code} without writing reward.txt"))
        return out
    try:
        out["reward"] = float(reward_file.read_text().strip())
    except ValueError:
        out.update(reward=0.0, crashed=True, why=f"reward.txt is not a number: {reward_file.read_text()[:40]!r}")
        return out
    ctrf = box / "verifier" / "ctrf.json"
    try:
        out["_tests"] = json.loads(ctrf.read_text()).get("results", {}).get("tests", []) if ctrf.is_file() else []
    except Exception:
        out["_tests"] = []
    return out


def run_verifier_apptainer(tid: str, image: str, key: str, box: Path) -> dict:
    r"""Apptainer version: `image` is a SIF; the snapshot overlay is OVERLAYS/snap/<tid>-<key> (copied by judge; may be absent in self-tests, meaning an empty overlay)."""
    require_isolation()
    it = BOOK[tid]
    snap = OVERLAYS / "snap" / f"{tid}-{key}"
    if not snap.is_dir():
        (snap / "upper").mkdir(parents=True)
        (snap / "work").mkdir(parents=True)
    cleanup = f"find / {it['workdir']} /root -maxdepth 1 -name conftest.py -type f -delete 2>/dev/null; "
    code, timed_out = -1, False
    t0 = time.time()
    try:
        r = sh(
            "apptainer", "exec", "--cleanenv", "--fakeroot", "--containall", "--no-home", "--no-umask", "--pwd", it["workdir"],
            "--overlay", str(snap), "-B", f"{Path(it['dir']) / 'verifier'}:/verifier:ro", "-B", f"{box}:/logs",
            image, "bash", "-c", cleanup + "bash /verifier/test.sh",
            timeout=it["verify_seconds"],
        )
        code = r.returncode
        (box / "verifier" / "test-stdout.txt").write_text((r.stdout + r.stderr)[-200000:], encoding="utf-8")
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        shutil.rmtree(snap, ignore_errors=True)
    return finish_verifier(it, box, code, timed_out, round(time.time() - t0, 1))


CACHE_LOCK = threading.Lock()
INFLIGHT: dict[str, threading.Event] = {}
# Serialize grading per live container; each request uses an independent snapshot, log directory, and grading container.
# A path fingerprint neither proves equal content nor isolates identically named candidates from different runs.

GRADERS = int(os.environ.get("TGENGIN_SKB_GRADERS", "4"))
GATE = threading.Semaphore(GRADERS)


def judge(place: str, tid: str) -> dict:
    r"""Grade a candidate: take a fresh snapshot → run the official grader → read reward; never reuse decisions about mutable state."""
    try:
        require_isolation()
        name = container_up(place)
    except Exception as e:
        return {"reward": 0.0, "crashed": True, "why": f"no container: {e}"}
    key = name

    while True:
        with CACHE_LOCK:
            waiting = INFLIGHT.get(key)
            if waiting is None:
                mine = threading.Event()
                INFLIGHT[key] = mine
                break
        waiting.wait(timeout=BOOK[tid]["verify_seconds"] + 120)

    t0 = time.time()
    request_id = uuid.uuid4().hex
    snap = f"skb-cand-{tid}:{request_id}"
    # Service failures (such as an undeletable log directory) must also return a dictionary scoring 0, not propagate to HTTP.
    # Otherwise the connection closes and the kernel sees only an unanswered handle, unable to distinguish a wrong answer from a broken service.
    got: dict = {"reward": 0.0, "crashed": True, "why": "the stand failed before judging"}
    try:
        with GATE:
            queued = round(time.time() - t0, 1)
            if BACKEND == "apptainer":
                snapdir = OVERLAYS / "snap" / f"{tid}-{request_id}"
                shutil.rmtree(snapdir, ignore_errors=True)
                snapdir.parent.mkdir(parents=True, exist_ok=True)
                r = sh("cp", "-a", str(OVERLAYS / name), str(snapdir))
                image = task_image(tid)
            else:
                r = sh("docker", "commit", name, snap)
                image = snap
            if r.returncode != 0:
                got = {"reward": 0.0, "crashed": True, "why": f"cannot snapshot the container: {r.stderr.strip()[-200:]}"}
            else:
                try:
                    got = run_verifier(tid, image, request_id)
                except Exception as e:
                    got = {"reward": 0.0, "crashed": True, "why": f"the stand failed while judging: {e}"}
                finally:
                    if BACKEND == "docker":
                        sh("docker", "rmi", "-f", snap)
            got["queued"] = queued
    finally:
        with CACHE_LOCK:
            INFLIGHT.pop(key, None)
        mine.set()
    tests = got.get("_tests", [])
    print(
        f"[skb] {tid} reward={got.get('reward')} tests={sum(1 for t in tests if t.get('status') == 'passed')}/{len(tests)} "
        f"took={got.get('seconds', 0)}s queued={got.get('queued', 0)}s"
        + (f" crashed: {got.get('why')}" if got.get("crashed") else ""),
        flush=True,
    )
    return got


# ── note: feedback detail selected by --level ──


def note_of(tid: str, got: dict) -> dict | str:
    r"""Additional information on verdict 0. **The level controls detail**, while the response structure stays the same."""
    if LEVEL <= 0:
        return ""
    if got.get("crashed"):
        return {"stage": "verifier", "detail": got.get("why", "")}
    tests = got.get("_tests", [])
    note: dict = {
        "stage": "tests",
        "reward": got.get("reward"),
        "tests": f"{sum(1 for t in tests if t.get('status') == 'passed')} of {len(tests)} pass" if tests else "(no per-test report)",
    }
    if LEVEL <= 1:
        return note
    failed = [t for t in tests if t.get("status") != "passed"]
    # Pytest parameter names can contain the expected answer even without a
    # failure message. Keep stable identities without exposing raw test names.
    note["failing"] = ([t.get("name", "") for t in failed][:60] if ALLOW_UNSAFE_DIAGNOSTIC
                       else [f"test#{i + 1}" for i, t in enumerate(tests) if t.get("status") != "passed"][:60])
    if LEVEL <= 2:
        return note
    # **Level 3 leaks ground truth**: many assertion messages contain expected values. Use only for upper-bound experiments.
    note["failures"] = [{"name": t.get("name", ""), "message": (t.get("message") or "")[:2000]} for t in failed[:40]]
    return note


# ── HTTP ────────────────────────────────────────────────────────────────────


def task_of(body: dict) -> tuple[str, str]:
    r"""The kernel sends `{node, moment, domain, feed, input}`; `input.task.id` is `<run-name>/<task-id>`. Ignore submission content."""
    task = (body.get("input") or {}).get("task") or {}
    tid = task_id_of(str(task.get("id", "")))
    place = str(task.get("place", "") or f"skb:{tid}")
    return tid, place


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
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
            self._send({"ok": True, "tasks": len(BOOK), "usable": 0, "diagnosticUsable": len(BOOK) - len(SKIP), "skipped": SKIP,
                        "level": LEVEL, "skills": SKILLS, "network": NETWORK, "graders": GRADERS, "backend": BACKEND,
                        **isolation_status(), "authenticated": bool(GRADER_TOKEN)})
            return
        if self.path.startswith("/problems"):
            if not self._authorized():
                return
            # **Problem endpoint: send the statement, not the answer.** No content from oracle/ or verifier/ is sent.
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
                    "workdir": BOOK[i]["workdir"],
                    "seconds": BOOK[i]["seconds"],
                    # Provide skill names and descriptions only in the skills-enabled run; the solver reads the bodies in container /root/skills.
                    "skills": BOOK[i]["skills"] if SKILLS == "with" else [],
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

        # ── Grade the U arm once after completion (without G); /stop cleans up ──
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
                got = dict(require_result(judge(place, tid)))
                got.pop("_tests", None)
                self._send(got)
            except Exception as e:
                self._send(fault_payload(e), 503)
            return

        # ── The two nodes of G. **Grade once, read in two places.** ──
        if self.path in ("/verified", "/passed"):
            tid, place = task_of(body)
            if tid not in BOOK:
                self._send({'error': 'UnknownTask'}, 422)
                return
            try:
                got = require_result(judge(place, tid))
                if self.path == "/verified":
                    ok = True
                else:
                    feed = body.get("feed") or []
                    if feed and feed[0].get("value") is not True:
                        self._send({"value": False})
                        return
                    ok = abs(float(got.get("reward", 0.0)) - 1.0) < 1e-9
            except Exception as e:
                self._send(fault_payload(e), 503)
                return
            # **Return `{"value": bool}`.** The value domain is closed; other responses violate the contract and the kernel maps them to 0.
            self._send({"value": True} if ok else {"value": False, "note": note_of(tid, got)})
            return

        self._send({"error": f"no {self.path} here"}, 404)


# ── Self-tests ──


def selftest(ids: list[str]) -> int:
    r"""For each task, an empty container must score 0 (not 1.0), and the official oracle/solve.sh must score 1. **A faulty installation fails here.**

    Run the oracle as the official `--agent oracle` does: without skill injection (`run_benchflow_integration.py:392`)."""
    bad = 0
    for tid in ids:
        it = BOOK[tid]
        try:
            image = task_image(tid)
        except Exception as e:
            print(f"  FAIL {tid:<48} {e}", flush=True)
            bad += 1
            continue
        a = run_verifier(tid, image, "empty")
        # Official oracle: run solve.sh in a fresh container, then grade it.
        name = f"skb-oracle-{tid}"
        remove(name)
        if BACKEND == "apptainer":
            saved = globals()["SKILLS"]; globals()["SKILLS"] = "none"   # The official oracle does not inject skills.
            try:
                instance_up(name, tid)
            finally:
                globals()["SKILLS"] = saved
            upload(name, Path(it["dir"]) / "oracle", "/oracle")
        else:
            sh("docker", "run", "-d", "--name", name, "--network", network_of(tid),
               "--cpus", it["cpus"], "--memory", it["memory"], "-w", it["workdir"], image, "sleep", "infinity")
            sh("docker", "cp", f"{Path(it['dir']) / 'oracle'}/.", f"{name}:/oracle")
        try:
            if BACKEND == "apptainer":
                cexec(name, "bash", "/oracle/solve.sh", timeout=it["seconds"])
                snapdir = OVERLAYS / "snap" / f"{tid}-oracle"
                shutil.rmtree(snapdir, ignore_errors=True); snapdir.parent.mkdir(parents=True, exist_ok=True)
                sh("cp", "-a", str(OVERLAYS / name), str(snapdir))
                b = run_verifier(tid, image, "oracle")
            else:
                sh("docker", "exec", "-w", it["workdir"], name, "bash", "/oracle/solve.sh", timeout=it["seconds"])
                snap = f"skb-cand-{tid}:oracle"
                sh("docker", "commit", name, snap)
                b = run_verifier(tid, snap, "oracle")
                sh("docker", "rmi", "-f", snap)
        except subprocess.TimeoutExpired:
            b = {"reward": 0.0, "crashed": True, "why": "oracle timed out"}
        finally:
            remove(name)
        ok = float(a.get("reward", 1)) < 1.0 and abs(float(b.get("reward", 0)) - 1.0) < 1e-9
        bad += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'} {tid:<48} empty={a.get('reward')} oracle={b.get('reward')}"
              + (f" ({b.get('why')})" if b.get("crashed") else ""), flush=True)
    print(f"\n{len(ids) - bad} of {len(ids)} tasks grade their own oracle as passed")
    return 1 if bad else 0


def main() -> int:
    global LEVEL, SKILLS, NETWORK, GRADERS, GATE, ALLOW_UNSAFE_DIAGNOSTIC
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("TGENGIN_SKB_PORT", "7903")))
    ap.add_argument("--level", type=int, default=LEVEL, help="how much the note field says: 0..3")
    ap.add_argument("--skills", choices=("with", "none"), default=SKILLS, help="the benchmark's independent variable")
    ap.add_argument("--network", choices=("official", "none"), default=NETWORK,
                    help="official = each task's own network_mode (86/87 public); none = cut it (not the leaderboard experiment)")
    ap.add_argument("--graders", type=int, default=GRADERS)
    ap.add_argument("--unsafe-diagnostic", action="store_true", default=ALLOW_UNSAFE_DIAGNOSTIC,
                    help="allow unisolated backends or reference-bearing feedback for diagnosis only")
    ap.add_argument("--pick", nargs=2, type=int, metavar=("N", "SEED"))
    ap.add_argument("--build", nargs="*", metavar="TASK_ID")
    ap.add_argument("--selftest", nargs="*", metavar="TASK_ID")
    a = ap.parse_args()
    ALLOW_UNSAFE_DIAGNOSTIC = a.unsafe_diagnostic
    LEVEL, SKILLS, NETWORK = a.level, a.skills, a.network
    if a.graders != GRADERS:
        GRADERS = a.graders
        GATE = threading.Semaphore(GRADERS)
    LOGS.mkdir(parents=True, exist_ok=True)

    if a.pick is not None:
        print("\n".join(pick(a.pick[0], a.pick[1])))
        return 0
    if a.build is not None:
        for tid in (a.build or sorted(BOOK)):
            print(f"  {task_image(tid)}", flush=True)
        return 0
    if a.selftest is not None:
        return selftest(a.selftest or pick(4, 0))

    require_isolation()
    if not GRADER_TOKEN and not ALLOW_UNSAFE_DIAGNOSTIC:
        raise SystemExit("TGENGIN_GRADER_TOKEN is required for authenticated grading")

    print(f"[skb] {'UNSAFE DIAGNOSTIC | ' if ALLOW_UNSAFE_DIAGNOSTIC else ''}stand up: http://127.0.0.1:{a.port}/{{place,verified,passed}} | backend {BACKEND} | {len(BOOK)} tasks | "
          f"level {LEVEL} | skills {SKILLS} | network {NETWORK}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
