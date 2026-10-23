"""DeepSWE 的台子 —— 引擎外面的一个 HTTP 服务。**Apptainer 版**（Sherlock）；docker 版在 `stand.py.bak-docker-0929`。

    python3 stand.py [--port 7902] [--level 2] [--graders 4] [--selftest [TASK_ID...] [--jobs 4]] [--pull [TASK_ID...]]

引擎那边它是**三条句柄**：

    http://127.0.0.1:7902/place       在哪儿干：把工具调用转发进那道题的容器
    http://127.0.0.1:7902/applies     G 的第一格：交出来的补丁打得上吗
    http://127.0.0.1:7902/resolved    G 的根：官方判据说做成了吗

另有两条给 U 臂收工用的：

    /grade  {place}                   判一次容器里 `git diff --binary <base> HEAD`（官方 collect 命令），不经 G
    /stop   {place}                   停容器、删 overlay

句柄名本身就是地址，内核 POST 一份 JSON 过来，这儿回一份 JSON —— 没有别的协议。

## 为什么位置也在这儿

「怎么到那个位置」是 `workplace.identity` 指着的那条句柄（`app/src/place/index.ts`）。
内核自带的 `fn:place.hops` 读的是 `wsl` / `ssh` / `docker` 那套跳板串；这儿是 Apptainer，
地址写法是我们自己的（`dsw:<跑名>/<题号>`），容器怎么起、运行时怎么送，全在这个进程里。
内核一个字不用改。

**转发出去的工具还是内核那一份实现** —— bind 进容器的 `/rt` 是 `dist/tgengin-runtime-linux-x64`，
一个 MCP server，装的就是 `app/src/tools/` 那一批。

## Apptainer 怎么替 docker（实测见 $SCRATCH/bench-feas/REPORT-deepswe.md 和 2026-09-29 的自检）

- 一题一个 sif（`images/<tid>.sif` = `apptainer pull docker://<钉死的镜像>`），一跑一个 instance；
- 可写层用**目录 overlay**（`--overlay <dir>`，放 /lscratch，作业结束即清），不用 `--writable-tmpfs`（那是内存）；
- `--fakeroot --containall --no-home`：**不加 `--no-home` 的话 fakeroot 的 HOME=/root 会被空 tmpfs 盖住**，镜像里 /root
  下的工具链消失；
- `--no-mount tmp`：`--containall` 默认把 /tmp、/var/tmp 换成内存 tmpfs，**盖掉镜像自带的 /tmp**（goreleaser 把
  GOMODCACHE/GOCACHE 和 go1.26.1 工具链放在 /tmp/gomodcache，盖掉就要联网下载 → 判 0）；不 mount 的话 /tmp 就是
  镜像的 + overlay，落在 /lscratch，也不吃作业内存；
- `--no-mount /etc/localtime`：Apptainer 默认绑宿主的（PDT），docker 用镜像的（UTC）；adaptix 的日期测试差一天；
- **断网 = `--no-mount /etc/resolv.conf`**：Apptainer 做不了网络命名空间，但不绑宿主 resolv.conf 之后域名解析全失败
  （gaierror，与 docker `--network none` 的失败形态一致），curl/pip/git/go 下载全断；loopback 照常。
  之前试过 http_proxy 指向死端口的软墙，它改变异常类型（botocore 的 ProxyConnectionError ≠ EndpointConnectionError），
  gql 的 5 条测试因此假阴性，弃用。**裸 IP 仍通**（Methods 要写）；
- fakeroot 往环境里塞 LD_PRELOAD=libfakeroot.so 和 LD_LIBRARY_PATH，Deno 拒绝在带这两个变量的环境里 spawn 子进程
  （cliffy 13 条快照测试）→ 每条进容器的命令前 unset（仍是 root，那是 user namespace 给的）；
- `instance start` 不收 `--pwd`，每条 exec 都带 `--pwd /app`（113 道题的仓库都在 /app）；exec 加 `--cleanenv`，台子
  进程的宿主环境（端口、路径）不进 agent 的 bash；
- 判卷不 build 判据镜像：`--bind tasks/<tid>/tests:/tests:ro` 直接在题目 sif 上跑 `bash /tests/test.sh`；tests 目录的
  sha256 记进结果；
- **没有 PID 命名空间。** Apptainer 的 starter 是 child subreaper：exec 的主进程正常退出时它把所有后代（含 setsid/nohup
  起的）一起收掉；但 starter 被 SIGKILL 就收不了，后代成孤儿（/rt、faked、测试起的服务）。所以这儿**从不 SIGKILL
  starter**：/rt 关 stdin 让它自己退；超时先杀后代再等 starter 自然退出（`run()`）；
- 容器共享宿主 loopback：台子和引擎的端口对容器里的 agent 可达。台子对每个 POST 查连接方进程的 mount namespace，
  来自容器内的一律拒绝（`from_container`）；U 臂题面里不放句柄 URL（send.ts）。

### Methods 要如实写的偏差（相对官方 harness 与 docker 版 F 臂）

1. 无网络命名空间：断网靠不绑 resolv.conf，域名解析失败但裸 IP 可达；loopback 与宿主共享（台子有来源检查）。
2. 无 cgroup 限额（官方 2 核 8 GB）：靠 Slurm 作业整体限额（33 核 256 GB）和 `--graders` 限并发。
3. 无 PID 命名空间：容器里 `kill -1` 能打到宿主上本人的进程（未发生过；无法防）。
4. /tmp 在 overlay 上不限大小（官方 storage_mb=20480）。
5. U 臂在 Sherlock Apptainer、F 臂在 WSL docker；T=7200 对官方 10800（两臂一致）。
6. 模型服务路径：F 臂（9-02）走 DeepSeek 官方 API，U 臂走 OpenRouter 钉 BaseTen fp8（官方 9-10 已下线 V4 flash）。

## 判卷是官方的，一行不改

`tests/` 里的 `test.sh` + `grader.py` + `config.json` + `test.patch` 是官方判据。这个文件不实现任何判断，
只做四件事：起容器、取补丁、把官方判据跑起来、读 `reward.json`。

判卷跑在**另一个干净容器**里（官方 `environment_mode = "separate"`）：题目 sif + 空 overlay + `/tests` 只读 bind。
干活那个容器不参与判卷，也不回档 —— 经验留在里头。

## 分级：这一栏说多少

`--level` 定 `note` 那一栏写多细。**每个级别是一次单独的实验**，引擎那边不知道有这回事，G 的形状也不随级别变。

    0   只有过没过
    1   + 哪一段断的 + 计数（44 条新行为过了 12 条；2738 条原有测试没坏）
    2   + 是哪几条没过（测试名）
    3   + 失败信息原文

## solution/ 不出这个进程

`tasks/<id>/solution/solution.patch` 是参考解。它只在自检里用（喂回去该判 1），判卷时官方判据自己也不碰它。
语料在 `$TGENGIN_DSW_HOME/deep-swe/tasks`，不 bind 进任何容器。
"""

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
# 干活容器和判卷容器的可写层。**放 /lscratch**（节点本地盘，作业结束即清）。
OVERLAYS = Path(os.environ.get("TGENGIN_DSW_OVERLAYS", f"/lscratch/{os.environ.get('USER', 'u')}/tgengin-dsw"))
WORKDIR = "/app"

