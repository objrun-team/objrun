"""SkillsBench 1.1 的台子 —— 引擎外面的一个 HTTP 服务，跑在有 docker 的机器上（WSL）。

2026-10-08 隔离修复：此通用台子的 Docker 快照会执行候选可修改的 bash/Python，
不能正式计分；Docker 快照、Apptainer 和 level 3 仅可用 --unsafe-diagnostic 诊断。
每次诊断评分使用独立快照、实例和日志名，防止跨 run 覆盖。正式 JPG 私有输出评分
由独立 repair adapter 实现，其原镜像/输出文件/解释器与实际控制门另行验证。
发题、工具与评分入口须携带宿主 TGENGIN_GRADER_TOKEN，令牌不写入任务或容器。
正式 level 2 回报稳定的 test#N 序号；测试原名可能包含参数化期望值，仅诊断时可见。

    python3 stand.py [--port 7903] [--level 2] [--skills with|none] [--network official|none]
    python3 stand.py --pick 10 0          点名（给 setup.sh 用）
    python3 stand.py --build [TASK_ID...] 建镜像
    python3 stand.py --selftest [TASK_ID...]

引擎那边它是**三条句柄**：

    http://127.0.0.1:7903/place       在哪儿干：把工具调用转发进那道题的容器
    http://127.0.0.1:7903/verified    G 的第一格：官方 verifier/test.sh 跑完、写出了 reward.txt
    http://127.0.0.1:7903/passed      G 的根：reward == 1.0

句柄名本身就是地址，内核 POST 一份 JSON 过来，这儿回一份 JSON —— 没有别的协议。

## 候选是容器状态

题面写死了输出路径（`/root/offer_letter_filled.docx` 这种），官方判据直接 open 它。
所以交卷字符串**不看**，判的是交卷那一刻容器里的文件。判卷时先 `docker commit` 干活容器
成快照，再起一个一次性容器把官方 `verifier/` 拷进 `/verifier` 跑 `test.sh`。

官方 harness 是 `verifier.service: main` —— 在干活容器里原地跑。改用快照只有一个理由：
一轮里 verify 会问好几次，每次 test.sh 都 `apt-get`/`uvx` 装一遍东西，原地跑的话干活
容器越判越脏。判据本身一字不改。

## 判卷是官方的，一行不改

`tasks/<id>/verifier/test.sh`（+ `test_outputs.py`，pytest）是官方判据，退出码 0 就
`echo 1 > /logs/verifier/reward.txt`。这个文件不实现任何判断，只做四件事：起容器、拍快照、
把官方判据跑起来、读 `reward.txt`。

**通过 = reward == 1.0**，论文和官方 oracle 门（`run_benchflow_integration.py:549`）都这么定。
7 道题的 test.sh 写的是分数，榜单 `mean(reward)` 给部分分，这儿不给 —— 分数进 note。

## 分级：这一栏说多少

    0   只有过没过
    1   + 哪一段断的 + reward 数值 + pytest 计数（81 道有 ctrf.json）
    2   + 是哪几条没过（测试名）
    3   + 断言原文 —— **会漏 GT**（很多断言把期望值写在信息里），只当上界实验

## skills 是这个 benchmark 的自变量

论文比的是同一模型「有 / 无 skills」。`--skills with` 把 `environment/skills/` 拷进
`/root/skills` 和 `/root/.claude/skills`，并在 `/problems` 里附 skill 名和描述让发批脚本
拼进题面（官方 harness 是注入 system prompt，我们的 solver 不是那些 harness，这是我们自己
的注入法）。`--skills none` 是 no-skill 对照。G 的形状两趟一样。

## oracle/ 和 verifier/ 不出这个进程

参考解只在自检里用。GT 在 `verifier/` 里，只进那个一次性判卷容器。**但这不是隔离**：
86/87 道题官方给干活容器 `network_mode: public`，而整个 benchmark 在 GitHub 上。
`--network none` 是我们的旋钮，开了就不是榜上那个实验。
"""

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

import yaml  # setup.sh 装的 pyyaml —— task.md 的 frontmatter 是 YAML，stdlib 没有

HOME_DIR = Path(os.environ.get("TGENGIN_SKB_HOME", Path.home() / ".cache" / "tgengin-skillsbench"))
REPO = HOME_DIR / "skillsbench"
TASKS = REPO / "tasks"
RUNTIME = HOME_DIR / "tgengin-runtime-linux-x64"
LOGS = HOME_DIR / "logs"

