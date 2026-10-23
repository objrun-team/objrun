"""DeepSWE 的台子 —— 引擎外面的一个 HTTP 服务，跑在 WSL 里，手上有 docker。

    python3 stand.py [--port 7902] [--level 2] [--selftest]

引擎那边它是**三条句柄**：

    http://127.0.0.1:7902/place       在哪儿干：把工具调用转发进那道题的容器
    http://127.0.0.1:7902/applies     G 的第一格：交出来的补丁打得上吗
    http://127.0.0.1:7902/resolved    G 的根：官方判据说做成了吗

句柄名本身就是地址，内核 POST 一份 JSON 过来，这儿回一份 JSON —— 没有别的协议。

## 为什么位置也在这儿

「怎么到那个位置」是 `workplace.identity` 指着的那条句柄（`app/src/place/index.ts`）。
内核自带的那条（`fn:place.hops`）读的是 `wsl` / `ssh` / `docker` 那套跳板串，在这台
机器上过不去，三处都实测过：

    wsl.exe -- docker ps                     docker: command not found
                                             （snap 装的，只在登录 shell 的 PATH 上）
    ship() 只处理最外一跳                     运行时 cp 进了 WSL 的 /tmp，不在容器里
    docker cp /tmp/…                         lstat: no such file（snap 够不着 /tmp）

三条都是**这台机器的性质**，不是「位置」这个概念的性质。所以这个例子自带一条转发
实现：地址写法是我们自己的（`dsw:<task-id>`），容器怎么起、运行时怎么送，全在这个
进程里。内核一个字不用改。

**转发出去的工具还是内核那一份实现** —— 送进容器的是 `dist/tgengin-runtime-linux-x64`，
它是个 MCP server，装的就是 `app/src/tools/` 那一批。自己拿 Python 再实现一遍 bash /
read / write 的话，同一件事就有了两份，而且会悄悄地漂。

## 判卷是官方的，一行不改

`tests/` 里的 `test.sh` + `grader.py` + `config.json` + `test.patch` 是官方判据。这个
文件不实现任何判断，只做四件事：起容器、取补丁、把官方判据跑起来、读 `reward.json`。

判卷跑在**另一个干净容器**里（官方 `environment_mode = "separate"`）：镜像 = 那道题
钉死的镜像 + 把隐藏测试烤进 `/tests`，`--network none`。干活那个容器不参与判卷，也
不回档 —— 经验留在里头。

## 分级：这一栏说多少

`--level` 定 `note` 那一栏写多细。**每个级别是一次单独的实验**，从详到略各跑一趟，
看这条信息值多少。引擎那边不知道有这回事，G 的形状也不随级别变。

    0   只有过没过
    1   + 哪一段断的 + 计数（44 条新行为过了 12 条；2738 条原有测试没坏）
    2   + 是哪几条没过（测试名）
    3   + 失败信息原文

## solution/ 不出这个进程

`tasks/<id>/solution/solution.patch` 是参考解。它只在自检里用（喂回去该判 1），
判卷时官方判据自己也不碰它。语料装在 WSL 家目录下，不进仓库 —— 干活的智能体在容器
里，`--network none`，够不着这个目录，也够不着网。
"""

from __future__ import annotations

import argparse
import hashlib
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

HOME_DIR = Path(os.environ.get("TGENGIN_DSW_HOME", Path.home() / ".cache" / "tgengin-deepswe"))
CORPUS = HOME_DIR / "deep-swe" / "tasks"
RUNTIME = HOME_DIR / "tgengin-runtime-linux-x64"
LOGS = HOME_DIR / "logs"

# 官方每道题自己声明的限额，照抄进 docker run。**不放宽** —— 放宽的话算出来的东西
# 跟榜上那些不是同一个实验。
CPUS = "2"
MEMORY = "8g"