# 官方判卷上限 1800 s（`verifier.timeout_sec`），照抄。
VERIFY_SECONDS = 1800

# 断网开关。`TGENGIN_DSW_NETWALL=0` 关掉（容器能解析域名）。
NETWALL = os.environ.get("TGENGIN_DSW_NETWALL", "1") != "0"
NO_MOUNT = ("--no-mount", "/etc/localtime,tmp" + (",/etc/resolv.conf" if NETWALL else ""))
ENV_PRELUDE = "unset LD_PRELOAD LD_LIBRARY_PATH; "

LEVEL = int(os.environ.get("TGENGIN_DSW_LEVEL", "2"))

os.environ.setdefault("APPTAINER_CACHEDIR", "/scratch/users/ehz0002/.apptainer")
os.environ.setdefault("APPTAINER_TMPDIR", f"/lscratch/{os.environ.get('USER', 'u')}/aptmp")

HOST_MNTNS = os.readlink("/proc/self/ns/mnt")


# ── 语料 ────────────────────────────────────────────────────────────────────


def load_corpus() -> dict[str, dict]:
    """把 113 道题的元数据读进来。**答案不读** —— `solution/` 只在自检里碰。"""
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
            # **官方给了时限就用官方的**（`[agent] timeout_sec`），我们不另编一个数；send.ts 那边封顶。
            "seconds": int(float(agent.get("timeout_sec", 10800))),
            "instruction": (d / "instruction.md").read_text(encoding="utf-8"),
            "dir": str(d),
        }
    return book


