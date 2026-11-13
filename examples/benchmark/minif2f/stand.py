r"""miniF2F (Lean 4) grading service: an HTTP service outside the engine, with Lean + Mathlib.

    python3 stand.py [--port 7903] [--level 1] [--backend repl|kimina] [--selftest [ID...]]

The engine sees **three handles**:

    http://127.0.0.1:7903/stated      Prerequisite: theorem declaration unchanged (verbatim comparison).
    http://127.0.0.1:7903/compiles    First node of G: Lean compilation has no errors.
    http://127.0.0.1:7903/sound       Root of G: no sorry; axioms belong to the allowed set.

Each handle is its own address. The kernel POSTs JSON and receives JSON; there is no additional protocol.

## The grader is the unchanged Lean compiler

This file **does not parse Lean or judge proofs**. It splits the candidate into declaration and proof body, sends official header + official declaration + candidate proof body to the Lean REPL, retrieves its JSON, and reads it with the two official Kimina functions (`kimina_client.models.is_error / has_sorry`).

An unchanged declaration is guaranteed **by construction**, not trust: compilation always uses the official header + official declaration + candidate proof body. `/stated` merely reports a prefix mismatch, following DeepSeek-Prover-V1.5’s protocol (`prover/lean/verifier.py` concatenates header + formal_statement + model completion for compilation).

The axiom node adds **one check beyond** Kimina `is_valid`: send `#print axioms <name>` with the proof to expose `sorryAx` / custom axioms. `native_decide` leaves `Lean.ofReduceBool`, accepted by leaderboard participants and allowed here by default; disable it with `TGENGIN_MF2F_STRICT_AXIOMS=1`.

## Feedback levels: how much this field reveals

`--level` determines the detail in `note`. **Each level is a separate experiment**; the shape of G does not change.

    0   Pass/fail only.
    1   + Failed node + unclosed goals (the ⊢ line) + axiom list.
    2   + Each error’s location (relative to the theorem line) and first line.
    3   + Raw Lean error messages.

## Backends

`repl` (default): this process maintains a pool of `lake env repl` processes (leanprover-community/repl, pinned to v4.15.0). Run the header (`import Mathlib …`) once to obtain env 0, then each proof with `env: 0`. Replace a process after N uses (the official v4.15.0 REPL has no `gc`, so memory only grows).

`kimina`: forward to a running Kimina Lean Server (`/verify`). The grader and REPL are identical; Kimina manages the pool. prisma/node cannot be installed on Sherlock (glibc 2.17), so this is not the default.

## Answers are not here

Lean grading has no reference answer: the proof is the answer, and compilation is the criterion. Kimina’s 226 published proofs (golden/) are used only for self-tests, never sent by `/problems` or included in problem statements. **They are online**, however, in a GitHub zip. Disabling web_search and listing repository names in `noSearch` is the send side’s responsibility."""

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

# **The dataset, Lean, Mathlib, and official code all live on the grading-service side**, outside the repository; setup.sh installs them.
HOME_DIR = Path(os.environ.get("TGENGIN_MF2F_HOME", Path.home() / ".cache" / "tgengin-minif2f"))
VENDOR = HOME_DIR / "vendor"
KIMINA_CLIENT = VENDOR / "kimina-lean-server" / "client"
MATHLIB = HOME_DIR / "mathlib4"
REPL_BIN = HOME_DIR / "repl" / ".lake" / "build" / "bin" / "repl"
DATA = HOME_DIR / "problems.jsonl"
GOLDEN = HOME_DIR / "golden"

LEVEL = int(os.environ.get("TGENGIN_MF2F_LEVEL", "1"))
# The header sets `set_option maxHeartbeats 0`: Lean has no internal limit, so **wall time is the only gate**.
# The 300 s limit matches the defaults in DeepSeek-Prover-V1.5’s verifier and Kimina VerifyRequestBody.
TIMEOUT = int(os.environ.get("TGENGIN_MF2F_TIMEOUT", "300"))
REPLS = int(os.environ.get("TGENGIN_MF2F_REPLS", "2"))
MAX_USES = int(os.environ.get("TGENGIN_MF2F_MAX_USES", "16"))
MEM_GB = int(os.environ.get("TGENGIN_MF2F_MEM_GB", "12"))
KIMINA_URL = os.environ.get("TGENGIN_MF2F_KIMINA", "http://127.0.0.1:8000")
BACKEND = os.environ.get("TGENGIN_MF2F_BACKEND", "repl")

# Lean’s three core axioms + the native_decide axiom. Any additional axiom means 0.
ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
if os.environ.get("TGENGIN_MF2F_STRICT_AXIOMS", "0") != "1":
    ALLOWED_AXIOMS.add("Lean.ofReduceBool")


# ── Official code ──


