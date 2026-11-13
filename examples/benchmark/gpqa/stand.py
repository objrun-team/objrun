r"""GPQA Diamond grading service: an HTTP service outside the engine.

    python stand.py [--port 7903] [--level 1] [--selftest]

The engine sees two handles:

    http://127.0.0.1:7903/parsed     Can the official regex extract an A–D answer?
    http://127.0.0.1:7903/correct    Is the extracted letter correct (root)?

Each handle is its own address. The kernel POSTs JSON and receives JSON; there is no additional protocol.

## The official grader, unchanged

`vendor/gpqa/baselines/` is the official repository (idavidrein/gpqa, pinned to 56686c0). All three grading components are in the official code; this file **implements no grading decisions**:

    utils.load_examples(csv, seed)                 Shuffle the four choices and record the correct index.
    AnswerPredictor.parse_sampled_answer(text)     Try five regexes in order; extract A–D or return None.
    AnswerPredictor.LETTER_TO_INDEX[l] == correct_index      That line in run_baseline.py main().

**Option order comes from the official `random.seed(seed)` + `random.shuffle`**, with seed 0 by default. `/problems` and grading read the same `load_examples` result, so the solver’s (A)(B)(C)(D) match the grader’s indices. Changing the seed creates a different experiment; use `TGENGIN_GPQA_SEED`.

## Why not import utils directly?

`utils.py` starts with `from openai import OpenAI` … `client = OpenAI()`, which fails at import time without OPENAI_API_KEY. `run_baseline.py` also imports `fire` / `tqdm` / `open_book` (Bing search). These support model execution and are unnecessary for grading. Insert empty modules with those names into `sys.modules` before importing the official modules. The official code stays unchanged, and **only pandas / numpy need to be installed**.

## Keep answers outside the solving side

The `Correct Answer` and `Explanation` columns in `gpqa_diamond.csv` contain the answers; **only this process reads them**. `/problems` sends the problem statement and four shuffled options, without `correct_index`.

**This is not isolation; do not treat it as such.** The dataset is public on GitHub (zip password in the official README) and also on HF (gating only requires login). A solver with network access can obtain the entire dataset. Blocking that requires `noSearch` and disabling `web_search`, which belong to the `place` / tool dimension and cannot be enforced here.

## Feedback levels: how much `note` reveals

With four choices, little can be added after a score of 0: “not X” is already one elimination step when m = 4.

    0   Pass/fail only.
    1   + Which stage failed (no letter extracted / incorrect letter).
    2   + The letter the official regex extracted (the parsing result, not the answer).

There is no level 3: anything further reveals the answer (`Explanation` is the reference solution). `--level 3` behaves as level 2."""

from __future__ import annotations

import argparse
import json
import os
import sys
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# **The dataset and grader live on the grading-service side, outside the repository.** The solver has read / glob / bash;
# inside the repository, a glob would find them (observed in CMT). Make them unreachable, rather than merely forbidden.
HOME_DIR = Path(os.environ.get("TGENGIN_GPQA_HOME", Path.home() / ".cache" / "tgengin-gpqa"))
BASELINES = HOME_DIR / "vendor" / "gpqa" / "baselines"
DATA = Path(os.environ.get("TGENGIN_GPQA_DATA", HOME_DIR / "dataset" / "gpqa_diamond.csv"))
# The official `run_baseline.py` defaults to `seed` 0, which determines option order.
SEED = int(os.environ.get("TGENGIN_GPQA_SEED", "0"))
LEVEL = int(os.environ.get("TGENGIN_GPQA_LEVEL", "1"))


def stub(name: str, **attrs) -> None:
    r"""Insert an empty module into `sys.modules` in place of the API clients imported by the official code.

    **Replace forcibly, not with setdefault**: if openai is installed, `OpenAI()` still fails without a key."""
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m


def load_official():
    r"""Load the two official modules containing all three grading components."""
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
    import utils  # noqa: E402  Official baselines/utils.py
    from run_baseline import AnswerPredictor  # noqa: E402  Official baselines/run_baseline.py
    return utils, AnswerPredictor


UTILS, PREDICTOR = load_official()
LETTERS = "ABCD"


def load_book() -> dict[int, dict]:
    r"""Dataset: 198 tasks shuffled by the official `load_examples`; the index is the official `question_id`.

    Read the CSV again only for metadata such as Record ID / subject. **Answer columns never enter book**; they stay in `Example.correct_index`, read only by judge() and self-tests."""
    if not DATA.exists():
        raise SystemExit(f"the problem set is missing: {DATA} (run setup.sh first)")
    examples = UTILS.load_examples(str(DATA), seed=SEED)
    import pandas as pd  # Already required by the official utils; this adds no dependency.

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
            "_example": ex,  # Contains correct_index; **never leaves this process**.
        }
    return book


BOOK = load_book()


def judge(response: str, item: dict) -> tuple[bool, bool, str | None]:
    r"""Run the official grader. Return `(letter_extracted, correct, extracted_letter)`.

    Copy the `sample` branch of the official `run_baseline.py` main(): if `parse_sampled_answer` returns None, record a refusal without comparison; otherwise compare `LETTER_TO_INDEX[sampled_answer] == example.correct_index`."""
    ex = item["_example"]
    letter = PREDICTOR.parse_sampled_answer(response or "")
    if letter is None:
        return False, False, None
    return True, PREDICTOR.LETTER_TO_INDEX[letter] == ex.correct_index, letter


# One grading pass per problem is enough: `parsed` and `correct` request two fields of the same result.
CACHE: dict[tuple[str, str], tuple[bool, bool, str | None]] = {}


def answer_of(body: dict) -> tuple[str, dict | None, str]:
    r"""Extract the task and model answer from the kernel payload.

    The kernel sends `{node, moment, domain, feed, input}`; `input` is `{task, chain, result}` on the tree path or `{task, result}` during finalization. Extract the task index from `task.id`: `[<run-name>/]gpqa-<index>`."""
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


# ── note: feedback detail selected by --level ──


def note_of(parsed: bool, letter: str | None) -> dict | str:
    r"""Additional information on verdict 0. **The level controls detail**, while the response structure stays the same."""
    if LEVEL <= 0:
        return ""
    if not parsed:
        return {"stage": "parse",
                "detail": "no answer choice found - end your response with: The correct answer is (X)"}
    note: dict = {"stage": "answer", "detail": "the chosen option is not the correct one"}
    if LEVEL <= 1:
        return note
    note["parsed"] = letter  # The letter extracted by the official regex: what it intended to answer may differ from what was parsed.
    return note


# ── HTTP ────────────────────────────────────────────────────────────────────


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
            self._send({"ok": True, "items": len(BOOK), "seed": SEED, "level": LEVEL})
            return
        if self.path.startswith("/problems"):
            # **Problem endpoint: send the problem statement and four shuffled options, without correct_index.**
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
        # **Root.** Do not repeat an upstream failure explanation; the preceding node already supplied it.
        feed = body.get("feed") or []
        if feed and feed[0].get("value") is not True:
            self._send({"value": False})
            return
        self._send({"value": True} if correct else {"value": False, "note": note_of(parsed, letter)})


# ── Self-tests ──


def selftest() -> int:
    r"""Submit each task’s correct letter in the official format: it must score 1; an incorrect letter must score 0; no letter must fail parsing. **A faulty installation fails here.**"""
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
