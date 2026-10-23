"""GPQA Diamond 的判卷台 —— 引擎外面的一个 HTTP 服务。

    python stand.py [--port 7903] [--level 1] [--selftest]

引擎那边它就是两条句柄：

    http://127.0.0.1:7903/parsed     官方正则从回答里抠得出一个 A–D 吗
    http://127.0.0.1:7903/correct    抠出来的字母是不是正确选项（根）

句柄名本身就是地址，内核 POST 一份 JSON 过来，这儿回一份 JSON —— 没有别的协议。

## 判据是官方的，一行不改

`vendor/gpqa/baselines/` 是官方仓库（idavidrein/gpqa，钉在 56686c0）。判卷只有三处，
全在官方代码里，这个文件**不实现任何判断**：

    utils.load_examples(csv, seed)                 把四个选项打乱、记下正确项的下标
    AnswerPredictor.parse_sampled_answer(text)     五条正则依次试，抠出 A–D，抠不出回 None
    AnswerPredictor.LETTER_TO_INDEX[l] == correct_index      run_baseline.py main() 里那一行

**选项顺序是官方 `random.seed(seed)` + `random.shuffle` 定的**，seed 默认 0。发题（`/problems`）
和判卷读的是同一份 `load_examples` 的结果，所以求解器看到的 (A)(B)(C)(D) 跟判卷用的
下标是同一套。换了 seed 就是另一趟实验，`TGENGIN_GPQA_SEED` 改它。

## 为什么不直接 import utils

`utils.py` 顶上 `from openai import OpenAI` … `client = OpenAI()` —— 没有 OPENAI_API_KEY
在 import 那一刻就炸；`run_baseline.py` 又拉 `fire` / `tqdm` / `open_book`（bing 检索）。
那些是它「拿模型跑一遍」那半边，判卷用不上。所以这儿先往 `sys.modules` 里塞几个同名
空壳，再 import 官方模块 —— 官方代码一个字不改，**装的依赖因此只有 pandas / numpy。**

## 答案不进求解那一侧

`gpqa_diamond.csv` 里 `Correct Answer` 和 `Explanation` 两栏就是答案，**只有这个进程读它**。
`/problems` 发的是题面 + 打乱后的四个选项，`correct_index` 不过来。

**但这不是隔离，别当成隔离。** 数据集在 GitHub 上公开（zip 密码写在官方 README 里），
HF 上也有（gated 只是要登录）；solver 有网就能拿到整本。要挡得靠 `noSearch` 和关掉
`web_search`，那是 `place` / 工具那一维的事，不是这个文件能做的。

## 分级：`note` 那一栏说多少

四选一，判 0 之后能多说的东西极少 —— 「不是 X」在 m = 4 上就是排除法的一步。

    0   只有过没过
    1   + 哪一段断的（抠不出字母 / 字母错了）
    2   + 官方正则从你的回答里抠出的是哪个字母（给它看解析结果，不给答案）

没有 3。再多一个字就是答案本身（`Explanation` 那一栏就是标准解）。`--level 3` 按 2 办。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# **题库和判据不在仓库里，在判卷台这一侧。** solver 手上有 read / glob / bash，放仓库里
# 的话 glob 一下就找到（cmt 那边实测发生过）。够不着，不是不许。
HOME_DIR = Path(os.environ.get("TGENGIN_GPQA_HOME", Path.home() / ".cache" / "tgengin-gpqa"))
BASELINES = HOME_DIR / "vendor" / "gpqa" / "baselines"
DATA = Path(os.environ.get("TGENGIN_GPQA_DATA", HOME_DIR / "dataset" / "gpqa_diamond.csv"))
# 官方 `run_baseline.py` 的 `seed` 默认 0，选项顺序由它定。
SEED = int(os.environ.get("TGENGIN_GPQA_SEED", "0"))
LEVEL = int(os.environ.get("TGENGIN_GPQA_LEVEL", "1"))


def stub(name: str, **attrs) -> None:
    """往 `sys.modules` 里塞一个空壳，顶掉官方代码 import 的那些 API 客户端。

    **强制顶掉，不用 setdefault** —— 真装了 openai 的话，`OpenAI()` 没钥匙照样炸。
    """
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m


def load_official():
    """把官方那两个模块加载进来。判据的三处都在里面。"""
    if not (BASELINES / "run_baseline.py").exists():
        raise SystemExit(f"the official grading code is missing: {BASELINES} (run setup.sh first)")
    nothing = lambda *a, **k: None  # noqa: E731
    stub("openai", OpenAI=nothing, api_key=None)
    stub("anthropic", Anthropic=nothing)
    stub("dotenv", load_dotenv=nothing)
    stub("tqdm", tqdm=lambda it, *a, **k: it)
    stub("fire", Fire=nothing)
    stub("open_book", answer_single_question=nothing)
    sys.path.insert(0, str(BASELINES))
    import utils  # noqa: E402  官方 baselines/utils.py
    from run_baseline import AnswerPredictor  # noqa: E402  官方 baselines/run_baseline.py
    return utils, AnswerPredictor


UTILS, PREDICTOR = load_official()
LETTERS = "ABCD"


def load_book() -> dict[int, dict]:
    """题库：官方 `load_examples` 打乱过的 198 道，下标就是官方的 `question_id`。

    另读一遍 csv 只为拿 Record ID / 学科这几栏元数据 —— **答案那几栏不进 book**，
    留在 `Example.correct_index` 里，只有 judge() 和自检看它。
    """
    if not DATA.exists():
        raise SystemExit(f"the problem set is missing: {DATA} (run setup.sh first)")
    examples = UTILS.load_examples(str(DATA), seed=SEED)
    import pandas as pd  # 官方 utils 已经要它，这儿不多一个依赖

    df = pd.read_csv(DATA)
    if len(df) != len(examples):
        raise SystemExit(f"csv has {len(df)} rows but load_examples gave {len(examples)}")
    book: dict[int, dict] = {}
    for i, (ex, (_, row)) in enumerate(zip(examples, df.iterrows())):
        book[i] = {
            "index": i,
            "record_id": str(row.get("Record ID", "")),
            "domain": str(row.get("High-level domain", "")),
            "subdomain": str(row.get("Subdomain", "")),
            "question": ex.question,
            "choices": {"A": str(ex.choice1), "B": str(ex.choice2), "C": str(ex.choice3), "D": str(ex.choice4)},
            "_example": ex,  # 带 correct_index，**不出这个进程**
        }
    return book


BOOK = load_book()


def judge(response: str, item: dict) -> tuple[bool, bool, str | None]:
    """跑一遍官方判据。回 `(抠出字母了, 判对了, 抠出的字母)`。

    照抄官方 `run_baseline.py` main() 的 `sample` 分支：`parse_sampled_answer` 回 None
    就记 refusal 不比对；否则 `LETTER_TO_INDEX[sampled_answer] == example.correct_index`。
    """
    ex = item["_example"]
    letter = PREDICTOR.parse_sampled_answer(response or "")
    if letter is None:
        return False, False, None
    return True, PREDICTOR.LETTER_TO_INDEX[letter] == ex.correct_index, letter


# 一道题判一次就够 —— `parsed` 和 `correct` 两个节点问的是同一次判卷的两栏。
CACHE: dict[tuple[str, str], tuple[bool, bool, str | None]] = {}


def answer_of(body: dict) -> tuple[str, dict | None, str]:
    """从内核送来的那份东西里挖出「哪道题」和「模型答了什么」。

    内核送的是 `{node, moment, domain, feed, input}`，`input` 是 `{task, chain, result}`
    （树那条路）或 `{task, result}`（收尾那一路）。题号从 `task.id` 里摘：`[<跑名>/]gpqa-<下标>`。
    """
    inp = body.get("input") or {}
    task = inp.get("task") or {}
    tid = str(task.get("id", ""))
    tail = tid.rsplit("/", 1)[-1]
    item = BOOK.get(int(tail[5:])) if tail.startswith("gpqa-") and tail[5:].isdigit() else None
    result = inp.get("result")
    said = result.get("body") if isinstance(result, dict) else result
    if said is None:
        said = task.get("result")
    return tid, item, "" if said is None else str(said)


def verdict(body: dict) -> tuple[bool, bool, str | None]:
    tid, item, said = answer_of(body)
    if item is None:
        print(f"[gpqa] {tid} is not in the problem set", flush=True)
        raise LookupError("UnknownTask")
    key = (tid, said)
    if key not in CACHE:
        CACHE[key] = judge(said, item)
        ok, eq, letter = CACHE[key]
        tail = (said or "").replace("\n", " ")[-60:]
        print(f"[gpqa] {tid} ({item['domain']}) parsed={ok} correct={eq} letter={letter} | ...{tail}", flush=True)
    return CACHE[key]


# ── note：这一栏说多少，按 --level ──────────────────────────────────────────


def note_of(parsed: bool, letter: str | None) -> dict | str:
    """判 0 的时候多说的那一份。**级别定详略**，形状不随级别变。"""
    if LEVEL <= 0:
        return ""
    if not parsed:
        return {"stage": "parse",
                "detail": "no answer choice found - end your response with: The correct answer is (X)"}
    note: dict = {"stage": "answer", "detail": "the chosen option is not the correct one"}
    if LEVEL <= 1:
        return note
    note["parsed"] = letter  # 官方正则抠出来的是哪个字母 —— 它想答的和被读到的可能不是一个
    return note


# ── HTTP ────────────────────────────────────────────────────────────────────


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
            self._send({"ok": True, "items": len(BOOK), "seed": SEED, "level": LEVEL})
            return
        if self.path.startswith("/problems"):
            # **发题的口：给题面和打乱后的四个选项，不给 correct_index。**
            n = 0
            if "?" in self.path:
                for kv in self.path.split("?", 1)[1].split("&"):
                    if kv.startswith("n="):
                        n = int(kv[2:] or 0)
            items = [BOOK[i] for i in sorted(BOOK)]
            if n > 0:
                items = items[:n]
            self._send([{k: v for k, v in it.items() if not k.startswith("_")} for it in items])
            return
        self._send({"error": f"no {self.path} here"}, 404)

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        if self.path not in ("/parsed", "/correct"):
            self._send({"error": f"no {self.path} here"}, 404)
            return
        try:
            parsed, correct, letter = verdict(body)
        except Exception as e:
            self._send({"valid": False, "outcome": "grader_error", "error": type(e).__name__}, 422 if isinstance(e, LookupError) else 503)
            return
        if self.path == "/parsed":
            self._send({"value": True} if parsed else {"value": False, "note": note_of(False, None)})
            return
        # **根。** 上游判 0 的话不必再说一遍 —— 那句话已经在上一格里了。
        feed = body.get("feed") or []
        if feed and feed[0].get("value") is not True:
            self._send({"value": False})
            return
        self._send({"value": True} if correct else {"value": False, "note": note_of(parsed, letter)})


# ── 自检 ────────────────────────────────────────────────────────────────────


def selftest() -> int:
    """拿每道题的正确字母按官方格式喂回去，该判 1；错字母该判 0；没字母该抠不出。**装错了在这儿就炸。**"""
    bad = 0
    for i in sorted(BOOK):
        ex = BOOK[i]["_example"]
        right = LETTERS[ex.correct_index]
        wrong = LETTERS[(ex.correct_index + 1) % 4]
        a = judge(f"Reasoning... The correct answer is ({right})", BOOK[i])
        b = judge(f"The correct answer is ({wrong})", BOOK[i])
        c = judge("I am not sure.", BOOK[i])
        ok = a == (True, True, right) and b == (True, False, wrong) and c == (False, False, None)
        bad += 0 if ok else 1
        if not ok or i < 3:
            print(f"  {'ok  ' if ok else 'FAIL'} gpqa-{i:<4} right={a} wrong={b} none={c}")
    print(f"\n{len(BOOK) - bad} of {len(BOOK)} questions grade their own correct option as 1 (seed={SEED})")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("TGENGIN_GPQA_PORT", "7903")))
    ap.add_argument("--level", type=int, default=LEVEL, help="how much the note field says: 0..2 (3 behaves as 2)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    LEVEL = min(a.level, 2)
    if a.selftest:
        raise SystemExit(selftest())
    print(f"[gpqa] stand up: http://0.0.0.0:{a.port}/{{parsed,correct}} | {len(BOOK)} problems | seed {SEED} | level {LEVEL}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()