# ── 后端：docker 或 apptainer（Sherlock）────────────────────────────────────
# 判据一行不改，只换容器四件事。实测见 $SCRATCH/bench-feas/REPORT-skillsbench.md：
#   - 镜像：Dockerfile → def（$TGENGIN_SKB_HOME/def_of.py，spython 直译 + apt drop-in）→ images/<tid>.sif；
#   - 干活容器：sif 只读 + **目录 overlay**（/lscratch）+ --containall --no-home（否则 /root 里 COPY 进来的题目文件被盖掉）；
#   - 快照 = `cp -a` overlay 目录（0.1 s），替代 docker commit；判卷 = 一次性 exec 挂快照 overlay 跑官方 test.sh；
#   - 指纹 = upper/ 里的路径+mtime+大小，替代 docker diff；
#   - 做不到：--network none（无 net namespace）、--cpus/--memory（无 cgroup）。
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


# ── 语料 ────────────────────────────────────────────────────────────────────


def split_task_md(text: str) -> tuple[dict, str]:
    """`task.md` = `---` YAML frontmatter `---` 题面。题面就是 agent 看到的全部。"""
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError("task.md has no frontmatter")
    return yaml.safe_load(m.group(1)) or {}, m.group(2).strip()


def workdir_of(dockerfile: Path) -> str:
    """Dockerfile 最后一条 WORKDIR，就是 agent 的 cwd（66 道 /root、15 道 /app…）。

    带变量的那一条（`WORKDIR ${WORKSPACE}`）会抓成字面量 —— 只有一道，见 G.md 未验证。
    """
    wd = "/root"
    for line in dockerfile.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\s*WORKDIR\s+(\S+)", line)
        if m:
            wd = m.group(1)
    return wd


def skills_of(d: Path) -> list[dict]:
    """每个 skill 的名字和描述（SKILL.md 的 frontmatter）。**只发这两样**，正文 solver 自己去读。"""
    out = []
    for s in sorted((d / "environment" / "skills").glob("*/SKILL.md")):
        try:
            fm, _ = split_task_md(s.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            fm = {}
        out.append({"name": str(fm.get("name") or s.parent.name), "description": str(fm.get("description") or "")})
    return out


def load_corpus() -> dict[str, dict]:
    """把 87 道题的元数据读进来。**oracle/ 不读，verifier/ 不读** —— 判卷时才拷进一次性容器。"""
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
            # **官方给了时限就用官方的**，我们不另编一个数。
            "seconds": int(float((fm.get("agent") or {}).get("timeout_sec", 1800))),
            "verify_seconds": int(float((fm.get("verifier") or {}).get("timeout_sec", 1800))),
            "cpus": str(env.get("cpus", 1)),
            "memory": f"{int(env.get('memory_mb', 4096))}m",
            # 87 道里只有 bike-rebalance 是 no-network，其余 public。
            "network": str(env.get("network_mode", "public")),
            "workdir": workdir_of(d / "environment" / "Dockerfile"),
            "skills": skills_of(d),
            "dir": str(d),
        }
    return book


BOOK = load_corpus()

# **这台机器上跑不了的题。** 发批时不发，成绩单里按 0 算。每一条都得写清楚是量出来的什么。
# 量法：`stand.py --selftest`（空容器判 0、官方 oracle 判 1 才算过），2026-09-28/29 三轮，记录在
# $TGENGIN_SKB_HOME/{selftest.out,selftest3.out}。87 题里 76 过、9 自检不过、2 没翻出 Apptainer 定义。
SKIP: dict[str, str] = {
    # 自检不过：官方 oracle 在 Apptainer 容器里判不到 1.0
    "crystallographic-wyckoff-position-analysis": "selftest: oracle=0.0",
    "exceltable-in-ppt": "selftest: oracle=0.0",
    "fix-druid-loophole-cve": "selftest: verifier exited 255 without writing reward.txt (oracle=0.0)",
    "fix-erlang-ssh-cve": "selftest: oracle=0.0",
    "gravitational-wave-detection": "selftest: oracle=0.0",
    "python-scala-translation": "selftest: oracle=0.0",
    "setup-fuzzing-py": "selftest: oracle=0.66 (partial credit only)",
    # 镜像建不出
    "debug-trl-grpo": "image build: downloads HF model at build time, no network in apptainer build",
    "lean4-proof": "image build: elan installs into host $HOME, `lean: not found` in container",
    # Dockerfile 是多阶段 / bugswarm 基底，def_of.py 没翻
    "fix-build-agentops": "no apptainer def: multi-stage / bugswarm base image not translated",
    "fix-build-google-auto": "no apptainer def: multi-stage / bugswarm base image not translated",
}


