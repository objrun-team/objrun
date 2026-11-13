r"""ChemBench grading service: an HTTP service outside the engine.

    python stand.py [--port 7903] [--level 1] [--selftest]

The engine sees two handles:

    http://127.0.0.1:7903/parsed     Can the official parser **extract** an answer?
    http://127.0.0.1:7903/correct    Does the official criterion mark it **entirely correct**? (root)

The handle name is its URL. The kernel POSTs JSON and receives JSON; there is no additional protocol.

## Use the official criterion unchanged

`vendor/chembench/src/chembench` contains the official pipeline (lamalab-org/chembench, pinned at 45f8bad). This file **implements no grading decisions**. It accepts HTTP, connects the official three stages (prompt generation, parsing, scoring), and caches results:

    Prompt   prompter.create_multiple_choice_prompt / general_prompt + utils.post_process_prompts
    Parse    prompter.prepare_mcq_answer + utils.run_regex / prompter.prepare_general_answer
    Score    prompter.BasePrompter._calculate_metrics -> metrics["all_correct"]

A custom letter extractor or numeric comparator would make results incomparable with the paper's table and invalidate the run's purpose.

## Why not import chembench directly?

`prompter.py` imports `LLMExtractor`, `.model`, and `.refusal`, which require litellm/tiktoken/openai/torch/transformers for model execution and BERT refusal detection. Grading does not use those components; `task.py` also requires `datasets`.
Inject a namespace package with the same name to bypass `__init__.py`, then stub those five modules. The grading functions never access them. **The installed dependencies are therefore only numpy/pint/fastcore/loguru/typing_extensions.**

## Two official features deliberately omitted

1. **No LLM fallback parsing.** After regex failure, the official pipeline can ask an LLM to extract an answer (paper A.8, Table A7: 0–2.4% of compliant models' responses and 24% for ReAct agents). Here `llm_extractor=None`: failed regex extraction scores 0. **No questions are discarded**; only tolerance for incorrectly formatted answers is removed. `/parsed` explains the format.
2. **No refusal detection.** Upstream checks keywords and BERT first and assigns 0 to refusals. Refusals here normally fail answer extraction and also score 0. The difference is false positives where upstream flags an answer containing [ANSWER] as a refusal: upstream returns 0, while this service grades it. This favors the solver by less than 1%.

## Twelve questions cannot receive verdict 1

The official numeric tolerance is `mae < 0.01 * target` (`_calculate_metrics`). The HF dataset has no per-task tolerance, so this default always applies. For 12 questions with target ≤ 0, the tolerance is ≤ 0: **even correct answers score 0**. Preserve that property of the official criterion. Exclude these questions from submitted batches and count them as 0 (see `SKIP` and `/health`).

## Answers remain inside this process

Only this process reads `chembench.jsonl`. `/problems` exposes the official statements, including A./B./… choice text, but never `target` or `target_scores`.
As with CMT, **this is not isolation**. If solver bash shares the machine, `cat ~/.cache/tgengin-chembench/chembench.jsonl` reveals the answer set. Relocation changes paths rather than reachability; effective prevention requires a solver sandbox in the `place` dimension.

## Feedback detail

`--level` controls how much `note` says on verdict 0. **Each level is a separate experiment.** The engine does not know about levels, and G's structure stays fixed.

    0   Pass/fail only.
    1   Also the failed stage (parse/grade) and the official parser's extracted value (an echo, not GT leakage).
    2   Choice questions: required, submitted, and incorrect choice counts; numeric questions: whether the candidate is too high or low.
    3   Choice questions: incorrect letters; numeric questions: relative error (**effectively reveals the answer**)."""

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

# **Keep the corpus and grader outside the repository, on the grader side.** A solver with read/glob/bash could otherwise find them with one glob. Access must be prevented rather than merely forbidden.
HOME_DIR = Path(os.environ.get("TGENGIN_CHB_HOME", Path.home() / ".cache" / "tgengin-chembench"))
SRC = HOME_DIR / "vendor" / "chembench" / "src"
DATA = Path(os.environ.get("TGENGIN_CHB_DATA", HOME_DIR / "chembench.jsonl"))

LEVEL = int(os.environ.get("TGENGIN_CHB_LEVEL", "1"))


# ── Official code ──


def load_official():
    r"""Load the official prompter/utils/constant modules **without executing __init__.py or installing model-execution dependencies**."""
    if not (SRC / "chembench" / "prompter.py").exists():
        raise SystemExit(f"the official grading code is missing: {SRC} (run setup.sh first)")
    sys.path.insert(0, str(SRC))

    pkg = types.ModuleType("chembench")
    pkg.__path__ = [str(SRC / "chembench")]
    sys.modules["chembench"] = pkg

    # Stub the five heavyweight modules imported by prompter.py. They are used only in __init__ and type annotations; prepare_*, _calculate_metrics, and create_*_prompt do not access them.
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

    # Repeat the only action in official __init__.py: `logger.disable("chembench")`. Otherwise loguru writes to stderr on every parse failure.
    from loguru import logger

    logger.disable("chembench")
    return prompter, utils, constant


PR, UT, CT = load_official()


class Judge:
    r"""Borrow only two methods from official `BasePrompter`, without calling its model-dependent __init__."""

    is_mcq = PR.BasePrompter.is_mcq
    _calculate_metrics = PR.BasePrompter._calculate_metrics


JUDGE = Judge()


# ── Problem corpus ──


def load_book() -> dict[str, dict]:
    r"""One problem per row: `{uuid, topic, name, metrics, example:{input, target | target_scores}}`."""
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
    r"""`_calculate_metrics` reads only `task._metrics` and `task._relative_tolerance`. The HF dataset has no tolerance field (`row.get` in `TaskRegistry.from_huggingface` returns None), so use None here too, triggering the official `0.01 * target` default. **Preserve it without adding a replacement.**"""
    return types.SimpleNamespace(_metrics=item["metrics"], _relative_tolerance=item.get("relative_tolerance"), _examples=[item["example"]])