BOOK = load_corpus()

# **这台机器上跑不了的题。发批的时候不发，但成绩单里按 0 算** —— 从分母里拿掉的话，
# 那个分数就不是「113 道里做成了几道」了。每一条都得写清楚是**量出来的什么**。
SKIP = {
    "eicrud-keyset-pagination-cursor":
        "needs more than the default 1024 open files: its MongoDB dies with "
        "'MongoServerError: 24: Too many open files' and the reference solution grades 0/14 "
        "(14/14 once nofile is raised). Left as a 0 rather than changing the environment. "
        "(measured on the docker/WSL stand, 2026-09; not in the 112-task F-arm run either)",
}


def pick(n: int, seed: int) -> list[str]:
    """点名哪几道。**确定的**：同一个 (n, seed) 永远是同一批。排除的先拿掉再抽。"""
    ids = [i for i in sorted(BOOK) if i not in SKIP]
    if n <= 0 or n >= len(ids):
        return ids
    return sorted(random.Random(seed).sample(ids, n))


# ── 进程：跑一条命令，超时不留孤儿 ──────────────────────────────────────────


def descendants(pid: int) -> list[int]:
    """`pid` 的全部后代（深的在前）。走 /proc/<pid>/task/*/children，没有 PID 命名空间所以都是宿主 pid。"""
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
    """杀 `pid` 的后代（不杀 pid 本身：那多半是 apptainer 的 starter，它看到主进程没了会自己收摊退出）。"""
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
    """`subprocess.run` 的替身。超时时**先杀后代再等 starter 自己退**（`subprocess.run` 是直接 SIGKILL
    子进程 = starter，容器里的 test.sh 和它起的服务就成了孤儿，事后还会往 /logs 里写 reward）。"""
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


# ── apptainer：起、进、收 ─────────────────────────────────────────────────────


def task_id_of(name: str) -> str:
    """`<跑名>/<题号>` 里的题号。没有斜杠就是题号本身。"""
    return name.rsplit("/", 1)[-1]


def container_of(place: str) -> str:
    """位置串 → 容器名。`dsw:[<跑名>/]<题号>`，**一跑一个容器**。"""
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
    """在活容器里执行一条命令的 argv。**每条都带 `--pwd /app`**（instance start 不收 --pwd，不带就回退到 /），
    `--cleanenv`（宿主环境不进去），前面接 ENV_PRELUDE（剥掉 fakeroot 的 LD_*）。"""
    e = [x for k, v in {"TGENGIN_DSW_BOX": name, **(env or {})}.items() for x in ("--env", f"{k}={v}")]
    return ["apptainer", "exec", "--cleanenv", "--no-umask", "--pwd", WORKDIR, *e, f"instance://{name}",
            "sh", "-c", ENV_PRELUDE + 'exec "$@"', "sh", *cmd]


def cexec(name: str, *cmd: str, env: dict[str, str] | None = None, timeout: float = 120) -> Ran:
    return run(exec_argv(name, *cmd, env=env), timeout)


