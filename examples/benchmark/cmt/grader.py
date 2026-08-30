"""CMT-Benchmark 的判卷台 —— 引擎外面的一个 HTTP 服务。

    python grader.py [--port 7901] [--selftest]

引擎那边它就是两条句柄：

    http://127.0.0.1:7901/parsed     这份回答**解析得出来**吗
    http://127.0.0.1:7901/equiv      跟 GT **等价**吗

句柄名本身就是地址，内核 POST 一份 JSON 过来，这儿回一个 JSON —— 没有别的协议。

## 判据是官方的，一行不改

`vendor/cmt_benchmark_data/src/cmtbench` 是官方评分代码（LaTeX→Sympy，会处理
非对易算符）。这个文件**不实现任何判断**，只做三件事：接 HTTP、按官方
`scripts/evaluate.py` 里那套分支挑该用哪个 evaluator、把结果缓存住。

自己搓一套归一化去比字符串的话，分数跟论文里那张表就不可比了 —— 那就白跑。

## 为什么不直接 import cmtbench

`cmtbench/__init__.py` 顶上 `from .query import ...`，而 `query.py` 要
openai / anthropic / google-genai / tqdm / dotenv —— 那是它「拿模型跑一遍」那半边，
判卷用不上。所以这儿手工塞一个同名的命名空间包，绕过 `__init__.py`，
只加载 `evaluator` + `parser` + `parser_rules`。**装的依赖因此只有 sympy/numpy/regex。**

## oracle 不进求解那一侧

答案在 `cmt_data.jsonl` 里，**只有这个进程读它**。任务描述里只有题面，`/problems`
发题时也把 `solution` 摘掉 —— 答案不出这个进程。G 封存在引擎另一个库里，主库全接口
开放也翻不出来。

**还漏着一条**：solver 的 `bash` 跟引擎在同一台机器上，猜到 `127.0.0.1:7901` 的话，
`/equiv` 就是个能刷的验证 oracle。把这个进程装进容器**堵不住它** —— 端口还是发布在
同一台机器上。往句柄名里塞 token 也不行：句柄是主库 `handle` 表里的一行，`/query`
一条 SQL 就读出来了。真堵死得让 solver 那个 place 够不着这个端口（网络受限的沙箱），
那是 `place` 这一维的事。**这一条现在靠的是没告诉它地址，不是够不着。**
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# **题库和判据不在仓库里，在判卷台这一侧。**
#
# solver 手上有 read / glob / bash，而它干活的地方就是引擎那台机器 —— 放仓库里的话
# 它 glob 一下就找到。实测发生过：模型先 read grader.py 搞清楚判据怎么比，接着读官方
# parser 源码，然后 glob 到了 cmt_data.jsonl。**够不着，不是不许。**
HOME_DIR = Path(os.environ.get("TGENGIN_CMT_HOME", Path.home() / ".cache" / "tgengin-cmt"))
SRC = HOME_DIR / "vendor" / "cmt_benchmark_data" / "src"
DATA = Path(os.environ.get("TGENGIN_CMT_DATA", HOME_DIR / "cmt_data.jsonl"))


def load_official():
    """把官方那三个模块加载进来，**不碰 __init__.py**。"""
    if not (SRC / "cmtbench" / "evaluator.py").exists():
        raise SystemExit(f"没有官方评分代码：{SRC}（先跑 setup.sh）")
    sys.path.insert(0, str(SRC))
    pkg = types.ModuleType("cmtbench")
    pkg.__path__ = [str(SRC / "cmtbench")]
    sys.modules["cmtbench"] = pkg
    from cmtbench import evaluator, parser  # noqa: E402
    return evaluator, parser


EV, PARSER = load_official()


def load_book() -> dict[int, dict]:
    if not DATA.exists():
        raise SystemExit(f"没有题库：{DATA}（先跑 setup.sh）")
    book = {}
    for line in DATA.read_text(encoding="utf-8").splitlines():
        if line.strip():
            it = json.loads(line)
            book[int(it["index"])] = it
    return book


BOOK = load_book()


def judge(response: str, item: dict) -> tuple[bool, bool, str]:
    """跑一遍官方判据。回 `(解析出来了, 等价, 出了什么错)`。

    分支照抄官方 `scripts/evaluate.py` 的 `evaluate_response`：
    参数和函数都空 → 先试纯数值，不行退回符号；只有参数且不含 NC → 符号；
    其余（有函数、或参数里带 NC 非对易）→ 函数式。
    """
    solution = item["solution"]
    parameters = item.get("parameters", "") or ""
    functions = item.get("functions", "") or ""
    try:
        if parameters == "" and functions == "":
            if PARSER.parse_numeric_solution(solution).success:
                r = EV.evaluate_numeric_solution(response, solution_string=solution)
            else:
                r = EV.evaluate_solution(response, solution_string=solution, parameter_string=parameters)
        elif parameters != "" and functions == "" and "NC" not in parameters:
            r = EV.evaluate_solution(response, solution_string=solution, parameter_string=parameters)
        else:
            r = EV.evaluate_functional_solution(
                response, solution_string=solution, parameter_string=parameters, function_string=functions
            )
    except Exception as e:  # 官方那套自己会抛，抛了就是没解析出来
        return False, False, f"{type(e).__name__}: {e}"
    return bool(r.success), bool(r.is_equivalent), r.error_message or ""


# 一道题判一次就够 —— `parsed` 和 `equiv` 两个节点问的是同一次判卷的两栏。
CACHE: dict[tuple[str, int], tuple[bool, bool, str]] = {}


def answer_of(body: dict) -> tuple[str, dict | None, str]:
    """从内核送来的那份东西里挖出「这道题是哪道」和「模型答了什么」。

    内核送的是 `{node, moment, domain, feed, input}`，`input` 是
    `{task, chain, result}`（树那条路）或 `{task}`（收尾那一路）。
    """
    inp = body.get("input") or {}
    task = inp.get("task") or {}
    tid = str(task.get("id", ""))
    item = BOOK.get(int(tid[4:])) if tid.startswith("cmt-") and tid[4:].isdigit() else None
    result = inp.get("result") or {}
    said = result.get("body")
    if said is None:
        said = task.get("result")
    return tid, item, "" if said is None else str(said)


def verdict(body: dict) -> tuple[bool, bool]:
    tid, item, said = answer_of(body)
    if item is None:
        print(f"[cmt] {tid} 题库里没有这道", flush=True)
        return False, False
    key = (tid, hash(said))
    if key not in CACHE:
        ok, eq, err = judge(said, item)
        CACHE[key] = (ok, eq, err)
        head = (said or "").replace("\n", " ")[-60:]
        print(
            f"[cmt] {tid}（{item['type']}）parsed={ok} equiv={eq}"
            + (f" err={err[:60]}" if err else "")
            + f" ｜答尾 …{head}",
            flush=True,
        )
    ok, eq, _ = CACHE[key]
    return ok, eq


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
            self._send({"ok": True, "items": len(BOOK)})
        elif self.path.startswith("/problems"):
            # **发题的口：给题面，不给答案。**
            #
            # 题库在判卷台这一侧，发批那个脚本（跑在引擎那台机器上）读不到 ——
            # 那正是我们要的。它从这儿取题，`solution` 一个字都不过来：
            # 答案**不出这个进程**。
            n = 0
            if "?" in self.path:
                for kv in self.path.split("?", 1)[1].split("&"):
                    if kv.startswith("n="):
                        n = int(kv[2:] or 0)
            items = [BOOK[i] for i in sorted(BOOK)]
            if n > 0:
                items = items[:n]
            self._send(
                [
                    {
                        "index": it["index"],
                        "prompt": it["prompt"],
                        "parameters": it.get("parameters", ""),
                        "functions": it.get("functions", ""),
                        "type": it["type"],
                    }
                    for it in items
                ]
            )
        else:
            self._send({"error": "404"}, 404)

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        ok, eq = verdict(body)
        # **回一个裸 bool。** G 的值域是封闭的（bool / bool[n]），
        # 回别的东西内核当违约，一律归 0。
        if self.path == "/parsed":
            self._send(ok)
        elif self.path == "/equiv":
            self._send(eq)
        else:
            self._send({"error": "404"}, 404)


def selftest() -> None:
    """拿题库自己的 GT 当回答喂进去 —— 官方判据该说「解析得出来、而且等价」。"""
    bad = 0
    for idx in sorted(BOOK)[:5]:
        it = BOOK[idx]
        ok, eq, err = judge(it["solution"], it)
        flag = "√" if (ok and eq) else "×"
        if not (ok and eq):
            bad += 1
        print(f"  {flag} cmt-{idx}（{it['type']}）parsed={ok} equiv={eq} {err[:70]}")
    print(f"  拿 GT 当回答：5 道里 {5 - bad} 道判等价")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("TGENGIN_CMT_PORT", 7901)))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        raise SystemExit(0)
    print(f"[cmt] 判卷台起来了：http://0.0.0.0:{a.port}/{{parsed,equiv}}｜题库 {len(BOOK)} 道", flush=True)
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()
