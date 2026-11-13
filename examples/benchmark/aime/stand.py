r"""AIME 2024–2025 grading service: an HTTP service outside the engine.

    python3 stand.py [--port 7903] [--level 1] [--selftest]

The engine sees **two handles**:

    http://127.0.0.1:7903/parsed      First G node: can the submission be parsed as an integer in 0–999?
    http://127.0.0.1:7903/correct     G root: does that integer equal the official answer?

The handle name is the URL. The kernel POSTs JSON and receives JSON; there is no additional protocol.

## Use the official criterion unchanged

AIME's rule is simple: the answer is an integer in 0–999 and must match exactly. **Extracting that integer from text is the difficult part**: `\boxed{070}`, `\boxed{70.}`, `$70$`, a final "the answer is 70", or a chain such as `a+b = 70`. Every edge case in a custom regex could make our scores incomparable with others.

Delegate parsing and comparison to `math_verify` (HuggingFace Math-Verify, Apache-2.0), also used by OpenCompass's `MATHVerifyEvaluator`, lighteval, and Open-R1 for AIME.
This file **implements neither parsing nor comparison**. It accepts HTTP, calls `parse`/`verify`, and applies a **domain check** between them: the parsed value must be an integer in 0–999. That is AIME's rule, not a new criterion.

## Answers remain inside this process

The `aime.jsonl` corpus contains `answer`; **only this process reads it**. `/problems` removes `answer` before exposing statements.
As with CMT, **this is not isolation**: if the solver's bash shares the machine, `cat ~/.cache/tgengin-aime/aime.jsonl` can still read it. Moving the file changes the path, not reachability. Real isolation requires a solver sandbox, which belongs to the `place` dimension.

## Feedback levels: additional information on verdict 0

    0   Pass/fail only.
    1   Also the failed stage (parse/value) and the integer extracted from the submission.
    2   Also whether the official answer is higher or lower. **A leakage experiment, not a normal setting**:
        directional feedback lets binary search find any number in 0–999 in 10 queries, exactly c=10.
        Binary search does not work with pass/fail feedback alone (see G.md).
    3   Not provided. More information, such as the difference or matching digits, would reveal the answer."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# **Keep the corpus on the grader side, outside the repository.** A solver with read/glob/bash can find an answer-bearing JSONL in the repository with one glob (observed with CMT). Access must be prevented, not merely forbidden.
HOME_DIR = Path(os.environ.get("TGENGIN_AIME_HOME", Path.home() / ".cache" / "tgengin-aime"))
DATA = Path(os.environ.get("TGENGIN_AIME_DATA", HOME_DIR / "aime.jsonl"))

LEVEL = int(os.environ.get("TGENGIN_AIME_LEVEL", "1"))

# **AIME answer domain:** the official rule is an integer in 0–999. This is the complete criterion for the `parsed` node.
LO, HI = 0, 999

# Inspect only the **tail** of the submission. math_verify uses the last `\boxed{}`; tens of thousands of preceding reasoning characters do not help grading but can make ANTLR very slow. Its built-in timeout is unavailable in a worker thread (see `judge`).
TAIL = 20000


def load_official():
    r"""Load the official grader. Fail immediately on an invalid installation rather than discovering it during grading."""
    try:
        import sympy  # noqa: F401
        from math_verify import ExprExtractionConfig, LatexExtractionConfig, parse, verify
    except ImportError as e:
        raise SystemExit(f"math_verify is missing ({e}); run setup.sh first and start me with its venv")
    return parse, verify, LatexExtractionConfig, ExprExtractionConfig


PARSE, VERIFY, LatexCfg, ExprCfg = load_official()

# On the submission side, prioritize `\boxed{}` as recommended by math_verify, then any LaTeX environment, and finally bare expressions. **Use the official default configuration unchanged.**
PRED_CFG = [LatexCfg(boxed_match_priority=0), ExprCfg()]
# The reference answer is just an integer; `ExprExtractionConfig()` is sufficient, as described in the README.
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


# ── Grading ──


def integer_of(parsed: list) -> int | None:
    r"""Select the first **integer-valued** result from the official `parse` output.

    `parse` returns SymPy objects, possibly with the original string as a fallback. `\boxed{070}` yields `Integer(70)`, whereas `\boxed{70.0}` yields a `Float`; the latter is still integer-valued. On an AIME answer sheet, 70 and 70.0 represent the same number. A fallback string is not a successful parse."""
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
    r"""Run the official criterion and return `{parsed, value, correct, err}`.

    `parsing_timeout=None` / `timeout_seconds=None` are deliberate: math_verify implements timeouts with `signal.alarm`, which only works in the main thread. ThreadingHTTPServer handlers run elsewhere and would raise ValueError. Disable those timeouts and bound submission length with `TAIL` instead."""
    said = said[-TAIL:]
    try:
        got = PARSE(said, extraction_config=PRED_CFG, parsing_timeout=None)
        gold = PARSE(str(item["answer"]), extraction_config=GOLD_CFG, parsing_timeout=None)
    except Exception as e:  # The official implementation can raise; treat that as a failed parse.
        return {"parsed": False, "value": None, "correct": False, "err": f"{type(e).__name__}: {e}"}
    value = integer_of(got)
    parsed = value is not None and LO <= value <= HI
    if not parsed:
        return {"parsed": False, "value": value, "correct": False, "err": ""}
    # **The official `verify` decides equality**, not our own `==`. For Integer versus Integer it is numeric equality, matching `==`; the self-test compares both and fails if they differ.
    try:
        ok = bool(VERIFY(gold, got, timeout_seconds=None))
    except Exception as e:
        return {"parsed": True, "value": value, "correct": False, "err": f"{type(e).__name__}: {e}"}
    return {"parsed": True, "value": value, "correct": ok, "err": ""}


# Grade a given submission once per problem: `parsed` and `correct` request two fields of that same result.
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


# ── note: additional information on verdict 0, selected by --level ──


def note_of(tid: str, got: dict) -> dict | str:
    r"""Additional information on verdict 0. **The level controls detail**, while the response structure stays the same."""
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
    # **Level 2 is a leakage experiment.** Higher/lower feedback permits binary search: ⌈log2 1000⌉ = 10 queries guarantee success.
    # Binary search is impossible with pass/fail alone, which rules out only one number per query. This level measures that difference.
    gold = int(BOOK[tid]["answer"])
    note["gold_is"] = "higher" if gold > got["value"] else "lower"
    return note


# ── HTTP ────────────────────────────────────────────────────────────────────

ID_RE = re.compile(r"aime-(\d{4})-(I|II)-(\d{1,2})")


def task_of(body: dict) -> tuple[str, str]:
    r"""Extract the problem identity and submitted answer from the kernel payload.

    The kernel sends `{node, moment, domain, feed, input}`. `input` contains `{task, chain, result}` on the tree path or `{task, result}` during finalization. Extract the problem ID from `task.id`, such as `aime-2025-I-3`, with or without a `<run-name>/` prefix. Since `task.id` is globally unique, a second run must use a different run name."""
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
            self._send({"ok": True, "items": len(BOOK), "level": LEVEL})
            return
        if self.path.startswith("/problems"):
            # **Problem endpoint: expose statements, not answers.** The batch sender runs on the engine machine and cannot read the corpus.
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
            # **Root.** Do not repeat an upstream failure explanation; the preceding node already supplied it.
            feed = body.get("feed") or []
            if feed and feed[0].get("value") is not True:
                self._send({"value": False})
                return
            ok = got["correct"]
        # On pass, return only `{"value": true}`; on failure, include note. The domain is closed: the kernel treats any other shape as a contract violation and returns 0.
        self._send({"value": True} if ok else {"value": False, "note": note_of(tid, got)})


# ── Self-tests ──


def selftest() -> int:
    r"""Run four checks on every problem. **Fail here if the installation is wrong.**

    1. Feed back the official answer (`\boxed{N}`) -> parsed=1, correct=1.
    2. Pad it to three digits as on an AIME answer sheet -> same result (`\boxed{070}` must parse as 70).
    3. Answer +1 (mod 1000) -> parsed=1, correct=0.
    4. No integer or an out-of-range value (`\boxed{1000}`) -> parsed=0.
    Also compare official `verify` with `==`: they must agree on integers; disagreement indicates the wrong version."""
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