def load_official():
    r"""Load only `kimina_client.models`, **without executing `__init__.py`**.

    `__init__` imports sync/async clients too (httpx / tenacity / datasets…); grading uses only `is_error` / `has_sorry`, so installing the rest serves no purpose. This is the same technique used to bypass `cmtbench/__init__.py` in CMT."""
    if not (KIMINA_CLIENT / "kimina_client" / "models.py").exists():
        raise SystemExit(f"the official grading code is missing: {KIMINA_CLIENT} (run setup.sh first)")
    sys.path.insert(0, str(KIMINA_CLIENT))
    pkg = types.ModuleType("kimina_client")
    pkg.__path__ = [str(KIMINA_CLIENT / "kimina_client")]
    sys.modules["kimina_client"] = pkg
    from kimina_client import models  # noqa: E402

    return models


KM = load_official()


# ── Problem corpus ──


def load_book() -> dict[str, dict]:
    r"""488 tasks: 244 `test/<name>` (AI-MO corrected version) + 244 `valid/<name>` (DeepSeek-Prover-V1.5 version)."""
    if not DATA.exists():
        raise SystemExit(f"the problem set is missing: {DATA} (run setup.sh first)")
    book: dict[str, dict] = {}
    for line in DATA.read_text(encoding="utf-8").splitlines():
        if line.strip():
            it = json.loads(line)
            book[it["id"]] = it
    return book


BOOK = load_book()


# ── Split candidate: declaration | proof body ──

BLOCK_COMMENT = re.compile(r"/-.*?-/", re.S)
LINE_COMMENT = re.compile(r"--[^\n]*")
MARK = ":= by"


def norm(s: str) -> str:
    r"""Strip comments and collapse whitespace. **Do only these two things**: declarations contain no tactic blocks, so comments and whitespace do not change semantics."""
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
    r"""Does this line start a command? It must be unindented and start with a Lean command keyword (or `@[attr]`, `#cmd`).
    An unindented non-keyword line (a multiline signature continuation, as used by Kimina) belongs to the previous command."""
    if not ln or ln[0].isspace():
        return False
    tok = ln.split(None, 1)[0]
    return tok in COMMAND_KW or tok.startswith("@[") or tok.startswith("#")


def commands(plain: str) -> list[str]:
    r"""Split the comment-free candidate into commands: an unindented command keyword starts one; subsequent lines belong to it."""
    out: list[str] = []
    for ln in plain.splitlines():
        if starts_command(ln):
            out.append(ln)
        elif out:
            out[-1] += "\n" + ln
        elif ln.strip():
            out.append(ln)  # The first line is not a keyword; let the later checks reject it.
    return out


def split_cand(cand: str, item: dict) -> tuple[bool, str, str, str]:
    r"""Return `(declaration_unchanged, prelude, proof_body, rejection_reason)`.

    A candidate is a sequence of **top-level commands**. Accept only four kinds: `import Mathlib` / `import Aesop` (discard; present in the official header), `set_option maxHeartbeats N` (likewise), `open …` (keep; changes name resolution, not truth), and `lemma` / `theorem` (keep auxiliary lemmas: 8 of Kimina’s 225 published proofs and Seed-Prover’s entire approach prove lemmas before the main theorem). The final command must be **the verbatim official declaration + `:= by` + an indented proof body**. Reject all other top-level constructs (`def`, `axiom`, other `set_option`, `namespace`, `macro`…): they can alter semantics or bypass the kernel. Auxiliary-lemma `sorry` and axioms cannot escape: if the main theorem uses them, `#print axioms` exposes them; otherwise `sorries` is still nonempty."""
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


# ── Lean backend: submit code for compilation and retrieve REPL JSON ──


class ReplDied(Exception):
    pass


class Repl:
    r"""A persistent `lake env repl` with the header already evaluated (env 0). **Do not interpret output**; return it unchanged."""

    def __init__(self, header: str):
        self.header = header
        self.uses = 0
        self.dead = False
        self.lines: queue.Queue[bytes | None] = queue.Queue()
        mem = MEM_GB * 1024 ** 3

        def preexec():
            # Memory limit + a separate process group (kill the whole group on timeout). Kimina uses the same two measures.
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
        # Send the header as a separate command without env: only such commands can import. The returned env should be 0.
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
        r"""One request, one response. A REPL response is JSON followed by a blank line (the same convention as Kimina `_read_response`)."""
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
    r"""Pool by header. All 488 tasks share one header, so there is effectively one pool."""

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
                    break  # Capacity remains; start a new process.
                if self.idle:
                    self.idle.pop(0).kill()  # Pool full, with idle processes for other headers: evict one.
                    break
                self.cv.wait()  # All busy: wait for one to return.
            self.busy += 1
        try:
            if r is None:
                try:
                    r = Repl(header)  # Process startup + import Mathlib takes over ten seconds.
                except Exception as e:  # lake missing from PATH, header import failure… these are service problems, not candidate problems.
                    return {"error": f"repl failed to start: {e}"}
            try:
                got = r.run({"cmd": body, "env": 0}, timeout=TIMEOUT)
            except TimeoutError as e:
                r = None
                return {"error": str(e)}
            except ReplDied as e:
                r = None
                return {"error": f"repl died: {e}"}
            if r.uses >= MAX_USES:  # Without gc, the REPL only consumes more memory over time.
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
    r"""Forward to Kimina Lean Server `/verify`. The returned `response` is the REPL CommandResponse."""

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
        if "message" in got:  # REPL-level error (Error shape), not a Lean message.
            return {"error": str(got["message"])}
        # Kimina already shifts line numbers by its extracted header (import lines only). We need locations relative to
        # the theorem line, so subtract the full header’s line count.
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


