"""Terminal-Bench 2.1 的台子 —— 引擎外面的一个 HTTP 服务，跑在有 docker 的那台机器上。

2026-10-08 隔离修复：精确版本的 nginx-request-logging 可使用独立评分器读取活服务。
其余任务及 Apptainer 尚无经过验证的隔离协议，正式实验阻止。
--unsafe-diagnostic 的共享活容器协议仅用于复现，不能作为有效成绩。
HTTP 发题、工具和评分入口须携带宿主 TGENGIN_GRADER_TOKEN。

    python3 stand.py [--port 7903] [--level 2] [--selftest [TASK_ID...]]

引擎那边它是**三条句柄**：

    http://127.0.0.1:7903/place     在哪儿干：把工具调用转发进那道题的容器
    http://127.0.0.1:7903/ran       G 的第一格：官方 tests/test.sh 跑完了、写出了 reward 吗
    http://127.0.0.1:7903/passed    G 的根：reward == 1 吗

句柄名本身就是地址，内核 POST 一份 JSON 过来，这儿回一份 JSON —— 没有别的协议。

## 候选是容器的终态，不是一份文件

Terminal-Bench 没有 git 仓库、没有「补丁」这种东西：题目是「把这个容器弄成某个样子」
（装上 Windows 3.11、让 nginx 记日志、把 /app/move.txt 写对……），官方默认判卷是在
干活的那个容器里**跑 `tests/test.sh`（harbor `verifier.environment_mode` 默认 `shared`）。
所以 cand = 判卷那一刻的容器本身。求解器交上来的字符串只是这一份候选的名字（用来把
`ran` / `passed` 两格对到同一次判卷），内容不参与判断。

**不做快照。** `docker commit` 存不下正在跑的进程，而 89 道里有服务类的题
（nginx、pypi-server、kv-store-grpc、qemu-alpine-ssh……）判的就是进程活着 —— 快照
一律判 0，看着像题坏了。新的 nginx 独立判卷共享服务网络，通过窄接口读取活容器
的三个文件及两种命令；既保留服务状态，也不把 tests 放进候选。

## 判卷是官方的，一行不改

每道题的 `tests/test.sh` 就是判据（装 uv，跑 `pytest --ctrf`，过了写
`echo 1 > /logs/verifier/reward.txt`）。这个文件不实现任何判断，只做四件事：起容器、
把 `tests/` 送到 `/tests`、把 `test.sh` 跑起来、读 `reward.txt`。读法照抄 harbor
`src/harbor/verifier/verifier.py::_parse_reward_text`（float、有限、空文件即错），
两个文件都在时 `reward.json` 优先（harbor 也是）。独立 nginx 协议还核实固定的
八条测试全部完成、源文件哈希、原镜像 ID、命名空间和窄接口故障状态。

诊断共享判卷会改容器：test.sh 自己 `apt-get install curl`、装 uv —— 官方一趟只判一次，
所以他们无所谓；我们允许中途 `verify`，于是每判一次容器就多一层这种东西。这是
官方判据的性质，不去挡。

## 诊断清理不等于测试隔离

判卷把隐藏测试送进了求解器的容器。不删的话，下一条 `bash` 就是 `cat /tests/test_outputs.py`
—— 那不是分级里的哪一级，那是整份答案。诊断路径会清理 /tests 和 /logs/verifier；
Apptainer 中转目录 /stage 的副本也在 upload 的 finally 中清理。
**判卷跑着的那几十秒里它仍然看得见**（同一个容器，同一个文件系统），这个窗口堵不死，
只能记着（见 G.md「boundary」）。

## 网络

官方 89 道全是 `allow_internet = true`，而且 **test.sh 自己要上网**（curl astral.sh 装 uv、
apt-get）。所以容器不能 `--network none` —— 这一点跟 deepswe 相反。代价是参考解就公开在
GitHub 上，容器里 `curl` 得到；这是官方基准自己的洞（他们靠 canary 字符串和荣誉制），
不是我们能在台子上堵的。

## 分级：这一栏说多少

`--level` 定 `note` 那一栏写多细。**每个级别是一次单独的实验**，引擎那边不知道有这回事，
G 的形状也不随级别变。

0   只有过没过
    1   + 哪一段断的 + 计数（9 条测试过了 4 条）
    2   + 是哪几条没过（稳定 test#N 编号）
    3   + 失败信息原文（仅显式诊断；正式模式拒绝）

## solution/ 不出这个进程

`tasks/<id>/solution/solve.sh` 是参考解。它只在自检里用（照 harbor `OracleAgent`
送到 `/solution` 跑一遍，该判 1）。语料装在台子这台机器的家目录，不进仓库。
"""

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