# **能开多少文件。默认不管，就是 docker 那个 1024。**
#
# `task.toml` 没声明这一条（它只说核、内存、盘），所以这儿也不替它声明 —— 环境是什么
# 样就是什么样，我们不去调。
#
# 留这个旋钮是因为**量过它的后果**：`eicrud-keyset-pagination-cursor` 在 1024 下起不动
# 它那个 MongoDB，报 `MongoServerError: 24: Too many open files`，参考解喂回去判 0
# （f2p 0/14）；提到 65536 就是 14/14。也就是说那道题在这台机器上做不成，**而且看着
# 完全像题坏了**。它被排除在批外，按 0 计（见 `SKIP`）。
#
# 要复现那个对比：`TGENGIN_DSW_NOFILE=65536:1048576 python3 stand.py`
NOFILE = os.environ.get("TGENGIN_DSW_NOFILE", "")

LEVEL = int(os.environ.get("TGENGIN_DSW_LEVEL", "2"))

# **docker 得先在 PATH 上。** snap 装的那份只在登录 shell 的 PATH 里，而这个进程
# 多半是被非登录 shell 叫起来的 —— 不补的话每一条 docker 都是 FileNotFoundError，
# 报出来的是 FileNotFoundError。
#
# 只在**找不到**的时候试那个常见位置，别处装的不受影响。这是「机器怎么装的」这一类
# 的事，正是该落在这个文件里的东西 —— 内核不该认得 snap。
if shutil.which("docker") is None and Path("/snap/bin/docker").exists():
    os.environ["PATH"] = "/snap/bin:" + os.environ.get("PATH", "")


# ── 语料 ────────────────────────────────────────────────────────────────────


def load_corpus() -> dict[str, dict]:
    """把 113 道题的元数据读进来。**答案不读** —— `solution/` 只在自检里碰。"""
    if not CORPUS.is_dir():
        raise SystemExit(f"the task corpus is missing: {CORPUS} (run setup.sh first)")
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
            # **官方给了时限就用官方的**（`[agent] timeout_sec`），我们不另编一个数。
            # 编一个的话，跑出来的东西跟榜上那些就不是同一个实验了。
            "seconds": int(float(agent.get("timeout_sec", 10800))),
            "instruction": (d / "instruction.md").read_text(encoding="utf-8"),
            "dir": str(d),
        }
    return book


BOOK = load_corpus()

# **这台机器上跑不了的题。发批的时候不发，但成绩单里按 0 算** —— 从分母里拿掉的话，
# 那个分数就不是「113 道里做成了几道」了。
#
# 每一条都得写清楚是**量出来的什么**，不是「跑起来怪怪的」。
SKIP = {
    "eicrud-keyset-pagination-cursor":
        "needs more than the default 1024 open files: its MongoDB dies with "
        "'MongoServerError: 24: Too many open files' and the reference solution grades 0/14 "
        "(14/14 once nofile is raised). Left as a 0 rather than changing the environment.",
}


def pick(n: int, seed: int) -> list[str]:
    """点名哪几道。**确定的**：同一个 (n, seed) 永远是同一批，复现靠这两个数。"""
    # **排除的那几道先拿掉再抽** —— 抽完再拿掉的话，同一个 (n, seed) 抽出来的道数
    # 会随排除名单变，那就不叫确定了。
    ids = [i for i in sorted(BOOK) if i not in SKIP]
    if n <= 0 or n >= len(ids):
        return ids
    return sorted(random.Random(seed).sample(ids, n))


# ── docker ──────────────────────────────────────────────────────────────────