# ── Grading ──

AXIOMS_RE = re.compile(r"'([^']+)' (?:does not depend on any axioms|depends on axioms: \[(.*)\])", re.S)


def judge(item: dict, cand: str) -> dict:
    r"""Run once. Return a dictionary containing three node values and raw REPL messages; select `note` content by feedback level."""
    got: dict = {"stated": False, "compiles": False, "sound": False, "messages": [], "sorries": [], "axioms": None}
    ok, prelude, body, why = split_cand(cand, item)
    got["why"] = why
    if not ok:
        return got
    got["stated"] = True
    # **Compile official header + candidate open/auxiliary lemmas + official declaration + candidate proof body**; the declaration cannot change.
    # Line numbers are relative to the candidate’s first command (with a prelude, theorem is not on line 1).
    name = item["name"]
    code = ((prelude.rstrip() + "\n\n") if prelude.strip() else "") + item["statement"].rstrip() + "\n" + body.rstrip() + "\n\n#print axioms " + name + "\n"
    t0 = time.monotonic()
    resp = LEAN.check(item["header"], code)
    # A dead REPL process (usually RLIMIT_AS exhaustion or a race with recycling after MAX_USES) is a service issue, not a candidate issue: retry once in a fresh process.
    # Observed 2026-09-25: amc12_2000_p1 scored 1 in 123 s on the first pass; the second failed after 48.8 s with “repl closed stdout”. Retry only once; another failure is backend_error.
    if "error" in resp and "repl died" in resp["error"]:
        resp = LEAN.check(item["header"], code)
    got["seconds"] = round(time.monotonic() - t0, 1)
    if "error" in resp:
        got["backend_error"] = resp["error"]
        return got
    got["messages"] = resp.get("messages") or []
    got["sorries"] = resp.get("sorries") or []
    # The two official functions: `is_error` checks for severity=error messages; `has_sorry` checks for nonempty sorries.
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


# ── note: feedback detail selected by --level ──


def goals_of(got: dict) -> list[str]:
    r"""Unclosed goals: `⊢` lines in `unsolved goals` errors, plus goals in sorries."""
    out: list[str] = []
    for m in got["messages"]:
        if m.get("severity") == "error" and m.get("data", "").startswith("unsolved goals"):
            out += [ln.strip() for ln in m["data"].splitlines() if ln.strip().startswith("⊢")]
    for s in got["sorries"]:
        out += [ln.strip() for ln in (s.get("goal") or "").splitlines() if ln.strip().startswith("⊢")]
    return [g[:400] for g in out[:8]]


def note_of(got: dict) -> dict | str:
    r"""Additional information on verdict 0. **The level controls detail**, while the response structure stays the same."""
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
    r"""Extract the task and submission from the kernel payload.

    The kernel sends `{node, moment, domain, feed, input}`; `input` is `{task, chain, result}` on the tree path or `{task, result}` during finalization. Use the final two segments of `task.id` as the task ID (also accepting `<run-name>/test/<name>`)."""
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
    r"""Extract Lean code from the submission. Use the contents of a ```lean fence if present; otherwise return it unchanged."""
    m = re.search(r"```(?:lean4?|lean 4)?\s*\n(.*?)```", said, re.S)
    return m.group(1) if m else said


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # Suppress the noisy default access log.
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
            # **Problem endpoint: problem statement, header, declaration.** There is no proof to send: a Lean task’s answer is its proof,
            # and none is stored here. Kimina’s 226 golden proofs are used only in self-tests, never through this endpoint.
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
        # **Do not repeat an upstream failure**: that explanation is already in the preceding node.
        feed = body.get("feed") or []
        if self.path != "/stated" and feed and feed[0].get("value") is not True:
            self._send({"value": False})
            return
        got = verdict(tid, cand_of(said))
        ok = got[self.path[1:]]
        # **Return a bare bool or {value, note}.** G has a closed value domain; any other response violates the contract and the kernel maps it to 0.
        self._send({"value": True} if ok else {"value": False, "note": note_of(got)})


# ── Self-tests ──


def golden_ids() -> list[str]:
    r"""Tasks with golden proofs whose declarations match the current dataset (Kimina’s zip predates several corrections)."""
    out = []
    for f in sorted(GOLDEN.glob("*.lean")):
        tid = f"test/{f.stem}"
        if tid in BOOK and split_cand(f.read_text(encoding="utf-8"), BOOK[tid])[0]:
            out.append(tid)
    return out


def selftest(ids: list[str]) -> int:
    r"""Replay Kimina’s published proofs: all three nodes should be 1. Replace the proof with `sorry`: compiles should be 1 and sound 0. **A faulty installation fails here.**"""
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
