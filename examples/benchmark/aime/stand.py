"""AIME 2024–2025 的判卷台 —— 引擎外面的一个 HTTP 服务。

    python3 stand.py [--port 7903] [--level 1] [--selftest]

引擎那边它是**两条句柄**：

    http://127.0.0.1:7903/parsed      G 的第一格：答卷里解析得出一个 0–999 的整数吗
    http://127.0.0.1:7903/correct     G 的根：这个整数跟官方答案相等吗

句柄名本身就是地址，内核 POST 一份 JSON 过来，这儿回一份 JSON —— 没有别的协议。

## 判据是官方的，一行不改

AIME 的判卷规则只有一句：答案是 0–999 的整数，相等就对。**「从一段文字里读出那个
整数」才是全部难点** —— `\\boxed{070}`、`\\boxed{70.}`、`$70$`、末尾一句 "the answer
is 70"、算式链 `a+b = 70`……自己写正则的话，每一条边界都是一次跟别人分数不可比的机会。

所以解析和比较都交给 `math_verify`（HuggingFace Math-Verify，Apache-2.0）——
OpenCompass 的 `MATHVerifyEvaluator`、lighteval、Open-R1 判 AIME 用的就是它。
这个文件**不实现任何解析和比较**，只做三件事：接 HTTP、调 `parse` / `verify`、
在两者之间加一道**值域闸**（解析出来的必须是 0–999 的整数）—— 那是 AIME 的规则，
不是我们的发明。

## 答案不出这个进程

题库 `aime.jsonl` 带 `answer`，**只有这个进程读它**。`/problems` 发题时把 `answer`
摘掉。跟 cmt 一样：**这不是隔离** —— solver 的 bash 跟这个进程在同一台机器上，
`cat ~/.cache/tgengin-aime/aime.jsonl` 一样拿到。改的是路径，不是可达性；真堵死得把
solver 关进沙箱，那是 `place` 那一维的事。

## 分级：判 0 的时候多说多少

    0   只有过没过
    1   + 断在哪一格（parse / value）+ 我们从你答卷里读出的那个整数
    2   + 官方答案比你的大还是小    ← **这是泄露实验，不是正常设置**：有了方向，
                                       二分 10 次就到 0–999 里任何一个数，c=10 刚好够。
                                       只回对错的话二分不成立（见 G.md）。
    3   没有。再多说一个字（差多少、哪几位对）就等于把答案交出去。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# **题库在判卷台这一侧，不在仓库里。** solver 手上有 read / glob / bash，仓库里放
# 一份带答案的 jsonl，它 glob 一下就找到（cmt 那边实测发生过）。够不着，不是不许。
HOME_DIR = Path(os.environ.get("TGENGIN_AIME_HOME", Path.home() / ".cache" / "tgengin-aime"))
DATA = Path(os.environ.get("TGENGIN_AIME_DATA", HOME_DIR / "aime.jsonl"))

LEVEL = int(os.environ.get("TGENGIN_AIME_LEVEL", "1"))

# **AIME 答案的值域。** 官方规则：0–999 的整数。这是 `parsed` 那一格的全部内容。
LO, HI = 0, 999

# 答卷只看**尾巴**。math_verify 认的是最后一个 `\boxed{}`，前面几万字的推理对判卷
# 没用，却能把 ANTLR 拖到很慢 —— 线程里又开不了它自带的超时（见 `judge`）。
TAIL = 20000


def load_official():
    """把官方判据加载进来。**装错了在这儿就炸**，不会等到判卷才发现。"""
    try:
        import sympy  # noqa: F401
        from math_verify import ExprExtractionConfig, LatexExtractionConfig, parse, verify
    except ImportError as e:
        raise SystemExit(f"math_verify is missing ({e}); run setup.sh first and start me with its venv")
    return parse, verify, LatexExtractionConfig, ExprExtractionConfig


PARSE, VERIFY, LatexCfg, ExprCfg = load_official()

# 答卷这一侧：`\boxed{}` 优先级最高（math_verify README 的建议），其次任何 latex 环境，
# 最后光秃秃的算式。**官方默认配置，一个数都不改。**
PRED_CFG = [LatexCfg(boxed_match_priority=0), ExprCfg()]
# 答案这一侧：只是个整数，按 README 的说法用 `ExprExtractionConfig()` 就够。
GOLD_CFG = [ExprCfg()]


def load_book() -> dict[str, dict]:
    if not DATA.exists():
        raise SystemExit(f"the problem set is missing: {DATA} (run setup.sh first)")
    book: dict[str, dict] = {}
    for line in DATA.read_text(encoding="utf-8").splitlines():
        if line.strip():
            it = json.loads(line)
            book[it["id"]] = it
    return book


BOOK = load_book()


# ── 判卷 ────────────────────────────────────────────────────────────────────


def integer_of(parsed: list) -> int | None:
    """官方 `parse` 吐出来的那串里，挑第一个**是整数**的。

    `parse` 回的是 sympy 对象（可能还夹着一个原文字符串作 fallback）。`\\boxed{070}`
    出来是 `Integer(70)`，`\\boxed{70.0}` 出来是 `Float`；后者按值算也是整数 ——
    AIME 的答题卡上写 70 和 70.0 是同一个数。字符串 fallback 不算解析出来。
    """
    import sympy

    for e in parsed:
        if not isinstance(e, sympy.Basic):
            continue
        try:
            if e.is_Integer:
                return int(e)
            if e.is_Number and e.is_finite and e == int(e):
                return int(e)
        except (TypeError, ValueError):
            continue
    return None


def judge(said: str, item: dict) -> dict:
    """跑一遍官方判据。回 `{parsed, value, correct, err}`。

    `parsing_timeout=None` / `timeout_seconds=None` **不是偷懒**：math_verify 的超时
    靠 `signal.alarm`，只能在主线程里用，ThreadingHTTPServer 的 handler 不在主线程，
    开着就抛 ValueError。所以关掉，改用 `TAIL` 截答卷长度来兜底。
    """
    said = said[-TAIL:]
    try:
        got = PARSE(said, extraction_config=PRED_CFG, parsing_timeout=None)
        gold = PARSE(str(item["answer"]), extraction_config=GOLD_CFG, parsing_timeout=None)
    except Exception as e:  # 官方那套自己会抛，抛了就是没解析出来
        return {"parsed": False, "value": None, "correct": False, "err": f"{type(e).__name__}: {e}"}
    value = integer_of(got)
    parsed = value is not None and LO <= value <= HI
    if not parsed:
        return {"parsed": False, "value": value, "correct": False, "err": ""}
    # **相等与否由官方 `verify` 说**，不是我们拿 `==` 比。它对 Integer vs Integer 就是
    # 数值相等，跟 `==` 结果一样 —— 自检里两条都对一遍，不一样就炸。
    try:
        ok = bool(VERIFY(gold, got, timeout_seconds=None))
    except Exception as e:
        return {"parsed": True, "value": value, "correct": False, "err": f"{type(e).__name__}: {e}"}
    return {"parsed": True, "value": value, "correct": ok, "err": ""}


# 一道题一份答卷判一次就够 —— `parsed` 和 `correct` 两格问的是同一次判卷的两栏。
CACHE: dict[tuple[str, str], dict] = {}


def verdict(tid: str, said: str) -> dict:
    key = (tid, said)
    if key not in CACHE:
        got = judge(said, BOOK[tid])
        if got.get("err"):
            raise RuntimeError("OfficialEvaluatorError")
        CACHE[key] = got
        tail = (said or "").replace("\n", " ")[-50:]
        print(
            f"[aime] {tid} parsed={got['parsed']} value={got['value']} correct={got['correct']}"
            + (f" err={got['err'][:60]}" if got["err"] else "")
            + f" | ...{tail}",
            flush=True,
        )
    return CACHE[key]


# ── note：判 0 的时候多说多少，按 --level ──────────────────────────────────


def note_of(tid: str, got: dict) -> dict | str:
    """判 0 的时候多说的那一份。**级别定详略**，形状不随级别变。"""
    if LEVEL <= 0:
        return ""
    if not got["parsed"]:
        if got["value"] is None:
            return {"stage": "parse",
                    "detail": "no integer could be read from your answer - end with \\boxed{N}, N an integer 0-999"}
        return {"stage": "parse", "read": got["value"],
                "detail": f"read {got['value']}, which is outside 0-999 - AIME answers are integers in 0-999"}
    note: dict = {"stage": "value", "read": got["value"], "detail": f"{got['value']} is not the answer"}
    if LEVEL <= 1:
        return note
    # **级别 2 是泄露实验。** 有了大小，猜数就成了二分：⌈log2 1000⌉ = 10 次必中。
    # 只回对错的时候二分不成立 —— 一次判卷只划掉一个数。这一级存在是为了量那条差距。
    gold = int(BOOK[tid]["answer"])
    note["gold_is"] = "higher" if gold > got["value"] else "lower"
    return note


# ── HTTP ────────────────────────────────────────────────────────────────────

ID_RE = re.compile(r"aime-(\d{4})-(I|II)-(\d{1,2})")


def task_of(body: dict) -> tuple[str, str]:
    """从内核送来的那份东西里挖出「哪道题」和「它答了什么」。

    内核送的是 `{node, moment, domain, feed, input}`，`input` 是 `{task, chain, result}`
    （树那条路）或者 `{task, result}`（收尾那一路）。题号从 `task.id` 里摘：
    `aime-2025-I-3`，前面带不带 `<跑名>/` 都行 —— `task.id` 全局唯一，第二趟要换跑名。
    """
    inp = body.get("input") or {}
    task = inp.get("task") or {}
    m = ID_RE.search(str(task.get("id", "")))
    tid = f"aime-{m.group(1)}-{m.group(2)}-{int(m.group(3))}" if m else ""
    result = inp.get("result")
    said = result.get("body") if isinstance(result, dict) else result
    if said is None:
        said = task.get("result")
    return tid, ("" if said is None else str(said)).strip()


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
            self._send({"ok": True, "items": len(BOOK), "level": LEVEL})
            return
        if self.path.startswith("/problems"):
            # **发题的口：给题面，不给答案。** 发批那个脚本跑在引擎那台机器上，读不到题库。
            n, year = 0, ""
            if "?" in self.path:
                for kv in self.path.split("?", 1)[1].split("&"):
                    if kv.startswith("n="):
                        n = int(kv[2:] or 0)
                    elif kv.startswith("year="):
                        year = kv[5:]
            items = [BOOK[i] for i in sorted(BOOK, key=lambda k: (BOOK[k]["year"], BOOK[k]["contest"], BOOK[k]["number"]))]
            if year:
                items = [it for it in items if str(it["year"]) == year]
            if n > 0:
                items = items[:n]
            self._send([
                {"id": it["id"], "year": it["year"], "contest": it["contest"],
                 "number": it["number"], "problem": it["problem"]}
                for it in items
            ])
            return
        self._send({"error": f"no {self.path} here"}, 404)

    def do_POST(self):
        length = int(self.headers.get("content-length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            body = {}
        if self.path not in ("/parsed", "/correct"):
            self._send({"error": f"no {self.path} here"}, 404)
            return
        tid, said = task_of(body)
        if tid not in BOOK:
            self._send({"valid": False, "outcome": "grader_error", "error": "UnknownTask"}, 422)
            return
        if not said:
            self._send({"value": False, "note": {"stage": "parse", "detail": "nothing was handed in - hand in \\boxed{N}"}})
            return
        try:
            got = verdict(tid, said)
        except Exception as error:
            self._send({"valid": False, "outcome": "grader_error", "error": type(error).__name__}, 503)
            return
        if self.path == "/parsed":
            ok = got["parsed"]
        else:
            # **根。** 上游判 0 的话不必再说一遍 —— 那句话已经在上一格里了。
            feed = body.get("feed") or []
            if feed and feed[0].get("value") is not True:
                self._send({"value": False})
                return
            ok = got["correct"]
        # 判 1 回裸 `{"value": true}`；判 0 带 note。值域是封闭的，回别的内核当违约归 0。
        self._send({"value": True} if ok else {"value": False, "note": note_of(tid, got)})


# ── 自检 ────────────────────────────────────────────────────────────────────


def selftest() -> int:
    """四条，每道题都过一遍。**装错了在这儿就炸。**

      1. 官方答案喂回去（`\\boxed{N}`）        → parsed=1 correct=1
      2. 官方答案按 AIME 答题卡写法补零到三位   → 同上（`\\boxed{070}` 得是 70）
      3. 答案 +1 (mod 1000)                   → parsed=1 correct=0
      4. 没有整数 / 越界（`\\boxed{1000}`）     → parsed=0
    另外把官方 `verify` 跟 `==` 对一遍：整数对整数它俩必须一致，不一致就是装错了版本。
    """
    bad = 0
    for tid in sorted(BOOK):
        gold = int(BOOK[tid]["answer"])
        a = judge(f"So the answer is $\\boxed{{{gold}}}$.", BOOK[tid])
        b = judge(f"\\boxed{{{gold:03d}}}", BOOK[tid])
        c = judge(f"\\boxed{{{(gold + 1) % 1000}}}", BOOK[tid])
        d = judge("I could not finish this one.", BOOK[tid])
        e = judge("\\boxed{1000}", BOOK[tid])
        ok = (
            a["parsed"] and a["correct"] and a["value"] == gold
            and b["parsed"] and b["correct"]
            and c["parsed"] and not c["correct"] and c["value"] == (gold + 1) % 1000
            and not d["parsed"]
            and not e["parsed"]
        )
        bad += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'} {tid:<16} gold={gold:<4} "
              f"a={a['parsed']}/{a['correct']} b={b['parsed']}/{b['correct']} "
              f"c={c['parsed']}/{c['correct']} d={d['parsed']} e={e['parsed']}"
              + (f" err={a['err'] or c['err']}" if (a['err'] or c['err']) else ""), flush=True)
    print(f"\n{len(BOOK) - bad} of {len(BOOK)} problems grade their own official answer as correct")
    return 1 if bad else 0


def main() -> int:
    global LEVEL
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("TGENGIN_AIME_PORT", "7903")))
    ap.add_argument("--level", type=int, default=LEVEL, help="how much the note field says: 0..2 (2 = leak experiment)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--bind", default="127.0.0.1")
    a = ap.parse_args()
    LEVEL = a.level
    if a.selftest:
        return selftest()
    print(f"[aime] {len(BOOK)} problems | note level {LEVEL} | "
          f"http://127.0.0.1:{a.port}/{{parsed,correct}}", flush=True)
    ThreadingHTTPServer((a.bind, a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