def is_mcq(item: dict) -> bool:
    return JUDGE.is_mcq(task_like(item))


def unsolvable(item: dict) -> bool:
    r"""Official tolerance is `mae < 0.01 * target`. When target ≤ 0, tolerance ≤ 0 and every answer scores 0."""
    if is_mcq(item):
        return False
    try:
        return float(item["example"]["target"]) <= 0
    except Exception:
        return True


# Questions excluded from the batch and counted as 0.
SKIP = sorted(u for u, it in BOOK.items() if unsolvable(it))


def prompt_of(item: dict) -> tuple[str, dict]:
    r"""Official statement generation follows InstructionPrompter: template plus default LaTeX postprocessing. Return `(statement, letter-to-score map)`; score_map is empty for numeric questions."""
    ex = item["example"]
    if is_mcq(item):
        prompt, score_map = PR.create_multiple_choice_prompt(ex)
    else:
        prompt, score_map = PR.general_prompt(ex), {}
    return UT.post_process_prompts(prompt), score_map


def pick(n: int, seed: int) -> list[str]:
    r"""Select available problems by sorting UUIDs, shuffling with the seed, and taking the first n. n=0 selects all. The grader and batch sender share this selection rule."""
    ids = [u for u in sorted(BOOK) if u not in SKIP]
    random.Random(seed).shuffle(ids)
    return ids[:n] if n > 0 else ids


# ── Grading: the three official stages ──


def judge(said: str, item: dict) -> dict:
    r"""Run the official criterion. Return `parsed`/`correct` plus intermediate diagnostic values. Follow the branches in official `BasePrompter._process_single_result`, changing only `llm_extractor` to None."""
    ex = item["example"]
    task = task_like(item)
    got: dict = {"mcq": is_mcq(item), "answer": None}
    _, score_map = prompt_of(item)
    target = ex["target_scores"] if got["mcq"] else ex["target"]

    try:
        if got["mcq"]:
            prepared = PR.prepare_mcq_answer(said, PR.MCQ_REGEX_TEMPLATE_1, example=ex, llm_extractor=None)
            # Upstream calls `run_regex(..., prepared)` directly. Without the LLM fallback, prepare can return None, causing TypeError; the official fallback normally prevents this path. Treat None as failed extraction.
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

    # The values below are for note only and do not affect the verdict.
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


# One grading pass per problem is enough: `parsed` and `correct` request two fields of the same result.
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


# ── note: feedback detail selected by --level ──


def note_of(got: dict) -> dict | str:
    r"""Additional information on verdict 0. **The level controls detail**, while the response structure stays the same."""
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
    r"""Extract the problem identity and answer from the kernel payload. The kernel sends `{node, moment, domain, feed, input}`; input is `{task, chain, result}` on the tree path or `{task, result}` during finalization. The problem ID is `[<run-name>/]chb-<uuid>`."""
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
    def log_message(self, *a):  # Suppress the noisy default access log.
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
            # **Problem endpoint: statements only, no answers.** The corpus stays on this side, beyond the batch sender's direct access.
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
                        # The choice letters already occur in the statement. Expose them separately so the batch sender need not parse the statement again.
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
            # **Root.** Do not repeat an upstream failure explanation; the preceding node already supplied it.
            feed = body.get("feed") or []
            if feed and feed[0].get("value") is not True:
                self._send({"value": False})
                return
            ok = got["correct"]
        # **Return `{"value": bool}`.** G has a closed domain; the kernel treats any other result as a contract violation and returns 0.
        self._send({"value": True} if ok else {"value": False, "note": note_of(got)})


# ── Self-tests ──


def golden_of(item: dict) -> str:
    r"""Build a correctly formatted response from the corpus GT. **Used only by self-tests.**"""
    _, score_map = prompt_of(item)
    if is_mcq(item):
        return "[ANSWER]" + ",".join(k for k, v in score_map.items() if v == 1) + "[/ANSWER]"
    return f"[ANSWER]{item['example']['target']}[/ANSWER]"


def wrong_of(item: dict) -> str:
    r"""Construct a guaranteed wrong answer: select a zero-score letter (or an extra letter if all are correct), or use 1.5 times the numeric target."""
    _, score_map = prompt_of(item)
    if is_mcq(item):
        zeros = [k for k, v in score_map.items() if v != 1]
        return "[ANSWER]" + (zeros[0] if zeros else ",".join(score_map)) + "[/ANSWER]"
    return f"[ANSWER]{float(item['example']['target']) * 1.5}[/ANSWER]"


def selftest() -> int:
    r"""Feeding back GT must score 1, a wrong answer must score 0, and untagged plain text must yield parsed=0. **Fail here on an invalid installation.**"""
    ids = pick(0, 0)
    mcq_single = [u for u in ids if is_mcq(BOOK[u]) and sum(v == 1 for v in BOOK[u]["example"]["target_scores"].values()) == 1][:3]
    mcq_multi = [u for u in ids if is_mcq(BOOK[u]) and sum(v == 1 for v in BOOK[u]["example"]["target_scores"].values()) > 1][:2]
    numeric = [u for u in ids if not is_mcq(BOOK[u])][:4]
    bad = 0
    for u in mcq_single + mcq_multi + numeric:
        it = BOOK[u]
        g, w = judge(golden_of(it), it), judge(wrong_of(it), it)
        # Plain text must contain no number words: the official numeric fallback reads "one" as 1 because NUM_WORDS_REGEX has no word boundaries.
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