# ── 后端：docker 或 apptainer ────────────────────────────────────────────────
#
# **判据一行不改，只换「容器四件事」的实现**（起、进、送、收）。Sherlock 上没有 docker，
# 只有 apptainer 1.5（无 subuid，fakeroot 走 root-mapped ns）。实测见
# $SCRATCH/bench-feas/REPORT-terminal-bench.md，要点：
#
#   - 一题一个 sif（`images/<tid>.sif`，`apptainer pull docker://<pinned>`），一跑一个 instance；
#   - 可写层用**目录 overlay**（`--overlay <dir>`，放 /lscratch），不用 --writable-tmpfs（那是内存）；
#   - `--containall --no-home`：/tmp 私有、HOME 不盖到 /root（否则镜像里 /root 的东西消失）；
#   - `/rt` 和 `/stage`（tests、solution 的中转）用 bind，`/logs` bind 到宿主目录（harbor 本来就是挂的）；
#   - `instance start` 不收 `--pwd`，每条 exec 都带 `--pwd <WORKDIR>`（从题的 Dockerfile 解析）；
#   - 起来后往 /etc/apt/apt.conf.d/ 塞 3 行 drop-in，不然 test.sh 里的 apt-get 因 _apt 沙箱目录不可写而假失败；
#   - `--cpus/--memory` 做不到（fakeroot 下无 cgroup），靠 Slurm 作业整体限额；无 PID 命名空间；无网络隔离（本基准本来就有网）。
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

# **一次判卷的结果留多久给第二格读。** `ran` 判完存着，`passed` 紧接着来读；正常隔不到
# 一秒。留十分钟是给引擎那边慢的时候用的，过了就当没判过 —— 容器早就不是那时候的样子了。
RESULT_TTL = 600

# **docker 得先在 PATH 上。** snap 装的那份只在登录 shell 的 PATH 里（同 deepswe）。
if shutil.which("docker") is None and Path("/snap/bin/docker").exists():
    os.environ["PATH"] = "/snap/bin:" + os.environ.get("PATH", "")


# ── 语料 ────────────────────────────────────────────────────────────────────


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
    """把 89 道题的元数据读进来。**答案不读** —— `solution/` 只在自检里碰。"""
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
            # 官方每道题自己声明的限额，照抄进 docker run。**不放宽。**
            "cpus": str(env.get("cpus", 1)),
            "memory_mb": int(env.get("memory_mb", 2048)),
            # **官方给了时限就用官方的**，我们不另编一个数。
            "seconds": int(float(agent.get("timeout_sec", 900))),
            "verify_seconds": int(float(verifier.get("timeout_sec", 900))),
            "instruction": (d / "instruction.md").read_text(encoding="utf-8"),
            "dir": str(d),
            # 镜像的 WORKDIR（docker 自动生效；apptainer 每条 exec 要显式 --pwd）。86/89 是 /app。
            "workdir": workdir_of(d / "environment" / "Dockerfile"),
        }
    return book


BOOK = load_corpus()

# **这台机器上跑不了的题。发批的时候不发，但成绩单里按 0 算。**
# 每一条都得写清楚是**量出来的什么**。目前空着 —— 还没量。
SKIP: dict[str, str] = {}


def pick(n: int, seed: int) -> list[str]:
    """点名哪几道。**确定的**：同一个 (n, seed) 永远是同一批。"""
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
    """`<跑名>/<题号>` 里的题号。没有斜杠就是题号本身（同 deepswe）。"""
    return name.rsplit("/", 1)[-1]


def container_of(place: str) -> str:
    """位置串 → 容器名。`tb:[<跑名>/]<题号>`，**一跑一个容器**。"""
    m = re.fullmatch(r"tb:(?:([A-Za-z0-9._-]+)/)?([A-Za-z0-9._-]+)", place or "")
    if not m:
        raise ValueError(f"unrecognised place for this bench: {place} (expected tb:[<run>/]<task-id>)")
    run, tid = m.group(1), m.group(2)
    if tid not in BOOK:
        raise ValueError(f"no such task: {tid}")
    name = f"tb-{run}-{tid}" if run else f"tb-{tid}"
    TID_OF[name] = tid
    return name