def pick(n: int, seed: int) -> list[str]:
    """点名哪几道。**确定的**：同一个 (n, seed) 永远是同一批。排除的先拿掉再抽。"""
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
    """`<跑名>/<题号>` 里的题号。理由同 deepswe：task.id 全局唯一，题号跨跑不变。"""
    return name.rsplit("/", 1)[-1]


def container_of(place: str) -> str:
    """位置串 → 容器名。`skb:[<跑名>/]<题号>`，一跑一个容器。"""
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
    """`environment/` 的指纹，镜像 tag 认它 —— 认名字的话语料一更新就悄悄用旧镜像。"""
    h = hashlib.sha256()
    d = Path(BOOK[tid]["dir"]) / "environment"
    for f in sorted(d.rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(d)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:12]


def task_image(tid: str) -> str:
    """那道题的镜像：官方 `environment/Dockerfile`，context 就是 `environment/`。**没有官方 registry，都得自己 build。**"""
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
    """`--network none` 旋钮开了就全 none；不开照官方那道题自己声明的。"""
    if NETWORK == "none" or BOOK[tid]["network"] == "no-network":
        return "none"
    return "bridge"


def container_up(place: str) -> str:
    """那道题的容器起着没有，没起就起一个。核、内存、网都照官方 task.md。"""
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
    """apptainer 版 container_up：sif 只读 + 目录 overlay + /rt、/stage 两个 bind。skills 在起之前放进 upper/。"""
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
    """`docker cp src/. name:dst`：apptainer 走 /stage 中转。"""
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
    """把内核那份运行时送进去（MCP server，装的就是内核本机那批工具）。"""
    if not RUNTIME.is_file():
        raise RuntimeError(f"the runtime binary is missing: {RUNTIME} (run setup.sh first)")
    if sh("docker", "exec", name, "test", "-x", "/rt").returncode == 0:
        return
    r = sh("docker", "cp", str(RUNTIME), f"{name}:/rt")
    if r.returncode != 0:
        raise RuntimeError(f"cannot ship the runtime into {name}: {r.stderr.strip()}")
    sh("docker", "exec", name, "chmod", "+x", "/rt")


def ship_skills(name: str, tid: str) -> None:
    """`environment/skills/` 进容器。两处：`/root/skills`（题面里指着它）和 `/root/.claude/skills`（agentskills 约定路径）。

    官方 CONTRIBUTING 说「不要把 skills 烤进镜像，harness 运行时注入」—— 这儿就是那个注入。
    """
    src = Path(BOOK[tid]["dir"]) / "environment" / "skills"
    if not src.is_dir():
        return
    for dst in ("/root/skills", "/root/.claude/skills"):
        sh("docker", "exec", name, "mkdir", "-p", dst)
        r = sh("docker", "cp", f"{src}/.", f"{name}:{dst}")
        if r.returncode != 0:
            raise RuntimeError(f"cannot ship skills into {name}: {r.stderr.strip()}")


# ── 转发：跟容器里那个运行时说 MCP（照抄 deepswe） ──────────────────────────


class Runtime:
    """一个容器里那个运行时的连接。**一条会话是一根线**，所以来回上锁排队。"""

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


# ── 判卷 ────────────────────────────────────────────────────────────────────


def wipe(box: Path, image: str) -> None:
    """清上一次的日志目录。判卷容器以 root 在 /logs 里建目录，宿主普通用户删不动 —— 借容器删。"""
    shutil.rmtree(box, ignore_errors=True)
    if box.exists() and BACKEND == "docker":
        sh("docker", "run", "--rm", "--network", "none", "-v", f"{box}:/logs", image,
           "sh", "-c", "rm -rf /logs/..?* /logs/.[!.]* /logs/*")
        shutil.rmtree(box, ignore_errors=True)
    if box.exists():
        raise RuntimeError(f"cannot clear the previous log directory: {box}")