START_LOCK = threading.Lock()          # instance start 一次一个
NAME_LOCKS: dict[str, threading.Lock] = {}
NAME_LOCKS_LOCK = threading.Lock()


def name_lock(name: str) -> threading.Lock:
    with NAME_LOCKS_LOCK:
        return NAME_LOCKS.setdefault(name, threading.Lock())


def container_up(place: str) -> str:
    """那道题的容器起着没有，没起就起一个：sif 只读 + 目录 overlay + `/rt` bind。

    overlay 目录已经在的话**接着用**（跑名在路径里，新跑名就是新目录；同一跑里 instance 意外没了，
    再起来时工作区还在）。`/stop` 才删。
    """
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
    """镜像里没有 git 身份，没有身份 `git commit` 会拒。`/root/.gitconfig` 落在 overlay 上，跨 exec 持久。"""
    for kv in (("user.email", "agent@tgengin.local"), ("user.name", "agent")):
        cexec(name, "git", "config", "--global", *kv, timeout=60)
    cexec(name, "git", "config", "--global", "--add", "safe.directory", WORKDIR, timeout=60)


def remove(name: str) -> None:
    """断掉运行时连接（让 /rt 自己退，它的 starter 会把 agent 留下的后台进程一起收掉）、停 instance、删 overlay。"""
    with RUNTIMES_LOCK:
        rt = RUNTIMES.pop(name, None)
    if rt is not None:
        rt.close()
    sh("apptainer", "instance", "stop", name, timeout=120)
    shutil.rmtree(OVERLAYS / name, ignore_errors=True)


# ── 转发：跟容器里那个运行时说 MCP ──────────────────────────────────────────


class Runtime:
    """一个容器里那个运行时的连接。**一条会话是一根线**，所以来回上锁排队。"""

    INIT_TIMEOUT = 120
    CALL_TIMEOUT = 1500      # 一次工具调用最多等多久（/rt 的 bash 自己有更短的上限）

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
        """关 stdin，/rt 读到 EOF 自己退出，starter 随之收摊。十秒不退再杀后代。"""
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
                # 这条会话废了：回答再来也对不上号。关掉，下一次调用重开。
                self.close()
                raise
            return json.loads(line)

    def call(self, tool: str, args: dict):
        out = self.rpc("tools/call", {"name": tool, "arguments": args})
        if "error" in out:
            raise RuntimeError(str(out["error"].get("message", out["error"])))
        res = out.get("result", {})
        # 工具执行错当**结果**回，不当协议错 —— 调用方多半是个模型，它看得见就能自己改。
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
    """开过的留着复用。建连接在**这一题自己的锁**里，别的题不等。"""
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


# ── 判卷 ────────────────────────────────────────────────────────────────────


def tests_digest(tid: str) -> str:
    """`tests/` 那几个文件的指纹，记进结果和日志，好核对判的是哪一版隐藏测试。"""
    h = hashlib.sha256()
    d = Path(BOOK[tid]["dir"]) / "tests"
    for f in sorted(d.rglob("*")):
        if f.is_file():
            h.update(f.name.encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:12]


