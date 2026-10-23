"""ChemIQ 的判卷台 —— 引擎外面的一个 HTTP 服务。

    python3 stand.py [--port 7903] [--level 1] [--selftest]

引擎那边它就是两条句柄：

    http://127.0.0.1:7903/parsed     官方 AnswerParser 从回答里抠得出一个答案吗
    http://127.0.0.1:7903/correct    官方 AnswerVerifier 说对吗（根）

句柄名本身就是地址，内核 POST 一份 JSON 过来，这儿回一份 JSON —— 没有别的协议。

## 默认使用官方判据；修订协议显式选用

`vendor/ChemIQ/utils/parser.py` + `utils/answer_verifier.py` 是官方判卷代码
（oxpig/ChemIQ，钉在 63826f6）。默认按官方 `analysis.ipynb` 的
parse → check_answer 调过去；本文件提供 HTTP、故障隔离、缓存与显式评分协议。

五种判法全在官方 `check_answer` 里按每题的 `verification_method` 分派：
exact_match（整数）、range（带噪 SAR）、list_of_tuples（原子映射）、
canonical_smi_match（RDKit 去立体后规范化比较）、opsin（IUPAC 名 → OPSIN 网络服务
→ SMILES → 再走 RDKit 比较）。**没有 LLM 判卷那一部分**，全是确定性的。

## 两件「机器怎么装」的事，落在这个文件里

1. **单线程 HTTP。** 官方 `check_answer` 上有个 `@timeout(2)`，用的是 `signal.alarm`，
   只能在主线程装 —— 放进 ThreadingHTTPServer 的工作线程里第一条请求就
   `ValueError: signal only works in main thread`。所以用 `HTTPServer`，一次判一道。
   一道题判一次不到两秒，够用。
2. **chdir 到 vendor 根。** 官方 verifier 用相对路径 `utils/opsin_cache.json` 读写
   OPSIN 缓存；不切目录它会在当前目录下另建一个空的 `utils/`，缓存全丢。

## OPSIN 的显式评分 profile

默认 `TGENGIN_CHEMIQ_OPSIN_PROFILE=rest` 保留官方 REST 路径。连接/HTTP/JSON
故障和超时记为评分不可用，并撤掉故障写入的负缓存；服务明确不识别名称才判错。
`local-2.8` 使用宿主的固定官方 OPSIN 2.8.0 JAR，通过本机文件队列传入 SMILES，
仍由官方 RDKit 分支判等。它不复用旧 REST 正缓存，也绝不回退到 REST；/health
记录版本、JAR 摘要和 cache 来源。这是独立的本地评分变体，不能宣称与旧 REST 等价。

`TGENGIN_CHEMIQ_LENGTH_POLICY=official-parsed` 是默认长度协议，保留官方
`len(str(parsed)) <= 200`。可显式选 `raw-input-length`：仅对原子映射题要求
原始交付单行、长度不超过 200，随后用官方 parser 和 `_check_list_of_tuples`
判等。它修正紧凑映射被解析器加空格后超过 200 的问题，不修改其他题的评分。
/health 记录 length_policy；两个协议的成绩必须分开报告。

### REST profile 的故障处理

官方 REST 分支的 `@timeout(2)` 会把连接故障写成 False 缓存，或返回
`{"is_correct": False, "opsin_smiles": None}`。这里分别记录传输/HTTP/JSON故障，
撤掉污染缓存，返回 HTTP 503 的评分不可用；只有明确不识别名称才是有效拒绝。
本地 profile 在调用 requests 前阻止 REST 路径，转换先在本机完成，再进官方
RDKit 比较。旧 REST 版本未知，不声明它和本地版本等价。

## 答案不进求解那一侧

题库 `questions/chemiq.jsonl` 每一行都带 `answer`（还有 `meta_data`、顶层 `smiles`），
**只有这个进程读它**。`/problems` 发题时只给 uuid / 类别 / 题面 / 答案格式，别的一个
字段都不过去。G 封存在引擎另一个库里，主库全接口开放也翻不出来。

**但这不是隔离。** solver 的 bash 跟判卷台在同一台机器上的话，
`cat ~/.cache/tgengin-chemiq/vendor/ChemIQ/questions/chemiq.jsonl` 就是整本答案；
在 Sherlock 上更简单，`git clone oxpig/ChemIQ` 一样拿到。装到家目录改的是路径，不是可达性。
真堵死得把 solver 关进没网的沙箱，那是 `place` 那一维的事（见 deepswe）。
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

# **题库和判据不在仓库里，在判卷台这一侧。** solver 手上有 read / glob，仓库里放的话
# 一个 glob 就找到。setup.sh 把官方仓库 vendored 到这儿。
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

# 题号形状：`chemiq-<uuid>`，也认 `<跑名>/chemiq-<uuid>`。从整串里抠 uuid 就够了。
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def load_official():
    """把官方两个类加载进来。**先 chdir 到 vendor 根** —— 见文件头第 2 条。"""
    if not (VENDOR / "utils" / "answer_verifier.py").exists() or not QUESTIONS.exists():
        raise SystemExit(f"the official grading code is missing: {VENDOR} (run setup.sh first)")
    sys.path.insert(0, str(VENDOR))
    from utils.answer_verifier import AnswerVerifier  # noqa: E402
    from utils.parser import AnswerParser  # noqa: E402

    # 官方 analysis.ipynb 就是这两行：doClean=True 的 parser + 同一份题库的 verifier。
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
# 题库就是 verifier 已经读进去的那份 —— 不另读一遍，两份会漂。
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
    """跑一遍官方判据。回 `{parsed, correct, ...排障用的几栏}`。

    照官方 `analysis.ipynb`：`parsed = parser.parse(uuid, raw)`，
    `check_answer(uuid, parsed)`。parse 失败官方回 False，check_answer 对 False 直接判错 ——
    我们照样把 False 递过去，不替它短路。
    """
    global OPSIN_FAILURE
    OPSIN_FAILURE = None
    q = BOOK[uuid]
    opsin = q["verification_method"] == "opsin"
    parsed = PARSER.parse(uuid, said)
    # 官方用 `False` 当「没抠出来」；`is False` 而不是 `== False`，因为整数 0 也 == False。
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
        # 这个名字判之前在不在缓存里 —— 不在、而这一趟又跑满了两秒，就是超时被当成
        # 「OPSIN 不认」写进了缓存（见文件头「OPSIN 那 200 道要网」）。
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
        # 把那条被超时污染的缓存撤掉再问。**这不改判断**，判断还是官方那一句；撤的是它
        # 自己没来得及区分的「没问到」和「问了说不认」。
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


# 一道题判一次就够 —— `parsed` 和 `correct` 两个节点问的是同一次判卷的两栏。
CACHE: dict[tuple[str, str], dict] = {}


def answer_of(body: dict) -> tuple[str, str]:
    """从内核送来的那份东西里挖出「哪道题」和「它答了什么」。

    内核送的是 `{node, moment, domain, feed, input}`，`input` 是
    `{task, chain, result}`（树那条路）或 `{task}`（收尾那一路）。
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


