"""miniF2F（Lean 4）的判卷台 —— 引擎外面的一个 HTTP 服务，手上有 Lean + Mathlib。

    python3 stand.py [--port 7903] [--level 1] [--backend repl|kimina] [--selftest [ID...]]

引擎那边它是**三条句柄**：

    http://127.0.0.1:7903/stated      前置：theorem 声明没被动过（跟原始陈述逐字比）
    http://127.0.0.1:7903/compiles    G 的第一格：Lean 编译没有 error
    http://127.0.0.1:7903/sound       G 的根：没有 sorry、公理只在允许的集合里

句柄名本身就是地址，内核 POST 一份 JSON 过来，这儿回一份 JSON —— 没有别的协议。

## 判据是 Lean 编译器，一行不改

这个文件**不解析 Lean、不判断证明**。它做四件事：把候选切成「声明 | 证明体」、
把官方 header + 官方声明 + 候选证明体送进 Lean REPL、拿回 REPL 的 JSON、
用 Kimina 官方那两个函数（`kimina_client.models.is_error / has_sorry`）读它。

「声明没被动过」不是靠信任，是靠**构造**：送去编译的永远是官方 header + 官方声明 +
候选的证明体。`/stated` 只是告诉它「你交的前缀跟官方不一样」——照 DeepSeek-Prover-V1.5
的协议（`prover/lean/verifier.py`：header + formal_statement + 模型补全拼起来编译）。

公理那一格是 Kimina `is_valid` 之外**多加的一道**：`#print axioms <name>` 跟着证明一起送，
`sorryAx` / 自定义 axiom 都在这儿现形。`native_decide` 留下 `Lean.ofReduceBool`，榜上各家
都认它，默认也认；`TGENGIN_MF2F_STRICT_AXIOMS=1` 关掉。

## 分级：这一栏说多少

`--level` 定 `note` 那一栏写多细。**每个级别是一次单独的实验**，G 的形状不随级别变。

    0   只有过没过
    1   + 哪一格断的 + 哪些 goal 没闭合（⊢ 那一行）+ 公理列表
    2   + 每条 error 的位置（相对 theorem 那一行）和第一行
    3   + Lean 报错原文

## 后端

`repl`（默认）：这个进程自己起 `lake env repl`（leanprover-community/repl，钉 v4.15.0），
常驻一池，header（`import Mathlib …`）跑一次拿到 env 0，每份证明用 `env: 0` 跑，
用满 N 次就换一个进程（官方 v4.15.0 的 REPL 没有 `gc`，内存只涨不落）。

`kimina`：转发到一个跑着的 Kimina Lean Server（`/verify`）。同一份判据、同一个 REPL，
只是池子归它管。Sherlock 上 prisma/node 装不上（glibc 2.17），所以默认不用它。

## 答案不在这儿

Lean 判卷没有「标准答案」—— 证明就是答案，判的是编译。Kimina 公开的那 226 份证明
（golden/）只在自检里用，`/problems` 不发它，题面里也没有它。**但网上有**（GitHub 的
zip），求解侧关掉 web_search、`noSearch` 写上仓库名，是 send 那一侧的事。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import resource
import signal
import subprocess
import sys
import threading
import time
import types
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# **题库、Lean、Mathlib、官方代码都在判卷台这一侧**，不进仓库。setup.sh 装的。
HOME_DIR = Path(os.environ.get("TGENGIN_MF2F_HOME", Path.home() / ".cache" / "tgengin-minif2f"))
VENDOR = HOME_DIR / "vendor"
KIMINA_CLIENT = VENDOR / "kimina-lean-server" / "client"
MATHLIB = HOME_DIR / "mathlib4"
REPL_BIN = HOME_DIR / "repl" / ".lake" / "build" / "bin" / "repl"
DATA = HOME_DIR / "problems.jsonl"
GOLDEN = HOME_DIR / "golden"

LEVEL = int(os.environ.get("TGENGIN_MF2F_LEVEL", "1"))
# header 里 `set_option maxHeartbeats 0` —— Lean 自己不设上限，**墙上时间是唯一的闸**。
# 300 s 照抄 DeepSeek-Prover-V1.5 verifier 和 Kimina VerifyRequestBody 的默认值。
TIMEOUT = int(os.environ.get("TGENGIN_MF2F_TIMEOUT", "300"))
REPLS = int(os.environ.get("TGENGIN_MF2F_REPLS", "2"))
MAX_USES = int(os.environ.get("TGENGIN_MF2F_MAX_USES", "16"))
MEM_GB = int(os.environ.get("TGENGIN_MF2F_MEM_GB", "12"))
KIMINA_URL = os.environ.get("TGENGIN_MF2F_KIMINA", "http://127.0.0.1:8000")
BACKEND = os.environ.get("TGENGIN_MF2F_BACKEND", "repl")

# Lean 核心那三条 + native_decide 那一条。多一条都是 0。
ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
if os.environ.get("TGENGIN_MF2F_STRICT_AXIOMS", "0") != "1":
    ALLOWED_AXIOMS.add("Lean.ofReduceBool")


# ── 官方代码 ────────────────────────────────────────────────────────────────


def load_official():
    """只加载 `kimina_client.models`，**不碰 `__init__.py`**。

    `__init__` 会把 sync/async client 一起拉进来（httpx / tenacity / datasets……），
    判卷只用 `is_error` / `has_sorry` 两个函数，装那一堆没意义。跟 cmt 那边绕
    `cmtbench/__init__.py` 是同一招。
    """
    if not (KIMINA_CLIENT / "kimina_client" / "models.py").exists():
        raise SystemExit(f"the official grading code is missing: {KIMINA_CLIENT} (run setup.sh first)")
    sys.path.insert(0, str(KIMINA_CLIENT))
    pkg = types.ModuleType("kimina_client")
    pkg.__path__ = [str(KIMINA_CLIENT / "kimina_client")]
    sys.modules["kimina_client"] = pkg
    from kimina_client import models  # noqa: E402

    return models


KM = load_official()


# ── 题库 ────────────────────────────────────────────────────────────────────


def load_book() -> dict[str, dict]:
    """488 道：`test/<name>` 244（AI-MO 修正版）+ `valid/<name>` 244（DeepSeek-Prover-V1.5 版）。"""
    if not DATA.exists():
        raise SystemExit(f"the problem set is missing: {DATA} (run setup.sh first)")
    book: dict[str, dict] = {}
    for line in DATA.read_text(encoding="utf-8").splitlines():
        if line.strip():
            it = json.loads(line)
            book[it["id"]] = it
    return book


BOOK = load_book()


# ── 候选切分：声明 | 证明体 ─────────────────────────────────────────────────

BLOCK_COMMENT = re.compile(r"/-.*?-/", re.S)
LINE_COMMENT = re.compile(r"--[^\n]*")
MARK = ":= by"


def norm(s: str) -> str:
    """去注释、压空白。**只做这两件事** —— 声明里没有 tactic 块，空白和注释都不改语义。"""
    s = BLOCK_COMMENT.sub(" ", s)
    s = LINE_COMMENT.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


ALLOWED_IMPORTS = {"Mathlib", "Aesop"}
AUX_HEAD = re.compile(r"^(?:@\[[^\]]*\]\s*)?(?:private\s+|protected\s+)?(lemma|theorem)\s+([^\s(\[{:]+)")


COMMAND_KW = {
    "import", "open", "set_option", "lemma", "theorem", "def", "abbrev", "axiom", "axioms", "instance", "structure",
    "inductive", "class", "namespace", "section", "end", "variable", "universe", "macro", "syntax", "notation",
    "infix", "infixl", "infixr", "prefix", "postfix", "elab", "macro_rules", "elab_rules", "declare_syntax_cat",
    "attribute", "example", "noncomputable", "private", "protected", "partial", "unsafe", "mutual", "deriving",
    "opaque", "initialize", "builtin_initialize", "register_option", "scoped", "local", "omit", "include", "export",
    "add_decl_doc", "unseal", "seal", "run_cmd", "run_tac",
}


def starts_command(ln: str) -> bool:
    """这一行开一条新命令吗：顶格，且第一个词是 Lean 的命令关键字（或 `@[attr]`、`#cmd`）。
    顶格但不是关键字的行（多行签名的续行，Kimina 就这么排版）归上一条。"""
    if not ln or ln[0].isspace():
        return False
    tok = ln.split(None, 1)[0]
    return tok in COMMAND_KW or tok.startswith("@[") or tok.startswith("#")


def commands(plain: str) -> list[str]:
    """把去掉注释的候选切成命令：命令关键字的顶格行开一条，其余行归它。"""
    out: list[str] = []
    for ln in plain.splitlines():
        if starts_command(ln):
            out.append(ln)
        elif out:
            out[-1] += "\n" + ln
        elif ln.strip():
            out.append(ln)  # 第一行就不是关键字：让后面的检查去拒
    return out


def split_cand(cand: str, item: dict) -> tuple[bool, str, str, str]:
    """回 `(声明没被动过, 前置, 证明体, 为什么不是)`。

    候选 = 若干**顶格命令**。认的只有四种：`import Mathlib` / `import Aesop`（丢掉，官方 header 里有）、
    `set_option maxHeartbeats N`（同上）、`open …`（保留，只改名字解析，改不了真假）、
    `lemma` / `theorem`（辅助引理，保留 —— Kimina 公开的 225 份里 8 份、Seed-Prover 整个范式都是先写引理再证主定理）。
    最后一条命令必须是**官方声明逐字 + `:= by` + 缩进的证明体**。其余顶格的东西（`def`、`axiom`、别的
    `set_option`、`namespace`、`macro`……）一律拒 —— 那些能改语义或绕内核。辅助引理里的 `sorry` 和公理逃不掉：
    主定理用了它们，`#print axioms` 就现形；没用也有 `sorries` 非空。
    """
    plain = LINE_COMMENT.sub(" ", BLOCK_COMMENT.sub(" ", cand))
    cmds = commands(plain)
    if not cmds:
        return False, "", "", "empty submission"
    want_stmt = norm(item["statement"])
    name = item["name"]
    prelude: list[str] = []
    main = None
    for k, c in enumerate(cmds):
        head = c.split(None, 1)[0]
        if head == "import":
            mod = c.split(None, 2)[1] if len(c.split()) > 1 else ""
            if mod not in ALLOWED_IMPORTS:
                return False, "", "", f"import {mod!r} is not allowed; only Mathlib and Aesop, and the official header already has them"
            continue
        if head == "set_option":
            if not re.match(r"set_option\s+maxHeartbeats\s+\d+\s*$", c.strip()):
                return False, "", "", f"'{c.strip()[:40]}' - set_option is not allowed except maxHeartbeats"
            continue
        if head == "open":
            if "\n" in c.strip():
                return False, "", "", "an 'open' command must be one line"
            prelude.append(c.strip())
            continue
        i = c.find(MARK)
        if i >= 0 and norm(c[: i + len(MARK)]) == want_stmt:
            if k != len(cmds) - 1:
                return False, "", "", f"the official theorem must be the last command; {len(cmds) - 1 - k} command(s) follow it"
            main = c
            break
        m = AUX_HEAD.match(c.strip())
        if m:
            if m.group(2) == name:
                return False, "", "", (
                    f"'theorem {name}' is present but its statement differs from the official one - copy the official "
                    f"statement verbatim (only the tactics after '{MARK}' are yours)"
                )
            prelude.append(c.rstrip())
            continue
        return False, "", "", (
            f"a top-level command '{c.strip()[:40]}' is not allowed - only 'open', auxiliary lemma/theorem, and the "
            f"official statement 'theorem {name} … {MARK}' followed by indented tactics"
        )
    if main is None:
        return False, "", "", (
            "the official theorem statement was not found - copy it verbatim "
            f"(it starts with 'theorem {name}') and put your tactics after '{MARK}'"
        )
    body = main[main.find(MARK) + len(MARK):]
    if not body.strip():
        return False, "", body, f"nothing after '{MARK}' - the proof is empty"
    return True, "\n".join(prelude), body, ""


# ── Lean 后端：把一段代码送去编译，拿回 REPL 的 JSON ────────────────────────


class ReplDied(Exception):
    pass


class Repl:
    """一个常驻的 `lake env repl`，header 已经跑过（env 0）。**不解释输出**，原样回。"""

    def __init__(self, header: str):
        self.header = header
        self.uses = 0
        self.dead = False
        self.lines: queue.Queue[bytes | None] = queue.Queue()
        mem = MEM_GB * 1024 ** 3

        def preexec():
            # 内存上限 + 自己一个进程组（超时的时候整组杀）。Kimina 那边同样的两条。
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            os.setsid()

        self.proc = subprocess.Popen(
            ["lake", "env", str(REPL_BIN)],
            cwd=str(MATHLIB),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            preexec_fn=preexec,
        )
        threading.Thread(target=self._pump, daemon=True).start()
        # header 单独一条命令，不带 env —— 只有这种命令能 import。回来的 env 该是 0。
        r = self.run({"cmd": header}, timeout=max(TIMEOUT, 600))
        if r.get("env") != 0 or KM.is_error(r):
            self.kill()
            raise ReplDied(f"header failed to load: {json.dumps(r)[:300]}")

    def _pump(self):
        assert self.proc.stdout is not None
        for ln in self.proc.stdout:
            self.lines.put(ln)
        self.lines.put(None)

    def run(self, cmd: dict, timeout: int) -> dict:
        """一问一答。REPL 的回复是一段 JSON 后跟一个空行（Kimina `_read_response` 同一约定）。"""
        if self.dead or self.proc.poll() is not None:
            raise ReplDied("repl process is gone")
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write((json.dumps(cmd, ensure_ascii=False) + "\n\n").encode())
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            self.kill()
            raise ReplDied(f"broken pipe: {e}")
        buf: list[bytes] = []
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                self.kill()
                raise TimeoutError(f"lean timed out after {timeout}s")
            try:
                ln = self.lines.get(timeout=left)
            except queue.Empty:
                self.kill()
                raise TimeoutError(f"lean timed out after {timeout}s")
            if ln is None:
                self.kill()
                raise ReplDied("repl closed stdout")
            if not ln.strip():
                if buf:
                    break
                continue
            buf.append(ln)
        self.uses += 1
        try:
            return json.loads(b"".join(buf))
        except json.JSONDecodeError:
            self.kill()
            raise ReplDied(f"repl returned non-JSON: {b''.join(buf)[:200]!r}")

    def kill(self):
        self.dead = True
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except Exception:
            pass


class ReplPool:
    """按 header 分池。这套题 488 道只有一个 header，池子实际上就一个。"""

    def __init__(self, size: int):
        self.size = size
        self.idle: list[Repl] = []
        self.busy = 0
        self.cv = threading.Condition()

    def check(self, header: str, body: str) -> dict:
        with self.cv:
            while True:
                r = next((x for x in self.idle if x.header == header), None)
                if r is not None:
                    self.idle.remove(r)
                    break
                if self.busy + len(self.idle) < self.size:
                    break  # 还有位子，起一个新的
                if self.idle:
                    self.idle.pop(0).kill()  # 池满，闲着的都是别的 header：淘汰一个
                    break
                self.cv.wait()  # 全忙着：等一个回来
            self.busy += 1
        try:
            if r is None:
                try:
                    r = Repl(header)  # 起进程 + import Mathlib，十几秒
                except Exception as e:  # lake 不在 PATH、header 装不进去……都是台子的事，不是候选的
                    return {"error": f"repl failed to start: {e}"}
            try:
                got = r.run({"cmd": body, "env": 0}, timeout=TIMEOUT)
            except TimeoutError as e:
                r = None
                return {"error": str(e)}
            except ReplDied as e:
                r = None
                return {"error": f"repl died: {e}"}
            if r.uses >= MAX_USES:  # 没有 gc 的 REPL 只会越吃越多
                r.kill()
                r = None
            return got
        finally:
            with self.cv:
                self.busy -= 1
                if r is not None and not r.dead:
                    self.idle.append(r)
                self.cv.notify_all()


class Kimina:
    """转发给 Kimina Lean Server `/verify`。回来的 `response` 就是 REPL 的 CommandResponse。"""

    def check(self, header: str, body: str) -> dict:
        req = {"codes": [{"custom_id": "x", "proof": header + body}], "timeout": TIMEOUT}
        data = json.dumps(req).encode()
        try:
            with urllib.request.urlopen(
                urllib.request.Request(f"{KIMINA_URL}/verify", data=data, headers={"content-type": "application/json"}),
                timeout=TIMEOUT + 60,
            ) as resp:
                out = json.loads(resp.read())
        except Exception as e:
            return {"error": f"kimina server: {e}"}
        r = (out.get("results") or [{}])[0]
        if r.get("error"):
            return {"error": str(r["error"])}
        got = r.get("response") or {}
        if "message" in got:  # REPL 级错误（Error 形状），不是 Lean 消息
            return {"error": str(got["message"])}
        # Kimina 把行号按它切出来的 header（只有 import 行）平移过了，我们要的是相对
        # theorem 那一行 —— 减掉整个 header 的行数。
        off = header.count("\n")
        for m in got.get("messages") or []:
            for k in ("pos", "endPos"):
                if m.get(k):
                    m[k]["line"] -= off
        for s in got.get("sorries") or []:
            for k in ("pos", "endPos"):
                if s.get(k):
                    s[k]["line"] -= off
        return got


LEAN: ReplPool | Kimina = Kimina() if BACKEND == "kimina" else ReplPool(REPLS)


# ── 判卷 ────────────────────────────────────────────────────────────────────

AXIOMS_RE = re.compile(r"'([^']+)' (?:does not depend on any axioms|depends on axioms: \[(.*)\])", re.S)


def judge(item: dict, cand: str) -> dict:
    """跑一遍。回一份字典：三格的值 + REPL 原样的消息，note 那一栏按级别从里面挑。"""
    got: dict = {"stated": False, "compiles": False, "sound": False, "messages": [], "sorries": [], "axioms": None}
    ok, prelude, body, why = split_cand(cand, item)
    got["why"] = why
    if not ok:
        return got
    got["stated"] = True
    # **送去编译的是 官方 header + 候选的 open/辅助引理 + 官方声明 + 它的证明体**，声明不可能被改。
    # 行号相对候选自己的第一条命令（有前置时 theorem 不在行 1）。
    name = item["name"]
    code = ((prelude.rstrip() + "\n\n") if prelude.strip() else "") + item["statement"].rstrip() + "\n" + body.rstrip() + "\n\n#print axioms " + name + "\n"
    t0 = time.monotonic()
    resp = LEAN.check(item["header"], code)
    # REPL 进程死掉（多半是 RLIMIT_AS 撞顶或用满 MAX_USES 后的回收撞上）是台子的事，不是候选的：换一个新进程再判一次。
    # 实测 2026-09-25：amc12_2000_p1 第一轮 123 s 判 1，第二轮 48.8 s 「repl closed stdout」。只重试一次，仍死就记 backend_error。
    if "error" in resp and "repl died" in resp["error"]:
        resp = LEAN.check(item["header"], code)
    got["seconds"] = round(time.monotonic() - t0, 1)
    if "error" in resp:
        got["backend_error"] = resp["error"]
        return got
    got["messages"] = resp.get("messages") or []
    got["sorries"] = resp.get("sorries") or []
    # 官方那两个函数。`is_error`：有 severity=error 的消息；`has_sorry`：sorries 非空。
    got["compiles"] = not KM.is_error(resp)
    for m in got["messages"]:
        mm = AXIOMS_RE.search(m.get("data", "")) if m.get("severity") == "info" else None
        if mm and mm.group(1) == name:
            got["axioms"] = [a.strip() for a in (mm.group(2) or "").split(",") if a.strip()]
    if got["compiles"]:
        got["sound"] = (
            not KM.has_sorry(resp) and got["axioms"] is not None and set(got["axioms"]) <= ALLOWED_AXIOMS
        )
    return got


CACHE: dict[tuple[str, str], dict] = {}
CACHE_LOCK = threading.Lock()


def verdict(tid: str, cand: str) -> dict:
    key = (tid, hashlib.sha256(cand.encode()).hexdigest())
    with CACHE_LOCK:
        hit = CACHE.get(key)
    if hit is not None:
        return hit
    got = judge(BOOK[tid], cand)
    with CACHE_LOCK:
        CACHE[key] = got
    print(
        f"[mf2f] {tid} stated={got['stated']} compiles={got['compiles']} sound={got['sound']} "
        f"axioms={got.get('axioms')} took={got.get('seconds', 0)}s"
        + (f" err={got['backend_error'][:80]}" if got.get("backend_error") else ""),
        flush=True,
    )
    return got


# ── note：这一栏说多少，按 --level ──────────────────────────────────────────


def goals_of(got: dict) -> list[str]:
    """没闭合的 goal：`unsolved goals` 那些 error 里的 `⊢` 行 + sorries 里的 goal。"""
    out: list[str] = []
    for m in got["messages"]:
        if m.get("severity") == "error" and m.get("data", "").startswith("unsolved goals"):
            out += [ln.strip() for ln in m["data"].splitlines() if ln.strip().startswith("⊢")]
    for s in got["sorries"]:
        out += [ln.strip() for ln in (s.get("goal") or "").splitlines() if ln.strip().startswith("⊢")]
    return [g[:400] for g in out[:8]]


def note_of(got: dict) -> dict | str:
    """判 0 的时候多说的那一份。**级别定详略**，形状不随级别变。"""
    if LEVEL <= 0:
        return ""
    if not got["stated"]:
        return {"stage": "stated", "detail": got["why"]}
    if got.get("backend_error"):
        return {"stage": "lean", "detail": got["backend_error"][:300]}
    errors = [m for m in got["messages"] if m.get("severity") == "error"]
    note: dict = {"stage": "compiles" if not got["compiles"] else "sound"}
    if not got["compiles"]:
        note["errors"] = len(errors)
        note["open_goals"] = goals_of(got)
    else:
        note["sorries"] = goals_of(got)
        note["axioms"] = got["axioms"]
        if got["axioms"] is not None:
            note["disallowed"] = sorted(set(got["axioms"]) - ALLOWED_AXIOMS)
    if LEVEL <= 1:
        return note
    note["at"] = [
        {"line": m["pos"]["line"], "col": m["pos"]["column"], "head": m["data"].splitlines()[0][:160] if m.get("data") else ""}
        for m in errors[:40]
    ]
    if LEVEL <= 2:
        return note
    note["lean"] = [
        {"severity": m.get("severity"), "line": m["pos"]["line"], "col": m["pos"]["column"], "data": (m.get("data") or "")[:4000]}
        for m in got["messages"][:40]
        if m.get("severity") != "info"
    ]
    return note


# ── HTTP ────────────────────────────────────────────────────────────────────


def task_of(body: dict) -> tuple[str, str]:
    """从内核送来的那份东西里挖出「哪道题」和「它交了什么」。

    内核送的是 `{node, moment, domain, feed, input}`，`input` 是 `{task, chain, result}`
    （树那条路）或 `{task, result}`（收尾那一路）。题号取 `task.id` 的最后两段
    （`<跑名>/test/<name>` 也认）。
    """
    inp = body.get("input") or {}
    task = inp.get("task") or {}
    parts = str(task.get("id", "")).split("/")
    tid = "/".join(parts[-2:]) if len(parts) >= 2 else ""
    result = inp.get("result")
    said = result.get("body") if isinstance(result, dict) else result
    if said is None:
        said = task.get("result")
    return tid, ("" if said is None else str(said))


def cand_of(said: str) -> str:
    """交上来的东西里挑出 Lean 代码。裹在 ```lean 围栏里的就取围栏里那段，否则原样。"""
    m = re.search(r"```(?:lean4?|lean 4)?\s*\n(.*?)```", said, re.S)
    return m.group(1) if m else said


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 默认那行访问日志太吵
        pass

    def _send(self, obj, code=200):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            self._send({"ok": True, "problems": len(BOOK), "level": LEVEL, "backend": BACKEND,
                        "allowed_axioms": sorted(ALLOWED_AXIOMS), "timeout": TIMEOUT})
            return
        if self.path.startswith("/problems"):
            # **发题的口：题面、header、声明。** 没有证明可发 —— Lean 题的答案就是证明，
            # 这儿本来就没有。Kimina 那 226 份 golden 只在自检里用，不走这条路。
            n, split = 0, "test"
            if "?" in self.path:
                for kv in self.path.split("?", 1)[1].split("&"):
                    if kv.startswith("n="):
                        n = int(kv[2:] or 0)
                    elif kv.startswith("split="):
                        split = kv[6:]
            items = [BOOK[k] for k in sorted(BOOK) if split in ("all", BOOK[k]["split"])]
            if n > 0:
                items = items[:n]
            self._send([
                {"id": it["id"], "name": it["name"], "split": it["split"], "informal": it["informal"],
                 "header": it["header"], "statement": it["statement"]}
                for it in items
            ])
            return
        self._send({"error": f"no {self.path} here"}, 404)

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        if self.path not in ("/stated", "/compiles", "/sound"):
            self._send({"error": f"no {self.path} here"}, 404)
            return
        tid, said = task_of(body)
        if tid not in BOOK:
            self._send({"value": False, "note": {"stage": "task", "detail": f"{tid} is not in the problem set"}})
            return
        if not said.strip():
            self._send({"value": False, "note": {"stage": "collect", "detail": "nothing was handed in - hand in the full Lean 4 proof"}})
            return
        # **上游判 0 的话不必再说一遍** —— 那句话已经在上一格里了。
        feed = body.get("feed") or []
        if self.path != "/stated" and feed and feed[0].get("value") is not True:
            self._send({"value": False})
            return
        got = verdict(tid, cand_of(said))
        ok = got[self.path[1:]]
        # **回一个裸 bool 或 {value, note}。** G 的值域是封闭的，回别的内核当违约归 0。
        self._send({"value": True} if ok else {"value": False, "note": note_of(got)})


# ── 自检 ────────────────────────────────────────────────────────────────────


def golden_ids() -> list[str]:
    """有 golden 证明、而且 golden 里的声明跟现在的题库一致的那些（Kimina 的 zip 早于几处修订）。"""
    out = []
    for f in sorted(GOLDEN.glob("*.lean")):
        tid = f"test/{f.stem}"
        if tid in BOOK and split_cand(f.read_text(encoding="utf-8"), BOOK[tid])[0]:
            out.append(tid)
    return out


def selftest(ids: list[str]) -> int:
    """Kimina 公开的证明喂回去，三格都该是 1；换成 `sorry`，compiles 1 而 sound 0。**装错了在这儿就炸。**"""
    if not GOLDEN.is_dir():
        raise SystemExit(f"no golden proofs at {GOLDEN} (run setup.sh first)")
    bad = 0
    for tid in ids:
        it = BOOK[tid]
        g = judge(it, (GOLDEN / f"{it['name']}.lean").read_text(encoding="utf-8"))
        s = judge(it, it["header"] + it["statement"] + "  sorry\n")
        ok = g["stated"] and g["compiles"] and g["sound"] and s["compiles"] and not s["sound"]
        bad += 0 if ok else 1
        print(
            f"  {'ok  ' if ok else 'FAIL'} {tid:<50} golden: stated={g['stated']} compiles={g['compiles']} "
            f"sound={g['sound']} axioms={g.get('axioms')} {g.get('seconds', 0)}s | sorry: compiles={s['compiles']} sound={s['sound']}"
            + (f" err={g.get('backend_error', '')[:60]}" if g.get("backend_error") else "")
            + (f" why={g['why'][:90]}" if not g["stated"] else "")
            + ("" if g["compiles"] or not g["stated"] else " first_error=" + next(
                (f"L{m['pos']['line']}: {(m.get('data') or '')[:160]!r}" for m in g["messages"] if m.get("severity") == "error"), "?")),
            flush=True,
        )
    print(f"\n{len(ids) - bad} of {len(ids)} golden proofs judged sound (and their sorry twins judged unsound)")
    return 1 if bad else 0


def main() -> int:
    global LEVEL, BACKEND, LEAN
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("TGENGIN_MF2F_PORT", "7903")))
    ap.add_argument("--level", type=int, default=LEVEL, help="how much the note field says: 0..3")
    ap.add_argument("--backend", choices=["repl", "kimina"], default=BACKEND)
    ap.add_argument("--selftest", nargs="*", metavar="TASK_ID", help="e.g. test/mathd_numbertheory_34")
    a = ap.parse_args()
    LEVEL = a.level
    if a.backend != BACKEND:
        BACKEND = a.backend
        LEAN = Kimina() if BACKEND == "kimina" else ReplPool(REPLS)
    if a.selftest is not None:
        return selftest(a.selftest or golden_ids()[:5])
    print(f"[mf2f] {len(BOOK)} problems | note level {LEVEL} | backend {BACKEND} | "
          f"axioms {sorted(ALLOWED_AXIOMS)} | http://127.0.0.1:{a.port}/{{stated,compiles,sound}}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
