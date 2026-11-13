"""ChemIQ grading service: an HTTP service outside the engine.

    python3 stand.py [--port 7903] [--level 1] [--selftest]

The engine sees two handles:

    http://127.0.0.1:7903/parsed     Can the official AnswerParser extract an answer?
    http://127.0.0.1:7903/correct    Does the official AnswerVerifier accept it? (root)

The handle name is the address. The kernel POSTs JSON and receives JSON; there is no other protocol.

## Official grading by default; revised protocols require an explicit selection

`vendor/ChemIQ/utils/parser.py` and `utils/answer_verifier.py` are the official grading code
(oxpig/ChemIQ, pinned to 63826f6). By default, this adapter follows the official
`analysis.ipynb` parse -> check_answer sequence. This file supplies HTTP access,
fault isolation, caching, and explicitly selected grading protocols.

The official `check_answer` dispatches all five grading methods using each problem's
`verification_method`: exact_match (integers), range (noisy SAR), list_of_tuples
(atom mappings), canonical_smi_match (RDKit canonical comparison after removing
stereochemistry), and opsin (IUPAC name -> OPSIN web service -> SMILES -> RDKit
comparison). **There is no LLM-based grading component**; all grading is deterministic.

## Two installation details belong in this file

1. **Single-threaded HTTP.** The official `check_answer` uses `@timeout(2)`, implemented
   with `signal.alarm`, which can only be installed in the main thread. Running it in
   a ThreadingHTTPServer worker fails on the first request with
   `ValueError: signal only works in main thread`. Use `HTTPServer` and grade one
   problem at a time. Each grading call takes less than two seconds, which is sufficient.
2. **Change directory to the vendor root.** The official verifier reads and writes its
   OPSIN cache through the relative path `utils/opsin_cache.json`. Without changing
   directory, it creates a new empty `utils/` in the current directory and loses the cache.

## Explicit OPSIN grading profiles

The default `TGENGIN_CHEMIQ_OPSIN_PROFILE=rest` retains the official REST path.
Connection, HTTP, JSON failures, and timeouts are recorded as grading unavailable;
negative cache entries caused by failures are removed. Only an explicit response
that the service does not recognize the name counts as an incorrect answer.
`local-2.8` uses the host's pinned official OPSIN 2.8.0 JAR, passes SMILES through a
local file queue, and still uses the official RDKit branch for equivalence checking.
It neither reuses old positive REST cache entries nor falls back to REST. /health
records the version, JAR digest, and cache source. This is a separate local grading
variant and must not be described as equivalent to the old REST version.

`TGENGIN_CHEMIQ_LENGTH_POLICY=official-parsed` is the default length protocol and
preserves the official `len(str(parsed)) <= 200` check. Explicit `raw-input-length`
requires only atom-mapping problems to supply a single-line raw answer of at most
200 characters, then uses the official parser and `_check_list_of_tuples` for
comparison. It addresses compact mappings exceeding 200 characters after the
parser adds spaces, without changing grading for other problems. /health records
length_policy; scores from the two protocols must be reported separately.

### Failure handling in the REST profile

The official REST branch's `@timeout(2)` can cache connection failures as False or
return `{"is_correct": False, "opsin_smiles": None}`. This adapter separately records
transport, HTTP, and JSON failures, removes contaminated cache entries, and returns
HTTP 503 for grading unavailable. Only an explicitly unrecognized name is a valid
rejection. The local profile blocks the REST path before requests is called:
conversion completes locally before the official RDKit comparison. The old REST
version is unknown; no equivalence to the local version is claimed.

## Answers never enter the solver-facing response

Every row of `questions/chemiq.jsonl` contains `answer` (plus `meta_data` and top-level
`smiles`). **Only this process reads it.** `/problems` returns only the UUID, category,
problem statement, and answer format; no other field crosses that interface.
G is sealed in a separate engine database and cannot be read even through unrestricted
main-database API access.

**This is not isolation, however.** If the solver's bash and grader run on the same
machine, `cat ~/.cache/tgengin-chemiq/vendor/ChemIQ/questions/chemiq.jsonl` reveals all
answers. On Sherlock, `git clone oxpig/ChemIQ` also obtains them. Installing under the
home directory changes the path, not reachability. Complete isolation requires a
networkless solver sandbox, which belongs to the `place` dimension (see deepswe).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import tempfile
import shutil
import uuid as uuidlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# **The problem corpus and grading criteria live on the grader side, outside the repository.** A solver with read / glob
# would find them immediately if they were in the repository. setup.sh vendors the official repository here.
HOME_DIR = Path(os.environ.get("TGENGIN_CHEMIQ_HOME", Path.home() / ".cache" / "tgengin-chemiq"))
VENDOR = HOME_DIR / "vendor" / "ChemIQ"
QUESTIONS = VENDOR / "questions" / "chemiq.jsonl"

LEVEL = int(os.environ.get("TGENGIN_CHEMIQ_LEVEL", "1"))
OPSIN_PROFILE = os.environ.get("TGENGIN_CHEMIQ_OPSIN_PROFILE", "rest")
OPSIN_JOBS = Path(os.environ.get("TGENGIN_CHEMIQ_OPSIN_JOBS", "/opsin-jobs"))
LOCAL_OPSIN_SHA = "d25bc08f41b8f6fcd6f35e18ab83f3b8d9218cdb003d55c5f74aaefe2e0c68ab"
LENGTH_POLICY = os.environ.get("TGENGIN_CHEMIQ_LENGTH_POLICY", "official-parsed")
if OPSIN_PROFILE not in {"rest", "local-2.8"}:
    raise SystemExit("unsupported OPSIN profile")
if LENGTH_POLICY not in {"official-parsed", "raw-input-length"}:
    raise SystemExit("unsupported ChemIQ length policy")


def opsin_metadata() -> dict:
    if OPSIN_PROFILE == "rest":
        return {"profile": "rest", "version": None, "cache_origin": "fixed positive REST cache; original OPSIN version unknown"}
    meta = json.loads((OPSIN_JOBS / "profile.json").read_text(encoding="utf-8"))
    if meta.get("profile") != "local-2.8" or meta.get("version") != "2.8.0" or meta.get("jar_sha256") != LOCAL_OPSIN_SHA or meta.get("rest_fallback") is not False:
        raise RuntimeError("LocalOPSINProfileMismatch")
    return {key: meta[key] for key in ["profile", "version", "jar_sha256", "cache_origin", "rest_fallback", "transport", "external_requests"]}


if OPSIN_PROFILE == "local-2.8":
    opsin_metadata()  # Fail before serving when the pinned local profile is absent.


def local_opsin(name: str) -> str | bool:
    opsin_metadata()
    status = json.loads((OPSIN_JOBS / "status.json").read_text(encoding="utf-8"))
    if status.get("stopped") or time.time() - status.get("heartbeat", 0) > 30:
        raise RuntimeError("LocalOPSINBridgeUnavailable")
    job = uuidlib.uuid4().hex
    request = OPSIN_JOBS / f"{job}.request.json"
    response = OPSIN_JOBS / f"{job}.response.json"
    staging = request.with_suffix(".tmp")
    staging.write_text(json.dumps({"id": job, "name": name}, ensure_ascii=False), encoding="utf-8")
    staging.replace(request)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if response.exists():
            data = json.loads(response.read_text(encoding="utf-8"))
            if data.get("id") != job or data.get("profile") != "local-2.8" or data.get("jar_sha256") != LOCAL_OPSIN_SHA or data.get("external_requests") != 0:
                raise RuntimeError("LocalOPSINInvalidResponse")
            if data.get("valid") is not True:
                raise RuntimeError("LocalOPSINConversionUnavailable")
            smiles = data.get("smiles")
            if not isinstance(smiles, str) or data.get("recognized") is not bool(smiles):
                raise RuntimeError("LocalOPSINInvalidResponse")
            if smiles and VERIFIER._canonicalize_smiles(smiles) is None:
                raise RuntimeError("LocalOPSINInvalidResponse")
            return smiles or False
        time.sleep(0.02)
    raise RuntimeError("LocalOPSINBridgeTimeout")

# Task IDs have the form `chemiq-<uuid>` or `<run-name>/chemiq-<uuid>`. Extracting the UUID from the full string is sufficient.
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def load_official():
    """Load the two official classes. **Change to the vendor root first**; see installation detail 2 above."""
    if not (VENDOR / "utils" / "answer_verifier.py").exists() or not QUESTIONS.exists():
        raise SystemExit(f"the official grading code is missing: {VENDOR} (run setup.sh first)")
    sys.path.insert(0, str(VENDOR))
    from utils.answer_verifier import AnswerVerifier  # noqa: E402
    from utils.parser import AnswerParser  # noqa: E402

    # These are the two lines used by the official analysis.ipynb: parser with doClean=True and verifier over the same corpus.
    writable = Path(tempfile.mkdtemp(prefix="chemiq-cache-"))
    (writable / "utils").mkdir()
    original_cache = VENDOR / "utils/opsin_cache.json"
    if original_cache.exists():
        shutil.copyfile(original_cache, writable / "utils/opsin_cache.json")
    os.chdir(writable)
    verifier = AnswerVerifier(str(QUESTIONS))
    from rdkit import rdBase
    with rdBase.BlockLogs():
        verifier._opsin_cache = {key:value for key,value in verifier._opsin_cache.items() if value and verifier._canonicalize_smiles(value) is not None}
    if OPSIN_PROFILE == "local-2.8":
        # Reference-cache names are available only to self-test selection. Scoring
        # uses conversions from the pinned local version exclusively.
        verifier._opsin_cache = {}
        def cached_local_only(name):
            if name not in verifier._opsin_cache:
                raise RuntimeError("LocalOPSINCacheMissing")
            return verifier._opsin_cache[name]
        verifier._get_opsin = cached_local_only
    return AnswerParser(str(QUESTIONS), doClean=True), verifier


PARSER, VERIFIER = load_official()
# Use the corpus already loaded by the verifier; a second copy could drift.
BOOK: dict[str, dict] = VERIFIER.question_dict
OPSIN_FAILURE = None
import requests
_original_get = requests.get
def observed_get(*args, **kwargs):
    global OPSIN_FAILURE
    if OPSIN_PROFILE == "local-2.8":
        OPSIN_FAILURE = "OPSINRestDisabled"
        raise RuntimeError(OPSIN_FAILURE)
    try:
        response = _original_get(*args, **kwargs)
        if not (200 <= response.status_code < 300 or response.status_code == 404):
            OPSIN_FAILURE = "OPSINUnavailable"
        else:
            try:
                data = response.json()
                status = str(data.get("status", "")).upper() if isinstance(data, dict) else ""
                explicit_rejection = status == "FAILURE"
                smiles = data.get("smiles") if isinstance(data, dict) else None
                if not explicit_rejection and (response.status_code == 404 or not isinstance(smiles, str) or not smiles or VERIFIER._canonicalize_smiles(smiles) is None):
                    OPSIN_FAILURE = "OPSINInvalidResponse"
            except Exception:
                OPSIN_FAILURE = "OPSINInvalidResponse"
        return response
    except Exception:
        OPSIN_FAILURE = "OPSINUnavailable"
        raise
requests.get = observed_get


def judge(uuid: str, said: str) -> dict:
    """Run the official grading criteria once. Return `{parsed, correct, ...diagnostic fields}`.

    Follow the official `analysis.ipynb`: `parsed = parser.parse(uuid, raw)`, then
    `check_answer(uuid, parsed)`. The official parser returns False on failure, and
    check_answer rejects False. Pass False through without introducing a shortcut.
    """
    global OPSIN_FAILURE
    OPSIN_FAILURE = None
    q = BOOK[uuid]
    opsin = q["verification_method"] == "opsin"
    parsed = PARSER.parse(uuid, said)
    # The official parser uses `False` for extraction failure. Use `is False`, not `== False`, because integer 0 also equals False.
    ok = parsed is not False
    if q["verification_method"] == "list_of_tuples" and LENGTH_POLICY == "raw-input-length":
        # The revision changes the mapping length contract only. Preserve the
        # official parser, falsey guard, and set-of-tuples equality implementation.
        # Checking the delivered raw string avoids str(list)'s inserted spaces.
        raw_eligible = len(said) <= 200 and "\n" not in said and "\r" not in said
        correct = False
        if ok and parsed and raw_eligible:
            try:
                correct = bool(VERIFIER._check_list_of_tuples(parsed, uuid))
            except Exception as error:
                return {"parsed": ok, "correct": False, "parsed_value": parsed, "error": type(error).__name__}
        return {"parsed": ok, "correct": correct, "parsed_value": parsed, "opsin_smiles": None,
            "timed_out": False, "error": None, "length_policy": LENGTH_POLICY, "raw_input_length_eligible": raw_eligible}
    opsin_required = opsin and ok and bool(parsed) and "\n" not in str(parsed) and len(str(parsed)) <= 200
    if OPSIN_PROFILE == "local-2.8" and opsin_required and str(parsed) not in VERIFIER._opsin_cache:
        try:
            VERIFIER._opsin_cache[str(parsed)] = local_opsin(str(parsed))
        except Exception as error:
            VERIFIER._opsin_cache.pop(str(parsed), None)
            return {"parsed": ok, "correct": False, "parsed_value": parsed, "error": str(error)}
    got = {"is_correct": False, "opsin_smiles": None}
    timed_out = False
    for attempt in range(3):
        # Was this name cached before grading? If not, and this call consumed the full two seconds,
        # a timeout may have been cached as "OPSIN does not recognize it" (see the OPSIN network discussion above).
        fresh = opsin and ok and str(parsed) not in VERIFIER._opsin_cache
        t0 = time.monotonic()
        try:
            got = VERIFIER.check_answer(uuid, parsed)
        except Exception as e:
            if opsin_required:
                VERIFIER._opsin_cache.pop(str(parsed), None)
            return {"parsed": ok, "correct": False, "parsed_value": parsed, "error": type(e).__name__}
        if OPSIN_FAILURE:
            VERIFIER._opsin_cache.pop(str(parsed), None)
            return {"parsed": ok, "correct": False, "parsed_value": parsed, "error": OPSIN_FAILURE}
        took = time.monotonic() - t0
        timed_out = bool(
            opsin_required and not got.get("is_correct")
            and (got.get("opsin_smiles") is None or (fresh and took >= 1.9 and got.get("opsin_smiles") is False))
        )
        if not timed_out:
            break
        # Remove the timeout-contaminated cache entry and retry. **The grading rule is unchanged**; it remains the official check.
        # This separates "no response received" from "the service responded that the name is unrecognized".
        VERIFIER._opsin_cache.pop(str(parsed), None)
        print(f"[chemiq] {uuid[:8]} OPSIN timed out ({took:.1f}s), retry {attempt + 1}/2", flush=True)
    return {
        "parsed": ok,
        "correct": bool(got.get("is_correct")),
        "parsed_value": parsed,
        "opsin_smiles": got.get("opsin_smiles"),
        "timed_out": timed_out,
        "error": OPSIN_FAILURE or ("OPSINTimeout" if timed_out else None),
    }


# Grade each problem once; the `parsed` and `correct` nodes request two fields from the same grading result.
CACHE: dict[tuple[str, str], dict] = {}


def answer_of(body: dict) -> tuple[str, str]:
    """Extract the problem identity and candidate answer from the kernel payload.

    The kernel sends `{node, moment, domain, feed, input}`, where `input` is
    `{task, chain, result}` for tree execution or `{task}` for finalization.
    """
    inp = body.get("input") or {}
    task = inp.get("task") or {}
    m = UUID_RE.search(str(task.get("id", "")))
    uuid = m.group(0) if m else ""
    result = inp.get("result")
    said = result.get("body") if isinstance(result, dict) else result
    if said is None:
        said = task.get("result")
    return uuid, "" if said is None else str(said)


def verdict(uuid: str, said: str) -> dict:
    key = (uuid, said)
    if key not in CACHE:
        got = judge(uuid, said)
        if got.get("error"):
            raise RuntimeError(str(got["error"]))
        CACHE[key] = got
        q = BOOK[uuid]
        tail = said.replace("\n", " ")[-60:]
        print(
            f"[chemiq] {uuid[:8]} ({q['question_category']}/{q['sub_category']}) "
            f"parsed={got['parsed']} correct={got['correct']}"
            + (" TIMEOUT" if got.get("timed_out") else "")
            + f" | answer tail ...{tail}",
            flush=True,
        )
    return CACHE[key]


# -- note: feedback detail is controlled by --level ---------------------------


def note_of(uuid: str, got: dict) -> dict | str:
    """Additional feedback on rejection. **Level controls detail**, not the response shape. **No GT is disclosed.**

    All permitted information comes from the candidate: what was extracted and
    whether OPSIN/RDKit recognizes it.
    """
    if LEVEL <= 0:
        return ""
    q = BOOK[uuid]
    fmt = q["answer_format"]
    if got.get("error"):
        return {"stage": "verifier", "detail": got["error"]}
    if not got["parsed"]:
        return {"stage": "parse", "detail": f"no {fmt} answer could be extracted from what you handed in - hand in the {fmt} alone on one line"}
    if got.get("timed_out"):
        return {"stage": "opsin", "detail": "OPSIN did not answer in time; this measurement is unavailable"}

    note: dict = {"stage": "verify", "format": fmt}
    if LEVEL <= 1:
        return note

    # Level 2: check whether the submission itself is well formed. These checks concern the **candidate**, never GT.
    pv = got.get("parsed_value")
    if q["verification_method"] == "opsin":
        os_ = got.get("opsin_smiles")
        note["name_understood_by_opsin"] = bool(os_)
    elif q["verification_method"] == "canonical_smi_match":
        # The official canonicalization function is used only to validate candidate SMILES, not to compare it with GT.
        note["smiles_valid"] = VERIFIER._canonicalize_smiles(str(pv)) is not None
    elif q["verification_method"] == "list_of_tuples":
        note["pairs_given"] = len(pv) if isinstance(pv, (list, tuple)) else 0
    if LEVEL <= 2:
        return note

    # Level 3: show the candidate transformed through the official path (name -> SMILES; SMILES -> canonical form).
    note["parsed_as"] = str(pv)[:300]
    if q["verification_method"] == "opsin" and got.get("opsin_smiles"):
        note["your_name_means"] = got["opsin_smiles"]
    elif q["verification_method"] == "canonical_smi_match":
        note["your_smiles_canonical"] = VERIFIER._canonicalize_smiles(str(pv))
    return note


# ── HTTP ────────────────────────────────────────────────────────────────────

PUBLIC = ("uuid", "question_category", "sub_category", "answer_format", "prompt")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # The default access-log line is too noisy.
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
            try:
                metadata = opsin_metadata()
                if OPSIN_PROFILE == "local-2.8":
                    status = json.loads((OPSIN_JOBS / "status.json").read_text(encoding="utf-8"))
                    if status.get("stopped") or time.time() - status.get("heartbeat", 0) > 30:
                        raise RuntimeError("LocalOPSINBridgeUnavailable")
                self._send({"ok": True, "items": len(ORDER), "level": LEVEL, "opsin": metadata, "length_policy": LENGTH_POLICY})
            except Exception:
                self._send({"ok": False, "error": "LocalOPSINProfileUnavailable"}, 503)
            return
        if self.path.startswith("/problems"):
            # **Problem endpoint: return the statement, never the answer.** The corpus stays on this side, out of reach of the batch sender.
            # Exclude `answer`, `answer_range`, `meta_data`, and top-level `smiles`; allow only the five PUBLIC fields.
            n, cat = 0, ""
            if "?" in self.path:
                for kv in self.path.split("?", 1)[1].split("&"):
                    if kv.startswith("n="):
                        n = int(kv[2:] or 0)
                    elif kv.startswith("category="):
                        cat = kv[9:]
            ids = [u for u in ORDER if not cat or BOOK[u]["question_category"] == cat]
            if n > 0:
                ids = ids[:n]
            self._send([{k: BOOK[u].get(k) for k in PUBLIC} | {"id": f"chemiq-{u}"} for u in ids])
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
        uuid, said = answer_of(body)
        if uuid not in BOOK:
            self._send({"valid": False, "outcome": "grader_error", "error": "UnknownTask"}, 422)
            return
        if not said.strip():
            self._send({"value": False, "note": {"stage": "collect", "detail": "nothing was handed in"}})
            return
        try:
            got = verdict(uuid, said)
        except Exception as error:
            self._send({"valid": False, "outcome": "grader_error", "error": type(error).__name__}, 503)
            return
        if self.path == "/parsed":
            ok = got["parsed"]
        else:
            # **Root.** If an upstream node rejected the candidate, do not repeat its explanation; the previous node already contains it.
            feed = body.get("feed") or []
            if feed and feed[0].get("value") is not True:
                self._send({"value": False})
                return
            ok = got["correct"]
        # **Return `{value: bool}`.** G has a closed domain; any other return value is a contract violation and becomes 0.
        self._send({"value": True} if ok else {"value": False, "note": note_of(uuid, got)})


# Problem order follows the corpus file rows, which is the order of the list loaded by the verifier.
ORDER: list[str] = [q["uuid"] for q in VERIFIER.all_questions]


# -- Self-check --------------------------------------------------------------


def golden_of(uuid: str) -> str | None:
    """Construct an answer that should be accepted for this problem.

    For most problems, `answer` itself suffices: the integer, SMILES, or stringified
    mapping list is used unchanged. **OPSIN problems are different**: their `answer`
    is SMILES, while the question requests an IUPAC name. Search the official
    `opsin_cache.json` (name-to-SMILES pairs accumulated during the authors' model
    runs) for a name whose OPSIN SMILES canonicalizes to GT, and use that name.
    Return None if no match exists; the self-check skips that problem.
    """
    q = BOOK[uuid]
    if q["verification_method"] != "opsin":
        if q["verification_method"] == "list_of_tuples" and LENGTH_POLICY == "raw-input-length":
            import ast
            pairs = ast.literal_eval(q["answer"]) if isinstance(q["answer"], str) else q["answer"]
            return "[" + ",".join("(" + ",".join(str(n) for n in pair) + ")" for pair in pairs) + "]"
        return str(q["answer"])
    want = VERIFIER._canonicalize_smiles(q["answer"])
    cache = VERIFIER._opsin_cache
    if OPSIN_PROFILE == "local-2.8":
        # Selecting a cached reference name does not reuse its conversion for a
        # score; judge() will run that name through the pinned local CLI.
        cache = json.loads((VENDOR / "utils/opsin_cache.json").read_text(encoding="utf-8"))
    for name, smi in cache.items():
        if len(name) > 200 or "\n" in name or "\r" in name:
            continue
        if smi and VERIFIER._canonicalize_smiles(smi) == want:
            return name
    return None


def selftest() -> int:
    """Take the first problem in each (category, subtype). GT should be accepted and nonsense rejected. **Installation errors fail here.**"""
    seen: set[tuple[str, str]] = set()
    picked = []
    for u in ORDER:
        k = (BOOK[u]["question_category"], BOOK[u]["sub_category"])
        if k not in seen:
            seen.add(k)
            picked.append(u)
    # Add a probe for the mapping problem with the most atoms (25). **It may be unsatisfiable under the official grader**:
    # str() of the GT list has 230 characters, exceeding check_answer's 200-character limit (derived in G.md's known issues; checked here).
    # This is a probe and does not count as a success or failure. It tests whether those 30 problems (n_atoms 23-25) really are unsatisfiable under the official criteria.
    probe = max(
        (u for u in ORDER if BOOK[u]["question_category"] == "atom_mapping"),
        key=lambda u: (BOOK[u].get("meta_data") or {}).get("n_atoms", 0),
    )
    bad = skipped = 0
    for u in picked + [probe]:
        q = BOOK[u]
        gold = golden_of(u)
        tag = f"{q['question_category']}/{q['sub_category']}"
        if gold is None:
            skipped += 1
            print(f"  skip {tag:<34} no cached IUPAC name maps to the GT; cannot self-test without inventing one")
            continue
        a = judge(u, gold)
        b = judge(u, "I am not sure, sorry.")
        ok = a["correct"] and not b["correct"]
        if u == probe:
            n = (q.get("meta_data") or {}).get("n_atoms")
            print(f"  {'ok  ' if ok else 'DEAD'} {tag}/n_atoms={n} (probe) golden={a['correct']} "
                  f"len(str(GT))={len(str(a['parsed_value']))} -> "
                  + ("large mappings are gradable under " + LENGTH_POLICY if ok else "this reference is rejected under " + LENGTH_POLICY + "; retain the control gap"))
            continue
        bad += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'} {tag:<34} golden={a['correct']} junk={b['correct']}"
              + (" (OPSIN timed out)" if a.get("timed_out") else ""))
    print(f"\n{len(picked) - bad - skipped} of {len(picked)} question types grade their own ground truth as correct"
          f"{f', {skipped} skipped' if skipped else ''}")
    return 1 if bad else 0


def main() -> int:
    global LEVEL
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("TGENGIN_CHEMIQ_PORT", "7903")))
    ap.add_argument("--level", type=int, default=LEVEL, help="how much the note field says: 0..3")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--bind", default="127.0.0.1")
    a = ap.parse_args()
    LEVEL = a.level
    if a.selftest:
        return selftest()
    print(f"[chemiq] {len(ORDER)} questions | note level {LEVEL} | "
          f"http://127.0.0.1:{a.port}/{{parsed,correct}}", flush=True)
    # Single-threaded: as explained above, the official @timeout uses SIGALRM and must run on the main thread.
    HTTPServer((a.bind, a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