# 容器名 → 题号（题号里有连字符，从名字里切不回来）。
TID_OF: dict[str, str] = {}
CREATED_CONTAINERS: set[str] = set()


def instance_running(name: str) -> bool:
    got = sh("apptainer", "instance", "list", "--json", name)
    try:
        return any(i.get("instance") == name for i in json.loads(got.stdout or "{}").get("instances", []))
    except Exception:
        return False


def exec_argv(name: str, *cmd: str, env: dict[str, str] | None = None) -> list[str]:
    """在活容器里执行一条命令的 argv（两个后端）。`name` 是容器名。"""
    if BACKEND == "docker":
        e = [x for k, v in (env or {}).items() for x in ("-e", f"{k}={v}")]
        return ["docker", "exec", *e, name, *cmd]
    wd = BOOK[TID_OF[name]]["workdir"] if name in TID_OF else "/app"
    e = [x for k, v in (env or {}).items() for x in ("--env", f"{k}={v}")]
    return ["apptainer", "exec", "--cleanenv", "--no-umask", "--pwd", wd, *e, f"instance://{name}", *cmd]


def cexec(name: str, *cmd: str, env: dict[str, str] | None = None, **kw) -> subprocess.CompletedProcess:
    return sh(*exec_argv(name, *cmd, env=env), **kw)


def upload(name: str, src: Path, dst: str) -> subprocess.CompletedProcess:
    """`docker cp src/. name:dst` 的两个后端。apptainer：宿主拷进 /stage，容器里 cp 到位。"""
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
    """`docker cp name:/logs/verifier/. box`。apptainer：/logs 就 bind 在宿主，直接拷。"""
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
    """那道题的容器起着没有，没起就起一个。

    照 harbor `docker-compose-prebuilt.yaml`：钉死的镜像 + `sh -c "sleep infinity"`。
    **不加 `--network none`**：官方 `allow_internet = true`，而且 test.sh 自己要上网。
    """
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
    # harbor 把 /logs 挂进去，所以那儿总是存在；我们不挂，就得自己建。
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
    """apptainer 版的 container_up：sif 只读 + 目录 overlay + 三个 bind。"""
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
        # apt 的 _apt 沙箱在 fakeroot 下不可写：装个 drop-in（不改镜像，不改 test.sh）。
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
    """把内核那份运行时送进去（`dist/tgengin-runtime-linux-x64`，一个 MCP server）。"""
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


# ── 转发：跟容器里那个运行时说 MCP（照抄 deepswe）───────────────────────────


class Runtime:
    """一个容器里那个运行时的连接。**一条会话是一根线**，所以来回上锁排队。"""

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


# ── 判卷 ────────────────────────────────────────────────────────────────────