# ── note：这一栏说多少，按 --level ──────────────────────────────────────────


def note_of(uuid: str, got: dict) -> dict | str:
    """判 0 的时候多说的那一份。**级别定详略**，形状不随级别变。**GT 一个字不出。**

    能说的全来自候选自己那一侧：抠出来了什么、OPSIN/RDKit 认不认它。
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

    # 级别 2：它交的东西本身站不站得住。这些判断是对**候选**做的，不碰 GT。
    pv = got.get("parsed_value")
    if q["verification_method"] == "opsin":
        os_ = got.get("opsin_smiles")
        note["name_understood_by_opsin"] = bool(os_)
    elif q["verification_method"] == "canonical_smi_match":
        # 官方自己的规范化函数 —— 只用来看候选 SMILES 是否合法，不比对。
        note["smiles_valid"] = VERIFIER._canonicalize_smiles(str(pv)) is not None
    elif q["verification_method"] == "list_of_tuples":
        note["pairs_given"] = len(pv) if isinstance(pv, (list, tuple)) else 0
    if LEVEL <= 2:
        return note

    # 级别 3：把它交的东西按官方那条路翻译回去给它看（名字 → SMILES；SMILES → 规范形）。
    note["parsed_as"] = str(pv)[:300]
    if q["verification_method"] == "opsin" and got.get("opsin_smiles"):
        note["your_name_means"] = got["opsin_smiles"]
    elif q["verification_method"] == "canonical_smi_match":
        note["your_smiles_canonical"] = VERIFIER._canonicalize_smiles(str(pv))
    return note


# ── HTTP ────────────────────────────────────────────────────────────────────

PUBLIC = ("uuid", "question_category", "sub_category", "answer_format", "prompt")


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
            # **发题的口：给题面，不给答案。** 题库在这一侧，发批那个脚本读不到。
            # `answer` / `answer_range` / `meta_data` / 顶层 `smiles` 全都不过去 —— 只放行 PUBLIC 那五栏。
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
            # **根。** 上游判 0 的话不必再说一遍 —— 那句话已经在上一格里了。
            feed = body.get("feed") or []
            if feed and feed[0].get("value") is not True:
                self._send({"value": False})
                return
            ok = got["correct"]
        # **回 `{value: bool}`。** G 的值域是封闭的，回别的东西内核当违约，一律归 0。
        self._send({"value": True} if ok else {"value": False, "note": note_of(uuid, got)})


# 发题顺序：题库文件的行序（verifier 读进来的 list 就是那个序）。
ORDER: list[str] = [q["uuid"] for q in VERIFIER.all_questions]


# ── 自检 ────────────────────────────────────────────────────────────────────


def golden_of(uuid: str) -> str | None:
    """这道题「该判 1」的一份回答。

    绝大多数题 `answer` 本身就是：整数原样、SMILES 原样、映射列表的字符串。
    **opsin 题不行** —— 它的 `answer` 是 SMILES，而题目要的是 IUPAC 名。所以从官方
    `opsin_cache.json`（作者跑模型时攒下的名字→SMILES）里找一个名字，OPSIN 给它的
    SMILES 规范化后等于 GT 的，拿那个名字当回答。找不到就回 None，自检跳过这道。
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
    """每个 (类别, 子类) 取第一道，拿 GT 喂回去，官方判据该说 1；一句废话该说 0。**装错了在这儿就炸。**"""
    seen: set[tuple[str, str]] = set()
    picked = []
    for u in ORDER:
        k = (BOOK[u]["question_category"], BOOK[u]["sub_category"])
        if k not in seen:
            seen.add(k)
            picked.append(u)
    # 多加一道：原子最多（25 个）的映射题。**疑似官方判据下无解**：GT 列表 str() 出来
    # 230 字符，超过 check_answer 那条 200 字符的门槛（G.md「已知坑」，算术推的，这儿验）。
    # 它是探针，不计入成败 —— 结果只是告诉我们那 30 道（n_atoms 23–25）在官方判据下是不是真没解。
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
    # 单线程，理由见文件头：官方 @timeout 用 SIGALRM，只能在主线程。
    HTTPServer((a.bind, a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
