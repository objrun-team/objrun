"""ChemBench 的判卷台 —— 引擎外面的一个 HTTP 服务。

    python stand.py [--port 7903] [--level 1] [--selftest]

引擎那边它就是两条句柄：

    http://127.0.0.1:7903/parsed     官方解析器从这份回答里**读得出**一个答案吗
    http://127.0.0.1:7903/correct    官方判据说**全对**吗（根）

句柄名本身就是地址，内核 POST 一份 JSON 过来，这儿回一份 JSON —— 没有别的协议。

## 判据是官方的，一行不改

`vendor/chembench/src/chembench` 是官方 pipeline（lamalab-org/chembench，钉在
45f8bad）。这个文件**不实现任何判断**，只做三件事：接 HTTP、把官方那三段串起来
（出题 → 解析 → 算分）、把结果缓存住。三段各自是官方哪个函数：

    出题   prompter.create_multiple_choice_prompt / general_prompt + utils.post_process_prompts
    解析   prompter.prepare_mcq_answer + utils.run_regex / prompter.prepare_general_answer
    算分   prompter.BasePrompter._calculate_metrics → metrics["all_correct"]

自己搓一套「找字母、比数字」的话，分数跟论文那张表就不可比 —— 那就白跑。

## 为什么不直接 import chembench

`prompter.py` 顶上 `from chembench.extractor import LLMExtractor`、`.model`、`.refusal`
—— 那三个要 litellm / tiktoken / openai / torch / transformers，是它「拿模型跑一遍」
和「用 BERT 认拒答」那半边，判卷用不上。`task.py` 要 `datasets`。所以这儿手工塞一个
同名的命名空间包绕过 `__init__.py`，再给那五个模块各塞一个空壳 —— prompter 的判卷
函数一个字不碰它们。**装的依赖因此只有 numpy / pint / fastcore / loguru / typing_extensions。**

## 官方判据里两处不包的东西，明说

1. **LLM 兜底解析不包。** 官方在正则解析失败时会调一个 LLM 从回答里抽答案
   （论文 A.8，Table A7：守规矩的模型 0–2.4% 的回答走了这条路，ReAct 智能体 24%）。
   这儿 `llm_extractor=None`：正则读不出来就是 0。**不是按题舍弃，一道题都没丢** ——
   舍弃的是「不按格式答也给分」这个宽容。`/parsed` 那一格会把格式要求说给它。
2. **拒答检测不包。** 官方先过一遍关键词 + BERT 认拒答，认出来直接 0。这儿不认：
   拒答的文本本来就解析不出答案，同样是 0。唯一的差别是官方检测的误报（回答里明明
   有 [ANSWER] 却被当成拒答）—— 官方判 0，这儿照判。偏向 solver，幅度在 1% 以内。

## 12 道判不出 1 的题

数值题的官方容差是 `mae < 0.01 * target`（`_calculate_metrics`，HF 数据集没有
per-task 的 tolerance 字段，所以永远走这条默认）。target ≤ 0 的 12 道题容差 ≤ 0，
**填对了也判 0**。这是官方判据自己的性质，不改它 —— 这 12 道排除在批外，按 0 计
（见 `SKIP`，`/health` 里列着）。

## 答案不出这个进程

题库在 `chembench.jsonl` 里，**只有这个进程读它**。`/problems` 发题只发官方拼好的
题面（选择题带 A./B./… 选项文字，这本来就是题面的一部分），`target` / `target_scores`
一个字都不过来。跟 cmt 一样：**这不是隔离** —— solver 的 bash 跟台子在同一台机器上，
`cat ~/.cache/tgengin-chembench/chembench.jsonl` 就是整本答案。装容器改的是路径，
不是可达性；真要挡住得把 solver 关进沙箱，那是 `place` 那一维的事。

## 分级：这一栏说多少

`--level` 定判 0 时 `note` 那一栏写多细。**每个级别是一次单独的实验**。引擎不知道
有这回事，G 的形状也不随级别变。

    0   只有过没过
    1   + 断在哪一段（parse / grade）+ 官方解析器从你的文本里读出了什么（回显，不漏 GT）
    2   + 选择题：该选几个、你选了几个、错了几个；数值题：你的数偏大还是偏小
    3   + 选择题：哪几个字母选错了；数值题：相对误差是多少（**等于把答案给它**）
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# **题库和判据不在仓库里，在判卷台这一侧。** solver 手上有 read / glob / bash，
# 放仓库里的话它 glob 一下就找到。够不着，不是不许。
HOME_DIR = Path(os.environ.get("TGENGIN_CHB_HOME", Path.home() / ".cache" / "tgengin-chembench"))
SRC = HOME_DIR / "vendor" / "chembench" / "src"
DATA = Path(os.environ.get("TGENGIN_CHB_DATA", HOME_DIR / "chembench.jsonl"))

LEVEL = int(os.environ.get("TGENGIN_CHB_LEVEL", "1"))


# ── 官方代码 ────────────────────────────────────────────────────────────────


def load_official():
    """把官方 prompter / utils / constant 加载进来，**不碰 __init__.py，不装模型那半边**。"""
    if not (SRC / "chembench" / "prompter.py").exists():
        raise SystemExit(f"the official grading code is missing: {SRC} (run setup.sh first)")
    sys.path.insert(0, str(SRC))

    pkg = types.ModuleType("chembench")
    pkg.__path__ = [str(SRC / "chembench")]
    sys.modules["chembench"] = pkg

    # prompter.py 顶上 import 的五个重模块，各塞一个空壳。它只在 __init__ 和类型标注里
    # 碰它们；我们要的 prepare_* / _calculate_metrics / create_*_prompt 一个都不碰。
    for name, classes in {
        "chembench.extractor": ["LLMExtractor"],
        "chembench.model": ["ChemBenchModel"],
        "chembench.refusal": ["RefusalDetector"],
        "chembench.report": ["Report"],
        "chembench.task": ["Task"],
    }.items():
        m = types.ModuleType(name)
        for c in classes:
            setattr(m, c, type(c, (), {}))
        sys.modules[name] = m

    from chembench import constant, prompter, utils  # noqa: E402

    # 官方 __init__.py 就干这一件事（`logger.disable("chembench")`），照做 ——
    # 不然每次解析失败 loguru 都往 stderr 吼一段。
    from loguru import logger

    logger.disable("chembench")
    return prompter, utils, constant


PR, UT, CT = load_official()


class Judge:
    """只借官方 `BasePrompter` 的两个方法，不起它的 __init__（那要一个模型）。"""

    is_mcq = PR.BasePrompter.is_mcq
    _calculate_metrics = PR.BasePrompter._calculate_metrics


JUDGE = Judge()


# ── 题库 ────────────────────────────────────────────────────────────────────


def load_book() -> dict[str, dict]:
    """一行一题：`{uuid, topic, name, metrics, example:{input, target | target_scores}}`。"""
    if not DATA.exists():
        raise SystemExit(f"the problem set is missing: {DATA} (run setup.sh first)")
    book = {}
    for line in DATA.read_text(encoding="utf-8").splitlines():
        if line.strip():
            it = json.loads(line)
            book[it["uuid"]] = it
    return book


BOOK = load_book()


def task_like(item: dict):
    """`_calculate_metrics` 只看 `task._metrics` 和 `task._relative_tolerance`。
    HF 数据集没有 tolerance 字段（`TaskRegistry.from_huggingface` 里 `row.get` 拿到 None），
    所以这儿也是 None —— 官方于是走 `0.01 * target`。**照抄，不补。**"""
    return types.SimpleNamespace(_metrics=item["metrics"], _relative_tolerance=item.get("relative_tolerance"), _examples=[item["example"]])


def is_mcq(item: dict) -> bool:
    return JUDGE.is_mcq(task_like(item))


def unsolvable(item: dict) -> bool:
    """官方容差 `mae < 0.01 * target`：target ≤ 0 的题容差 ≤ 0，怎么答都是 0。"""
    if is_mcq(item):
        return False
    try:
        return float(item["example"]["target"]) <= 0
    except Exception:
        return True


# 排除在批外、按 0 计的题。
SKIP = sorted(u for u, it in BOOK.items() if unsolvable(it))


def prompt_of(item: dict) -> tuple[str, dict]:
    """官方题面：InstructionPrompter 那条路（模板 + 默认的 LaTeX 后处理）。
    回 `(题面, 字母→分数)`；数值题的 score_map 是空的。"""
    ex = item["example"]
    if is_mcq(item):
        prompt, score_map = PR.create_multiple_choice_prompt(ex)
    else:
        prompt, score_map = PR.general_prompt(ex), {}
    return UT.post_process_prompts(prompt), score_map


def pick(n: int, seed: int) -> list[str]:
    """点名：可用的题按 uuid 排好、按种子洗一次、取前 n 道。n=0 是全部。台子和发批脚本用同一条挑法。"""
    ids = [u for u in sorted(BOOK) if u not in SKIP]
    random.Random(seed).shuffle(ids)
    return ids[:n] if n > 0 else ids


# ── 判卷：官方三段 ──────────────────────────────────────────────────────────


def judge(said: str, item: dict) -> dict:
    """跑一遍官方判据。回一个 dict：`parsed` / `correct` 两格 + 排障用的中间量。

    分支照抄官方 `BasePrompter._process_single_result`，只把 `llm_extractor` 换成 None。
    """
    ex = item["example"]
    task = task_like(item)
    got: dict = {"mcq": is_mcq(item), "answer": None}
    _, score_map = prompt_of(item)
    target = ex["target_scores"] if got["mcq"] else ex["target"]

    try:
        if got["mcq"]:
            prepared = PR.prepare_mcq_answer(said, PR.MCQ_REGEX_TEMPLATE_1, example=ex, llm_extractor=None)
            # 官方在这儿直接 `run_regex(..., prepared)`。没有 LLM 兜底时 prepare 可能回 None，
            # 那会 TypeError —— 官方跑的时候兜底总在，走不到这条路。这儿把 None 当「没读出来」。
            answer = UT.run_regex(UT.create_multiple_choice_regex(list(score_map.keys())), prepared, return_first=False) if prepared else None
        else:
            answer = PR.prepare_general_answer(said, pattern=PR.FLOATQ_REGEX_TEMPLATE_1, llm_extractor=None)
    except Exception:
        raise

    got["answer"] = answer
    got["parsed"] = bool(answer) if got["mcq"] else (answer is not None)

    result = {"metrics": {}}
    JUDGE._calculate_metrics(result, answer, target, task, score_map)
    got["metrics"] = result["metrics"]
    got["correct"] = result["metrics"].get("all_correct") == 1

    # 下面这些只给 note 用，判决不看它们。
    if got["mcq"]:
        expected = {k for k, v in score_map.items() if v == 1}
        given = set(answer or [])
        got["n_options"] = len(score_map)
        got["expected_count"] = len(expected)
        got["given_count"] = len(given)
        got["wrong_count"] = len(given - expected) + len(expected - given)
        got["wrong_letters"] = sorted(given - expected)
    else:
        try:
            f, t = float(answer), float(target)
            got["direction"] = "above" if f > t else ("below" if f < t else "equal")
            got["relative_error"] = abs(f - t) / abs(t) if t != 0 else math.inf
        except Exception:
            pass
    return got


# 一道题判一次就够 —— `parsed` 和 `correct` 两个节点问的是同一次判卷的两栏。
CACHE: dict[tuple[str, str], dict] = {}


def judged(tid: str, said: str) -> dict:
    key = (tid, said)
    if key not in CACHE:
        got = judge(said, BOOK[tid])
        CACHE[key] = got
        tail = said.replace("\n", " ")[-60:]
        print(
            f"[chb] {tid[:8]} ({'mcq' if got['mcq'] else 'num'}) parsed={got['parsed']} correct={got['correct']} "
            f"read={got['answer']!r}" + (f" err={got['error'][:60]}" if got.get("error") else "") + f" | ...{tail}",
            flush=True,
        )
    return CACHE[key]


# ── note：这一栏说多少，按 --level ──────────────────────────────────────────


def note_of(got: dict) -> dict | str:
    """判 0 的时候多说的那一份。**级别定详略**，形状不随级别变。"""
    if LEVEL <= 0:
        return ""
    kind = "mcq" if got["mcq"] else "numeric"
    if not got["parsed"]:
        return {
            "stage": "parse",
            "type": kind,
            "detail": (
                "the official parser found no answer in your text - put the final answer as [ANSWER]<letters>[/ANSWER], comma-separated letters only"
                if got["mcq"]
                else "the official parser found no number in your text - put the final answer as [ANSWER]<number>[/ANSWER], one number, dot as decimal separator, no units"
            ),
        }
    note: dict = {"stage": "grade", "type": kind, "parsed_as": got["answer"] if got["mcq"] else str(got["answer"])}
    if LEVEL <= 1:
        return note
    if got["mcq"]:
        note.update({"options_expected": got["expected_count"], "options_given": got["given_count"], "wrong_count": got["wrong_count"]})
    elif "direction" in got:
        note["direction"] = f"your number is {got['direction']} the target"
    if LEVEL <= 2:
        return note
    if got["mcq"]:
        note["wrong_letters"] = got["wrong_letters"]
    elif "relative_error" in got:
        note.update({"relative_error": got["relative_error"], "tolerance": "absolute error must be below 1% of the target"})
    return note


# ── HTTP ────────────────────────────────────────────────────────────────────


def task_of(body: dict) -> tuple[str, str]:
    """从内核送来的那份东西里挖出「哪道题」和「它答了什么」。

    内核送的是 `{node, moment, domain, feed, input}`，`input` 是 `{task, chain, result}`
    （树那条路）或 `{task, result}`（收尾那一路）。题号是 `[<跑名>/]chb-<uuid>`。
    """
    inp = body.get("input") or {}
    task = inp.get("task") or {}
    tid = str(task.get("id", "")).split("/")[-1]
    if tid.startswith("chb-"):
        tid = tid[4:]
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
            self._send({"ok": True, "items": len(BOOK), "usable": len(BOOK) - len(SKIP), "skipped": SKIP, "level": LEVEL})
            return
        if self.path.startswith("/problems"):
            # **发题的口：给题面，不给答案。** 题库在这一侧，发批那个脚本读不到。
            n, seed, topics = 0, 0, set()
            if "?" in self.path:
                for kv in self.path.split("?", 1)[1].split("&"):
                    if kv.startswith("n="):
                        n = int(kv[2:] or 0)
                    elif kv.startswith("seed="):
                        seed = int(kv[5:] or 0)
                    elif kv.startswith("topics="):
                        topics = {t for t in kv[7:].split(",") if t}
            ids = [u for u in pick(0, seed) if not topics or BOOK[u]["topic"] in topics]
            if n > 0:
                ids = ids[:n]
            out = []
            for u in ids:
                it = BOOK[u]
                prompt, score_map = prompt_of(it)
                out.append(
                    {
                        "id": f"chb-{u}",
                        "topic": it["topic"],
                        "type": "mcq" if is_mcq(it) else "numeric",
                        "prompt": prompt,
                        # 字母表本来就在题面里；单独给一份是让发批脚本不用再去解析题面。
                        "letters": list(score_map.keys()),
                    }
                )
            self._send(out)
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
        tid, said = task_of(body)
        if tid not in BOOK:
            self._send({"valid": False, "outcome": "grader_error", "error": "UnknownTask"}, 422)
            return
        if not said:
            self._send({"value": False, "note": {"stage": "collect", "detail": "nothing was handed in"}})
            return
        try:
            got = judged(tid, said)
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
        # **回 `{"value": bool}`。** G 的值域是封闭的，回别的东西内核当违约，一律归 0。
        self._send({"value": True} if ok else {"value": False, "note": note_of(got)})


# ── 自检 ────────────────────────────────────────────────────────────────────


def golden_of(item: dict) -> str:
    """拿题库自己的 GT 拼成一份按格式的回答。**只在自检里用。**"""
    _, score_map = prompt_of(item)
    if is_mcq(item):
        return "[ANSWER]" + ",".join(k for k, v in score_map.items() if v == 1) + "[/ANSWER]"
    return f"[ANSWER]{item['example']['target']}[/ANSWER]"


def wrong_of(item: dict) -> str:
    """一份必错的回答：选择题挑一个 0 分的字母（全对的题就多选一个），数值题给 target 的 1.5 倍。"""
    _, score_map = prompt_of(item)
    if is_mcq(item):
        zeros = [k for k, v in score_map.items() if v != 1]
        return "[ANSWER]" + (zeros[0] if zeros else ",".join(score_map)) + "[/ANSWER]"
    return f"[ANSWER]{float(item['example']['target']) * 1.5}[/ANSWER]"


def selftest() -> int:
    """GT 喂回去该判 1，错答该判 0，不带标签的裸文本该 parsed=0。**装错了在这儿就炸。**"""
    ids = pick(0, 0)
    mcq_single = [u for u in ids if is_mcq(BOOK[u]) and sum(v == 1 for v in BOOK[u]["example"]["target_scores"].values()) == 1][:3]
    mcq_multi = [u for u in ids if is_mcq(BOOK[u]) and sum(v == 1 for v in BOOK[u]["example"]["target_scores"].values()) > 1][:2]
    numeric = [u for u in ids if not is_mcq(BOOK[u])][:4]
    bad = 0
    for u in mcq_single + mcq_multi + numeric:
        it = BOOK[u]
        g, w = judge(golden_of(it), it), judge(wrong_of(it), it)
        # 裸文本里不能有数字词：官方数值解析的兜底会把 "one" 读成 1（NUM_WORDS_REGEX 不带词边界）。
        bare = judge("I am not sure about this.", it)
        ok = g["correct"] and g["parsed"] and not w["correct"] and w["parsed"] and not bare["parsed"]
        bad += 0 if ok else 1
        print(
            f"  {'ok  ' if ok else 'FAIL'} {u[:8]} [{it['topic']:<20}] {'mcq' if g['mcq'] else 'num'} "
            f"golden={int(g['correct'])} wrong={int(w['correct'])} bare_parsed={int(bare['parsed'])} "
            f"golden_text={golden_of(it)}",
            flush=True,
        )
    if SKIP:
        it = BOOK[SKIP[0]]
        g = judge(golden_of(it), it)
        print(f"  info {SKIP[0][:8]} target={it['example']['target']} golden={int(g['correct'])}  <- official tolerance <= 0, unsolvable, kept out of the batch")
    print(f"\n{len(mcq_single) + len(mcq_multi) + len(numeric) - bad} of {len(mcq_single) + len(mcq_multi) + len(numeric)} grade as expected; "
          f"{len(BOOK)} items, {len(SKIP)} skipped")
    return 1 if bad else 0


def main() -> int:
    global LEVEL
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("TGENGIN_CHB_PORT", "7903")))
    ap.add_argument("--level", type=int, default=LEVEL, help="how much the note field says: 0..3")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--bind", default="127.0.0.1")
    a = ap.parse_args()
    LEVEL = a.level
    if a.selftest:
        return selftest()
    print(f"[chb] {len(BOOK)} items ({len(SKIP)} skipped) | note level {LEVEL} | http://127.0.0.1:{a.port}/{{parsed,correct}}", flush=True)
    ThreadingHTTPServer((a.bind, a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