def parse_reward(box: Path) -> float | None:
    """读 reward。**照抄 harbor `Verifier._parse_reward_text` / `_parse_reward_json`**：
    json 优先；文本按 float 解析；空文件、非数、非有限 → 都算没判出来（回 None）。"""
    js, txt = box / "reward.json", box / "reward.txt"
    try:
        if js.is_file():
            if js.stat().st_size == 0:
                return None
            got = json.loads(js.read_text())
            vals = list(got.values()) if isinstance(got, dict) else [got]
            if not vals or any(not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")) for v in vals):
                return None
            # 89 道全写 reward.txt，这一支只是照 harbor 的优先级留着；键叫 reward 就取它。
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
    """在活容器里判一次。**官方那几步**（harbor `Verifier.verify`）：

        tests/  →  /tests            （upload_dir）
        chmod +x /tests/test.sh      （以 root）
        (/tests/test.sh) > /logs/verifier/test-stdout.txt 2>&1
        /logs/verifier/  →  本地      （download_dir）

    然后多做一步官方不做的：**把 /tests 和 /logs/verifier 删掉**。
    """
    require_isolation(tid)
    task = BOOK[tid]
    private = globals().get("isolated_verifier")
    if not ALLOW_UNSAFE_DIAGNOSTIC and private is not None and private.supports(task):
        return private.run_verifier(task, name, LOGS)
    tests = Path(task["dir"]) / "tests"
    box = LOGS / f"{tid}-{int(time.time() * 1000)}"
    box.mkdir(parents=True, exist_ok=True)

    cexec(name, "sh", "-c", "rm -rf /tests && mkdir -p /tests /logs/verifier && rm -rf /logs/verifier/*")
    # `tests/.` 而不是 `tests`：后者会得到 /tests/tests/。
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
        # 客户端超时了，容器里那条 test.sh 还在跑；不杀的话它会在几分钟后写出一份
        # reward 来，下一次判卷读到的就是这一次的。
        cexec(name, "sh", "-c", "pkill -f /tests/test.sh || true")
    took = round(time.time() - t0, 1)

    download_verifier(name, box)
    # **拿完就删。** 隐藏测试不能留在求解器的容器里。
    cexec(name, "sh", "-c", "rm -rf /tests /logs/verifier/*; true")

    reward = parse_reward(box)
    out: dict = {"seconds": took, "code": code, "box": str(box)}
    if reward is None:
        # **判不出来的三种原因得分得开**（同 deepswe）：OOM / 超时 / 判据自己炸了。
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


# **同一个容器一次只判一份。** 两次判卷同时往 /tests 里送东西，谁也读不到完整的一份。
LOCKS: dict[str, threading.Lock] = {}
LOCKS_LOCK = threading.Lock()

# `ran` 判完存这儿，`passed` 紧接着读。键 = (容器, 它交的名字)。
RESULTS: dict[tuple[str, str], tuple[float, dict]] = {}

# **同时最多判几份。** 每道题 1–4 核、2–8 GB，闸在台子这一侧（同 deepswe）。
GRADERS = int(os.environ.get("TGENGIN_TB_GRADERS", "4"))
GATE = threading.Semaphore(GRADERS)


def lock_of(name: str) -> threading.Lock:
    with LOCKS_LOCK:
        return LOCKS.setdefault(name, threading.Lock())


def judge(place: str, tid: str, said: str) -> dict:
    """判一份候选：就是此刻那个容器。**不缓存** —— 容器每一秒都可能变。"""
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
    """`ran` 那一格刚判过的那份。读一次就拿走 —— 下一轮是新的容器状态。"""
    name = container_of(place)
    with LOCKS_LOCK:
        hit = RESULTS.pop((name, said), None)
    if hit is None or time.time() - hit[0] > RESULT_TTL:
        return None
    return hit[1]


# ── note：这一栏说多少，按 --level ──────────────────────────────────────────


def note_of(got: dict) -> dict | str:
    """判 0 的时候多说的那一份。**级别定详略**，形状不随级别变。"""
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
    # 级别 3：断言原文。ctrf 的 `message` 是一行摘要，`trace` 是整段回溯。
    note["failures"] = [
        {"name": t.get("name", ""), "message": (t.get("message") or "")[:2000], "trace": (t.get("trace") or "")[:2000]}
        for t in failed[:40]
    ]
    return note


# ── HTTP ────────────────────────────────────────────────────────────────────


def task_of(body: dict) -> tuple[str, str, str]:
    """从内核送来的那份东西里挖出「哪道题」「在哪个容器」「它交的名字」。"""
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
    def log_message(self, *a):  # 默认那行访问日志太吵
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
            # **发题的口：给题面，不给答案。** `solution/` 一个字都不过来。
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

        # ── U 臂：任务结束后判一次容器终态（不经 G，只出成绩单）；/stop 收摊 ──
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

        # ── G 的两格。**一次判卷，两处读**。 ──────────────────────────────
        if self.path in ("/ran", "/passed"):
            tid, place, said = task_of(body)
            if tid not in BOOK:
                self._send({'error': 'UnknownTask'}, 422)
                return
            # 交的是候选的名字；空的也行，就叫 "done"。
            said = said or "done"
            try:
                if self.path == "/ran":
                    got = require_result(judge(place, tid, said))
                    ok = bool(got.get("ran"))
                else:
                    # **根。** 上游判 0 的话不必再说一遍。
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


# ── 自检 ────────────────────────────────────────────────────────────────────


def run_oracle(tid: str, name: str) -> int:
    """照 harbor `OracleAgent.run`：`solution/` 送到 `/solution`，跑 `solve.sh`，
    `DEBIAN_FRONTEND=noninteractive`，时限 = 官方 agent timeout。"""
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
    """两个干净容器：一个什么都不做该判 0；一个跑参考解该判 1。**装错了在这儿就炸。**"""
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