def patch_of(place: str, tid: str, ref: str, autocommit: bool = False) -> str:
    """把它交的那个提交取成一份补丁：**官方那条收集命令**（`[[verifier.collect]]`），只把 `HEAD` 换成它交的 ref。

    **不起容器。** 容器没起 = 那道题一次工具都没调过，没有可判的东西（同 docker 版：exec 一个不存在的容器就是失败）。
    """
    name = container_of(place)
    if not instance_running(name):
        raise RuntimeError(f"the container {name} is not running - the task never started, nothing to collect")
    base = BOOK[tid]["base_commit"]
    cexec(name, "git", "config", "--global", "--add", "safe.directory", WORKDIR, timeout=60)
    if autocommit:
        # **U 臂收工：把工作区里没提交的东西先提交掉。** 冒烟里三道题都是在交卷步之前一次都没 commit
        # （模型发了纯文本 / 预算用完，引擎就进交卷步，那一步不带工具），diff base..HEAD 全空、判 0 ——
        # 量的是「有没有 commit 习惯」不是代码。F 臂里同样的事会被判据说破然后重试，U 臂没有第二次。
        # 自动提交是保守方向（抬 U、压 Δ），Methods 里写。
        c = cexec(name, "sh", "-c", "git add -A && git commit -q -m 'tgengin hand-in' && echo COMMITTED || true", timeout=300)
        AUTOCOMMITTED[name] = "COMMITTED" in (c.stdout or "")
    r = cexec(name, "git", "diff", "--binary", base, ref, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"cannot read {ref} in {name}: {r.stderr.strip()[-300:]}")
    return r.stdout


AUTOCOMMITTED: dict[str, bool] = {}


def wipe(box: Path) -> None:
    """上一次同一份候选的日志目录。`/logs` 是 bind，里头文件属主是本人，直接删。"""
    shutil.rmtree(box, ignore_errors=True)
    if box.exists():
        raise RuntimeError(f"cannot clear the previous log directory: {box}")


def run_verifier(tid: str, patch: str) -> dict:
    """判一次：题目 sif + 空 overlay + `/tests` 只读 bind + `/logs` bind，`bash /tests/test.sh`。
    一次跑出一份 `reward.json` + 一份 `ctrf.json`，两个节点读同一份。"""
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
        # **判不出来的三种原因得分得开**：OOM / 超时 / 判据自己炸了。
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

# **同时最多判几份。** 无 cgroup 限额，这道闸是台子自己的：这台节点扛得住多少。
GRADERS = int(os.environ.get("TGENGIN_DSW_GRADERS", "4"))
GATE = threading.Semaphore(GRADERS)

# **同一份补丁只许有一个人在判。** 后来的在这儿等着，判完直接读缓存。
INFLIGHT: dict[tuple[str, str], threading.Event] = {}


def judge(place: str, tid: str, ref: str, autocommit: bool = False) -> dict:
    """判一份候选。**缓存认的是补丁的内容，不是提交号。**"""
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


# ── note：这一栏说多少，按 --level ──────────────────────────────────────────


def note_of(tid: str, got: dict) -> dict | str:
    """判 0 的时候多说的那一份。**级别定详略**，形状不随级别变。"""
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
    """这条连接是不是从容器里发来的。容器共享宿主 loopback，agent 用镜像里的 curl 就能打到这儿；
    按连接方本地端口查到进程（`ss -p`，本人的进程都查得到），看它的 mount namespace 是不是宿主的。
    查不到进程 / 读不了 ns 的一律当容器里来的（本人宿主上的进程都读得到）。"""
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
    """从内核送来的那份东西里挖出「哪道题」「在哪个容器」「它交的是哪个提交」。"""
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
    """它交上来的那一段里挑出提交 ref。**一个 sha 就够**，别的原样递给 git。"""
    m = re.search(r"\b[0-9a-f]{7,40}\b", said)
    return m.group(0) if m else (said.splitlines()[-1].strip() if said else "")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 默认那行访问日志太吵
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
            # **发题的口：给题面，不给答案。**
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
        # **容器里来的一律拒。** 判据、转发、收摊都只听引擎和 arm 脚本的。
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

        # ── 位置：转发一次工具调用，或者探一次活 ──────────────────────────
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

        # ── U 臂：收工后判一次容器里的 HEAD（官方 collect 命令：diff base..HEAD），不经 G；/stop 收摊 ──
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

        # ── G 的两格。**一次判卷，两处读**。 ──────────────────────────────
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


# ── 自检 ────────────────────────────────────────────────────────────────────


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
    """拿参考解喂回去，官方判据该说 1；空补丁该说 0。**装错了在这儿就炸。** 并发 `jobs` 道。"""
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
