r"""CMT-Benchmark grading service: an HTTP service outside the engine.

    python grader.py [--port 7901] [--selftest]

The engine sees two handles:

    http://127.0.0.1:7901/parsed     Can this response be **parsed**?
    http://127.0.0.1:7901/equiv      Is it **equivalent** to GT?

The handle name is its URL. The kernel POSTs JSON and receives JSON; there is no additional protocol.

## Use the official criterion unchanged

`vendor/cmt_benchmark_data/src/cmtbench` is the official grader (LaTeX -> SymPy, including noncommutative operators). This file **implements no grading decisions**: it accepts HTTP, selects evaluators using the branches in official `scripts/evaluate.py`, and caches results.
A custom normalization/string comparison would make scores incomparable with the paper's table and invalidate the run's purpose.

## Why not import cmtbench directly?

`cmtbench/__init__.py` imports `.query`, whose openai/anthropic/google-genai/tqdm/dotenv dependencies support model execution, not grading. Inject a namespace package with the same name to bypass `__init__.py` and load only `evaluator`, `parser`, and `parser_rules`. **Only sympy/numpy/regex must therefore be installed.**

## Keep the oracle away from the solver

Only this process reads the answers in `cmt_data.jsonl`. Task descriptions contain statements only, and `/problems` removes `solution`. Answers stay in this process. G is sealed in a separate engine database, inaccessible through the fully exposed main-database API.

**This is not isolation.** The solver's bash shares the engine machine, so `wsl.exe -- docker exec cmt-grader cat /oracle/cmt_data.jsonl` retrieves every answer. This was observed **without exploiting any vulnerability**: wsl.exe is in system32 and the account belongs to the Docker group.
A container changes paths, not reachability. This access route is deliberately left open because the detour is considered sufficiently long here; true prevention requires sandboxing the solver in the `place` dimension. See the README section on actually blocking GT access.

## Reachable `/parsed` and `/equiv` endpoints are **not** the leak

They return verdicts, which are intended for the agent: verdicts enter context after an attempt is marked dead, and the agent can explicitly query `verify` (`app/src/objective/tool.ts`). The same information cannot be legitimate when delivered automatically but cheating when requested.
The exploitable quantity is the **number** of requests (unlimited requests yield best-of-N with a perfect oracle), which is a budget issue. The tree gates it through `max_branches`, `max_dead_siblings`, and `solve_seconds`.
Only `solution` must remain hidden, and it never leaves this process."""

from __future__ import annotations

import argparse
import json
import os
import sys
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# **The corpus and grader live outside the repository, on the grader side.**
#
# The solver has read/glob/bash and runs on the engine machine. A repository copy is one glob away. In an observed run, the model read grader.py to understand comparison, then read the official parser, then found cmt_data.jsonl with glob. **Prevent access rather than merely prohibiting it.**
HOME_DIR = Path(os.environ.get("TGENGIN_CMT_HOME", Path.home() / ".cache" / "tgengin-cmt"))
SRC = HOME_DIR / "vendor" / "cmt_benchmark_data" / "src"
DATA = Path(os.environ.get("TGENGIN_CMT_DATA", HOME_DIR / "cmt_data.jsonl"))


def load_official():
    r"""Load the three official modules **without executing __init__.py**."""
    if not (SRC / "cmtbench" / "evaluator.py").exists():
        raise SystemExit(f"the official grading code is missing: {SRC} (run setup.sh first)")
    sys.path.insert(0, str(SRC))
    pkg = types.ModuleType("cmtbench")
    pkg.__path__ = [str(SRC / "cmtbench")]
    sys.modules["cmtbench"] = pkg
    from cmtbench import evaluator, parser  # noqa: E402
    return evaluator, parser


EV, PARSER = load_official()


def load_book() -> dict[int, dict]:
    if not DATA.exists():
        raise SystemExit(f"the problem set is missing: {DATA} (run setup.sh first)")
    book = {}
    for line in DATA.read_text(encoding="utf-8").splitlines():
        if line.strip():
            it = json.loads(line)
            book[int(it["index"])] = it
    return book