def run_verifier(tid: str, image: str, key: str) -> dict:
    """在 `image`（干活容器的快照，或自检时的原始镜像）上跑一遍官方判据。

    步骤照官方 harness：`verifier/` → `/verifier`，`bash /verifier/test.sh`，读
    `/logs/verifier/reward.txt`。多一步 `cleanup_conftests`（87 道 task.md 都开着这条
    hardening）：判卷前删掉 agent 放的 `conftest.py`，不然一个 conftest 就能劫持 pytest。
    BenchFlow 那边的精确范围没看到，这儿删的是 /、cwd、/root 顶层那一层（见 G.md 未验证）。
    """
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
    # **只删顶层的**（/、cwd、/root 各一层）：能劫持 /verifier 那趟 pytest 的是这几处；
    # 递归删的话会把题目仓库自己的 conftest.py 一起删掉，软件工程那几道就判坏了。
    cleanup = f"find / {it['workdir']} /root -maxdepth 1 -name conftest.py -type f -delete 2>/dev/null; "
    r = sh(
        "docker", "create", "--name", name,
        # 判卷容器的网照干活容器：57 个 test.sh 要 apt-get / curl uv，断网的话它们自己就崩。
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

    # 官方给判卷的上限是那道题自己的 `verifier.timeout_sec`，照抄。超了不抛 —— 读不到
    # reward.txt 自然判 0，那条路已经有了。
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
        # 三种缺席得分得开：OOM（137）、超时、判据自己炸了。
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
    """读 reward.txt（两个后端共用的收尾）。"""
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
    """apptainer 版：`image` 是 sif，快照 overlay 目录在 OVERLAYS/snap/<tid>-<key>（judge 拷好的；自检时可以不存在 = 空 overlay）。"""
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
# 每个活容器串行判卷，每次请求用独立快照/日志/判卷容器。
# 路径指纹既不能证明内容相同，也不能隔离不同run的同名候选。

GRADERS = int(os.environ.get("TGENGIN_SKB_GRADERS", "4"))
GATE = threading.Semaphore(GRADERS)


def judge(place: str, tid: str) -> dict:
    """判一份候选：重新拍快照 → 官方判据 → 读reward；不复用可变状态判决。"""
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
    # 台子自己炸了（日志目录删不掉之类）也得回一个判 0 的字典，不能把异常抛给 HTTP 层 ——
    # 抛出去的话连接断掉，内核那边只看到「句柄没回」，分不清是题错了还是台子坏了。
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


# ── note：这一栏说多少，按 --level ──────────────────────────────────────────


def note_of(tid: str, got: dict) -> dict | str:
    """判 0 的时候多说的那一份。**级别定详略**，形状不随级别变。"""
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
    # **level 3 会漏 GT**：不少断言信息里就是期望值。只当上界实验。
    note["failures"] = [{"name": t.get("name", ""), "message": (t.get("message") or "")[:2000]} for t in failed[:40]]
    return note


# ── HTTP ────────────────────────────────────────────────────────────────────


def task_of(body: dict) -> tuple[str, str]:
    """内核送的是 `{node, moment, domain, feed, input}`，`input.task.id` 是 `<跑名>/<题号>`。交卷内容不看。"""
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
            # **发题的口：给题面，不给答案。** oracle/ 和 verifier/ 一个字都不过来。
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
                    # 有 skills 那一趟才给名字和描述；正文在容器 /root/skills 里自己读。
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

        # ── U 臂收工判一次（不经 G）；/stop 收摊 ──
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

        # ── G 的两格。**一次判卷，两处读。** ──────────────────────────────
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
            # **回 `{"value": bool}`。** 值域封闭，回别的内核当违约归 0。
            self._send({"value": True} if ok else {"value": False, "note": note_of(tid, got)})
            return

        self._send({"error": f"no {self.path} here"}, 404)


# ── 自检 ────────────────────────────────────────────────────────────────────


def selftest(ids: list[str]) -> int:
    """每道题：空容器该判 0（不是 1.0），跑完官方 oracle/solve.sh 该判 1。**装错了在这儿就炸。**

    oracle 照官方 `--agent oracle` 那样跑：不注入 skills（`run_benchflow_integration.py:392`）。
    """
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
        # 官方 oracle：在一个全新容器里跑 solve.sh，然后判它。
        name = f"skb-oracle-{tid}"
        remove(name)
        if BACKEND == "apptainer":
            saved = globals()["SKILLS"]; globals()["SKILLS"] = "none"   # 官方 oracle 不注入 skills
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