def sh(*argv: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def task_id_of(name: str) -> str:
    """`<跑名>/<题号>` 里的题号。没有斜杠就是题号本身。

    **题号跨跑是不变的**，而 `task.id` 全局唯一（`tasks/publish.ts`：重了当场拒，
    而 `/bench` 是一道不过整批不发）。所以任务那一侧带上跑名，这儿再摘回来 ——
    不然第一趟跑完，第二趟整批发不出去，除非每次把库挪走重建。
    """
    return name.rsplit("/", 1)[-1]


def container_of(place: str) -> str:
    """位置串 → 容器名。**地址写法是我们自己的**，内核不解析它（见模块头）。

    `dsw:<跑名>/<题号>`，跑名可以省。**一跑一个容器** —— 换个跑名就是全新的工作区，
    上一跑留下的东西渗不进来。同一跑里判死重来共用同一个，那是有意的：经验留着。
    """
    m = re.fullmatch(r"dsw:(?:([A-Za-z0-9._-]+)/)?([A-Za-z0-9._-]+)", place or "")
    if not m:
        raise ValueError(f"unrecognised place for this bench: {place} (expected dsw:[<run>/]<task-id>)")
    run, tid = m.group(1), m.group(2)
    if tid not in BOOK:
        raise ValueError(f"no such task: {tid}")
    return f"dsw-{run}-{tid}" if run else f"dsw-{tid}"


def container_up(place: str) -> str:
    """那道题的容器起着没有，没起就起一个。

    **`--network none`** 照官方 `agent.network_mode = "no-network"`。核和内存也照
    官方那道题自己声明的来。
    """
    name = container_of(place)
    tid = task_id_of(place.split(':', 1)[1])
    got = sh("docker", "inspect", "-f", "{{.State.Running}}", name)
    if got.returncode == 0 and got.stdout.strip() == "true":
        return name
    if got.returncode == 0:
        sh("docker", "rm", "-f", name)
    r = sh(
        "docker", "run", "-d", "--name", name,
        "--network", "none", "--cpus", CPUS, "--memory", MEMORY,
        *(("--ulimit", f"nofile={NOFILE}") if NOFILE else ()),
        BOOK[tid]["image"], "sleep", "infinity",
    )
    if r.returncode != 0:
        raise RuntimeError(f"cannot start the container for {tid}: {r.stderr.strip()}")
    settle_git(name)
    ship_runtime(name)
    return name


def settle_git(name: str) -> None:
    """镜像里没有 git 身份，没有身份 `git commit` 会拒。

    `safe.directory` 同理：`/app` 的属主跟容器里跑命令的用户对不上时 git 会拒。
    官方那条收集命令自己也先加这一句。
    """
    for kv in (("user.email", "agent@tgengin.local"), ("user.name", "agent")):
        sh("docker", "exec", name, "git", "config", "--global", *kv)
    sh("docker", "exec", name, "git", "config", "--global", "--add", "safe.directory", "/app")


def ship_runtime(name: str) -> None:
    """把内核那份运行时送进去。

    **送的是 `dist/tgengin-runtime-linux-x64`**，不是这儿另写的一套：它是个 MCP
    server，装的就是内核本机跑的那批工具，一份实现两边通用。
    """
    if not RUNTIME.is_file():
        raise RuntimeError(f"the runtime binary is missing: {RUNTIME} (run setup.sh first)")
    if sh("docker", "exec", name, "test", "-x", "/rt").returncode == 0:
        return
    r = sh("docker", "cp", str(RUNTIME), f"{name}:/rt")
    if r.returncode != 0:
        raise RuntimeError(f"cannot ship the runtime into {name}: {r.stderr.strip()}")
    sh("docker", "exec", name, "chmod", "+x", "/rt")


# ── 转发：跟容器里那个运行时说 MCP ──────────────────────────────────────────


class Runtime:
    """一个容器里那个运行时的连接。**一条会话是一根线**，所以来回上锁排队。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.lock = threading.Lock()
        self.next_id = 0
        self.proc = subprocess.Popen(
            ["docker", "exec", "-i", name, "/rt"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1,
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
    """开过的留着复用 —— 每次调用都重送一遍运行时的话，什么都别干了。"""
    name = container_up(place)
    with RUNTIMES_LOCK:
        rt = RUNTIMES.get(name)
        if rt is not None and rt.alive():
            return rt
        rt = Runtime(name)
        RUNTIMES[name] = rt
        return rt


# ── 判卷 ────────────────────────────────────────────────────────────────────


def tests_digest(tid: str) -> str:
    """`tests/` 那几个文件的指纹。判据镜像的 tag 认它。

    **认名字的话，语料一更新就悄悄判旧的那套隐藏测试** —— 镜像还在，`docker image
    inspect` 说有，于是永远不重建，判的还是上一版的隐藏测试。
    """
    h = hashlib.sha256()
    d = Path(BOOK[tid]["dir"]) / "tests"
    for f in sorted(d.rglob("*")):
        if f.is_file():
            h.update(f.name.encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:12]


def verify_image(tid: str) -> str:
    """那道题的判据镜像：钉死的题目镜像 + 隐藏测试烤进 /tests。**官方的 Dockerfile。**"""
    tag = f"dsw-verify-{tid}:{tests_digest(tid)}"
    if sh("docker", "image", "inspect", tag).returncode == 0:
        return tag
    r = sh("docker", "build", "-q", "-t", tag, str(Path(BOOK[tid]["dir"]) / "tests"))
    if r.returncode != 0:
        raise RuntimeError(f"cannot build the verifier image for {tid}: {r.stderr.strip()[-400:]}")
    return tag


def patch_of(place: str, tid: str, ref: str) -> str:
    """把它交的那个提交取成一份补丁。

    **官方那条收集命令**（`task.toml` 的 `[[verifier.collect]]`），只把 `HEAD`
    换成它交的那个 ref —— 于是判的是它点名的那棵树，不是「现在恰好是什么」。
    """
    name = container_of(place)
    base = BOOK[tid]["base_commit"]
    sh("docker", "exec", name, "git", "config", "--global", "--add", "safe.directory", "/app")
    r = sh("docker", "exec", "-w", "/app", name, "git", "diff", "--binary", base, ref)
    if r.returncode != 0:
        raise RuntimeError(f"cannot read {ref} in {name}: {r.stderr.strip()[-300:]}")
    return r.stdout


def wipe(box: Path, tag: str) -> None:
    """把上一次的日志目录清干净。

    **不能只 `rmtree`。** 判卷容器在挂进去的 `/logs` 里以 root 建目录（`verifier/reports`
    就是），我们这边是普通用户，删不动 —— 而 `ignore_errors=True` 会把失败吞掉，留下
    一个半拉目录，下一句 `chmod` 当场 PermissionError。

    **重跑同一份候选就会撞上**，实测在预检里炸过一道。所以删不掉的时候借容器去删：
    那边是 root，而且用的就是这道题自己的判据镜像，不额外拉东西。
    """
    shutil.rmtree(box, ignore_errors=True)
    if box.exists():
        sh("docker", "run", "--rm", "--network", "none", "-v", f"{box}:/logs", tag,
           "sh", "-c", "rm -rf /logs/..?* /logs/.[!.]* /logs/*")
        shutil.rmtree(box, ignore_errors=True)
    if box.exists():
        raise RuntimeError(f"cannot clear the previous log directory: {box}")


def run_verifier(tid: str, patch: str) -> dict:
    """判一次。一次跑出一份 `reward.json` + 一份 `ctrf.json`，两个节点读同一份。"""
    tag = verify_image(tid)
    key = hashlib.sha256(patch.encode()).hexdigest()[:16]
    box = LOGS / f"{tid}-{key}"
    wipe(box, tag)
    (box / "artifacts").mkdir(parents=True, exist_ok=True)
    (box / "verifier").mkdir(parents=True, exist_ok=True)
    if patch:
        (box / "artifacts" / "model.patch").write_text(patch, encoding="utf-8")
    os.chmod(box, 0o777)
    for p in box.rglob("*"):
        os.chmod(p, 0o777)

    # 官方给判卷的上限是 1800 秒（`task.toml` 的 `verifier.timeout_sec`），照抄。
    # 超了不抛到上面去 —— 下面读不到 `reward.json` 自然会判 0，那条路已经有了。
    code, timed_out = -1, False
    t0 = time.time()
    try:
        code = sh(
            "docker", "run", "--rm", "--network", "none",
            "--cpus", CPUS, "--memory", MEMORY,
            *(("--ulimit", f"nofile={NOFILE}") if NOFILE else ()),
            "-v", f"{box}:/logs", tag, "bash", "/tests/test.sh",
            timeout=1800,
        ).returncode
    except subprocess.TimeoutExpired:
        timed_out = True
    took = round(time.time() - t0, 1)

    reward_file = box / "verifier" / "reward.json"
    if not reward_file.is_file():
        # **判不出来的三种原因得分得开。** 三种都会让 `reward.json` 缺席，而缺席
        # 长得跟「这道题的判据坏了」一模一样：
        #
        #   137      被 OOM 杀了 —— 是机器内存不够，不是样本的毛病
        #   超时      1800 秒没跑完
        #   其它      判据自己炸了
        #
        # 混在一起报的话，提一次内存重跑，分不清哪几道是真的坏。
        why = "oom-killed" if code == 137 else ("timed out at 1800s" if timed_out else f"the verifier exited {code}")
        return {"reward": 0, "crashed": True, "why": why, "seconds": took,
                "f2p_total": 0, "f2p_passed": 0, "p2p_total": 0, "p2p_passed": 0}
    out = json.loads(reward_file.read_text())
    # **墙上时间进结果。** 判一次多久是这一跑的性质之一，不记的话下次要问
    # 「慢在哪儿」就得整趟重来 —— 而这一趟要跑几个钟头。
    out["seconds"] = took
    ctrf = box / "verifier" / "ctrf.json"
    out["_tests"] = json.loads(ctrf.read_text()).get("results", {}).get("tests", []) if ctrf.is_file() else []
    return out


CACHE: dict[tuple[str, str], dict] = {}
CACHE_LOCK = threading.Lock()

# **同时最多判几份。**
#
# 真跑那一趟是二十道题并发的，每道都可能同时调 `verify` —— 不拦的话就是二十个判据
# 容器一起起，每个 2 核 8 GB。这台机器 12 核 16 GB，那不是慢，是雪崩：一起 OOM，
# 一起写不出 `reward.json`，于是每一道都判 0。
#
# 这道闸是**台子自己的**，跟引擎那边发几道题无关 —— 那边的并发是实验设定，这边的
# 并发是这台机器扛得住多少。两件事，两个数。
GRADERS = int(os.environ.get("TGENGIN_DSW_GRADERS", "4"))
GATE = threading.Semaphore(GRADERS)

# **同一份补丁只许有一个人在判。**
#
# 缓存只挡得住「判完之后再来问」。两个线程同时问同一份的话，两个都查不到、两个都去
# 判 —— 而 `applies` / `resolved` 本来就是一前一后问同一份，树上几个兄弟验同一个
# 提交也是常事。后来的在这儿等着，判完直接读缓存。
INFLIGHT: dict[tuple[str, str], threading.Event] = {}


def judge(place: str, tid: str, ref: str) -> dict:
    """判一份候选。

    **缓存认的是补丁的内容，不是提交号。** 改一个字符就是另一份候选，上一次的判决
    对它不作数；反过来，换了提交号而那棵树没变，那就是同一份，不必再判一遍。
    认提交号的话，同一棵树换个 amend 就得重判一遍几十秒到几分钟。

    两个节点问的是同一次判卷的两栏，所以一份补丁只判一次。
    """
    try:
        patch = patch_of(place, tid, ref)
    except Exception as e:
        return {"reward": 0, "no_patch": True, "detail": str(e), "_tests": []}
    key = (tid, hashlib.sha256(patch.encode()).hexdigest())

    # 判完了 → 直接给；有人正在判 → 等他；都没有 → 这一份归我判。
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
        waiting.wait(timeout=1900)

    t0 = time.time()
    try:
        if not patch.strip():
            got = {"reward": 0, "empty": True, "_tests": []}
        else:
            # 排队进闸。等了多久要报出来 —— 判卷慢和排队慢是两回事。
            with GATE:
                queued = round(time.time() - t0, 1)
                got = run_verifier(tid, patch)
                got["queued"] = queued
        got["_bytes"] = len(patch)
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
        f"took={got.get('seconds', 0)}s queued={got.get('queued', 0)}s",
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


def task_of(body: dict) -> tuple[str, str, str]:
    """从内核送来的那份东西里挖出「哪道题」和「它交的是哪个提交」。

    内核送的是 `{node, moment, domain, feed, input}`，`input` 是 `{task, chain, result}`
    （树那条路）或者 `{task, result}`（收尾那一路）。
    """
    inp = body.get("input") or {}
    task = inp.get("task") or {}
    # **题号从 `task.id` 里摘**（`<跑名>/<题号>`），位置串照原样用 —— 容器是一跑一个。
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
                        "skipped": SKIP, "level": LEVEL, "graders": GRADERS})
            return
        if self.path.startswith("/problems"):
            # **发题的口：给题面，不给答案。** 语料在这一侧，发批那个脚本读不到。
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

        # ── G 的两格。**一次判卷，两处读**。 ──────────────────────────────
        if self.path in ("/applies", "/resolved"):
            tid, place, said = task_of(body)
            if tid not in BOOK:
                self._send({"value": False, "note": {"stage": "task", "detail": f"{tid} is not in the corpus"}})
                return
            if not said:
                self._send({"value": False, "note": {"stage": "collect", "detail": "nothing was handed in - hand in the commit sha of your work"}})
                return
            got = judge(place, tid, ref_of(said))
            if self.path == "/applies":
                ok = not (got.get("no_patch") or got.get("empty") or got.get("apply_failed"))
            else:
                # **根。** 上游判 0 的话不必再说一遍 —— 那句话已经在上一格里了。
                feed = body.get("feed") or []
                if feed and feed[0].get("value") is not True:
                    self._send({"value": False})
                    return
                ok = int(got.get("reward", 0)) == 1
            self._send({"value": ok} if ok else {"value": False, "note": note_of(tid, got)})
            return

        self._send({"error": f"no {self.path} here"}, 404)


# ── 自检 ────────────────────────────────────────────────────────────────────


def selftest(ids: list[str]) -> int:
    """拿参考解喂回去，官方判据该说 1；空补丁该说 0。**装错了在这儿就炸。**"""
    bad = 0
    for tid in ids:
        d = Path(BOOK[tid]["dir"])
        golden = (d / "solution" / "solution.patch").read_text(encoding="utf-8")
        a = run_verifier(tid, "")
        b = run_verifier(tid, golden)
        ok = int(a.get("reward", -1)) == 0 and int(b.get("reward", -1)) == 1
        bad += 0 if ok else 1
        print(
            f"  {'ok  ' if ok else 'FAIL'} {tid:<52} [{BOOK[tid]['language']:<10}] "
            f"empty={a.get('reward')} golden={b.get('reward')} "
            f"f2p={b.get('f2p_passed')}/{b.get('f2p_total')}",
            flush=True,
        )
    print(f"\n{len(ids) - bad} of {len(ids)} tasks grade their own reference solution as solved")
    return 1 if bad else 0


def main() -> int:
    global LEVEL, GRADERS, GATE
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("TGENGIN_DSW_PORT", "7902")))
    ap.add_argument("--level", type=int, default=LEVEL, help="how much the note field says: 0..3")
    ap.add_argument("--graders", type=int, default=GRADERS,
                    help="how many verifier containers may run at once (each takes 2 cpus and up to 8g)")
    ap.add_argument("--selftest", nargs="*", metavar="TASK_ID")
    ap.add_argument("--build", nargs="*", metavar="TASK_ID",
                    help="build the verifier images for these tasks (all of them if none given) and stop")
    a = ap.parse_args()
    LEVEL = a.level
    if a.graders != GRADERS:
        GRADERS = a.graders
        GATE = threading.Semaphore(GRADERS)
    LOGS.mkdir(parents=True, exist_ok=True)

    if a.build is not None:
        for tid in (a.build or sorted(BOOK)):
            print(f"  {verify_image(tid)}", flush=True)
        return 0

    if a.selftest is not None:
        return selftest(a.selftest or pick(4, 0))

    print(f"[dsw] {len(BOOK)} tasks | note level {LEVEL} | {GRADERS} graders at once | "
          f"http://127.0.0.1:{a.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
