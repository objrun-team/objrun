"""判卷台的公共骨架。每个榜的 grader.py 只写三样：题库怎么读、题面怎么发、每个节点怎么判。

    from gradelib import serve
    serve(book=BOOK, view=view, nodes={"parsed": judge_parsed, "correct": judge_correct}, port=7911)

- `book`: {id: item}，item 里可以带答案 —— 答案只活在这个进程里
- `view(item)`: 发给引擎那侧的题面（**不许带答案**），至少 {"id", "prompt"}
- `nodes`: 节点名 -> fn(answer_text, item) -> bool。一次交卷所有节点一起算、缓存住，
  引擎按节点分别来问时回同一次判卷的那一栏
- POST /<node>  body {"input":{"task":{"id":..,"result":..}}}  -> 裸 bool
- GET /health, GET /problems?n=N&only=a,b
"""
from __future__ import annotations

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

_BOXED = re.compile(r"\\boxed\{((?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL)


def last_boxed(text: str) -> str | None:
    """最后一个 \\boxed{...} 的内容；没有就 None。"""
    if not text:
        return None
    m = _BOXED.findall(text)
    return m[-1].strip() if m else None


def last_line(text: str) -> str:
    lines = [l.strip() for l in (text or "").strip().splitlines() if l.strip()]
    return lines[-1] if lines else ""


def serve(book: dict, view: Callable, nodes: dict[str, Callable], port: int, tag: str = "bench") -> None:
    cache: dict[tuple[str, str], dict[str, bool]] = {}

    class GraderFault(Exception):
        def __init__(self, kind: str, status: int = 503):
            self.kind, self.status = kind, status

    def verdict(body: dict) -> dict[str, bool]:
        inp = body.get("input") or {}
        task = inp.get("task") or {}
        tid = str(task.get("id", ""))
        if tid not in book:
            matches = [key for key in book if tid.endswith("/" + key)]
            if len(matches) == 1:
                tid = matches[0]
        result = inp.get("result")
        said = result.get("body") if isinstance(result, dict) else result
        if said is None:
            said = task.get("result")
        if said is None:
            said = ""
        if not isinstance(said, str):
            raise GraderFault("InvalidCandidateType", 422)
        item = book.get(tid)
        if item is None:
            print(f"[{tag}] {tid} not in book", flush=True)
            raise GraderFault("UnknownTask", 422)
        key = (tid, said)
        if key not in cache:
            out = {}
            for name, fn in nodes.items():
                try:
                    value = fn(said, item)
                    if not isinstance(value, bool):
                        raise TypeError("grader returned a non-boolean value")
                    out[name] = value
                except Exception as e:
                    print(f"[{tag}] {tid} {name} raised {type(e).__name__}", flush=True)
                    raise GraderFault(type(e).__name__) from e
            cache[key] = out
            tail = (said or "").replace("\n", " ")[-70:]
            print(f"[{tag}] {tid} " + " ".join(f"{k}={int(v)}" for k, v in out.items()) + f" | ...{tail}", flush=True)
        return cache[key]

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
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
                self._send({"ok": True, "items": len(book), "nodes": list(nodes)})
            elif self.path.startswith("/problems"):
                n, only = 0, None
                if "?" in self.path:
                    for kv in self.path.split("?", 1)[1].split("&"):
                        if kv.startswith("n="):
                            n = int(kv[2:] or 0)
                        elif kv.startswith("only="):
                            only = set(kv[5:].split(","))
                ids = list(book)
                if only:
                    ids = [i for i in ids if i in only]
                if n > 0:
                    ids = ids[:n]
                self._send([view(book[i]) for i in ids])
            else:
                self._send({"error": "404"}, 404)

        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                self._send({"valid": False, "outcome": "grader_error", "error": "InvalidJSON"}, 400)
                return
            name = self.path.strip("/")
            if name not in nodes:
                self._send({"error": "404"}, 404)
                return
            try:
                self._send(verdict(body)[name])
            except GraderFault as e:
                self._send({"valid": False, "outcome": "grader_error", "error": e.kind}, e.status)

    print(f"[{tag}] grader up: http://0.0.0.0:{port}/{{{','.join(nodes)}}} | {len(book)} problems", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()


def selftest(book: dict, nodes: dict[str, Callable], gt: Callable, n: int = 5) -> bool:
    """拿题库自己的答案当回答喂进去，每个节点都该是 True。"""
    bad = 0
    for i, tid in enumerate(list(book)[:n]):
        item = book[tid]
        res = {name: bool(fn(gt(item), item)) for name, fn in nodes.items()}
        ok = all(res.values())
        bad += 0 if ok else 1
        print(f"  {'√' if ok else '×'} {tid} " + " ".join(f"{k}={int(v)}" for k, v in res.items()))
    print(f"  ground truth fed back: {n - bad} of {n} pass all nodes")
    return bad == 0