BOOK = load_book()


def judge(response: str, item: dict) -> tuple[bool, bool, str]:
    r"""Run the official criterion and return `(parsed, equivalent, error)`.

    Follow `evaluate_response` in official `scripts/evaluate.py`: with no parameters or functions, try numeric evaluation and fall back to symbolic; with parameters only and no NC, use symbolic; otherwise (functions or noncommutative NC parameters), use functional evaluation."""
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
    except Exception:
        # Official parsers report ordinary invalid candidates through r.success.
        # An unhandled evaluator exception is an unavailable measurement.
        raise
    return bool(r.success), bool(r.is_equivalent), r.error_message or ""


# One grading pass per problem is enough: `parsed` and `equiv` request two fields of the same result.
CACHE: dict[tuple[str, str], tuple[bool, bool, str]] = {}


def answer_of(body: dict) -> tuple[str, dict | None, str]:
    r"""Extract the problem identity and model answer from the kernel payload. The kernel sends `{node, moment, domain, feed, input}`; input is `{task, chain, result}` on the tree path or `{task}` during finalization."""
    inp = body.get("input") or {}
    task = inp.get("task") or {}
    tid = str(task.get("id", ""))
    tail = tid.rsplit("/", 1)[-1]
    item = BOOK.get(int(tail[4:])) if tail.startswith("cmt-") and tail[4:].isdigit() else None
    result = inp.get("result")
    said = result.get("body") if isinstance(result, dict) else result
    if said is None:
        said = task.get("result")
    return tid, item, "" if said is None else str(said)


def verdict(body: dict) -> tuple[bool, bool]:
    tid, item, said = answer_of(body)
    if item is None:
        print(f"[cmt] {tid} is not in the problem set", flush=True)
        raise LookupError("UnknownTask")
    key = (tid, said)
    if key not in CACHE:
        ok, eq, err = judge(said, item)
        CACHE[key] = (ok, eq, err)
        head = (said or "").replace("\n", " ")[-60:]
        print(
            f"[cmt] {tid} ({item['type']}) parsed={ok} equiv={eq}"
            + (f" err={err[:60]}" if err else "")
            + f" | answer tail ...{head}",
            flush=True,
        )
    ok, eq, _ = CACHE[key]
    return ok, eq


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
            self._send({"ok": True, "items": len(BOOK)})
        elif self.path.startswith("/problems"):
            # **Problem endpoint: statements only, no answers.**
            #
            # The corpus stays on the grader side, inaccessible directly to the sender on the engine machine. The sender fetches problems here without any `solution` content: answers **remain inside this process**.
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
        try:
            ok, eq = verdict(body)
        except Exception as e:
            self._send({"valid": False, "outcome": "grader_error", "error": type(e).__name__}, 422 if isinstance(e, LookupError) else 503)
            return
        # **Return a bare bool.** G has a closed domain (bool / bool[n]); any other result is a contract violation, mapped to 0 by the kernel.
        if self.path == "/parsed":
            self._send(ok)
        elif self.path == "/equiv":
            self._send(eq)
        else:
            self._send({"error": "404"}, 404)


def selftest() -> int:
    r"""Feed back the corpus GT; the official criterion should mark it both parsable and equivalent."""
    bad = 0
    selected = sorted(BOOK)[:10]
    for idx in selected:
        it = BOOK[idx]
        ok, eq, err = judge(it["solution"], it)
        flag = "√" if (ok and eq) else "×"
        wrong = judge(r"\boxed{999999999}", it)[1]
        junk = judge("I cannot provide an answer", it)[1]
        if not (ok and eq) or wrong or junk:
            bad += 1
        print(f"  {flag} cmt-{idx} ({it['type']}) parsed={ok} equiv={eq} wrong={wrong} junk={junk} {err[:70]}")
    print(f"  reference/wrong/format checks: {len(selected) - bad} of {len(selected)} pass")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("TGENGIN_CMT_PORT", 7901)))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    print(f"[cmt] grader up: http://0.0.0.0:{a.port}/{{parsed,equiv}} | {len(BOOK)} problems", flush=True)
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()
