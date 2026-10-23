"""LAB-Bench public ProtocolQA pilot using the pinned official prompt construction.

Text-only pilot, seed 0; image categories require a vision configuration before full readiness.
The official metric compares the delivered single letter exactly and tracks abstention.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import random
import sys
import types

HOME = Path(os.environ.get("TGENGIN_LAB_HOME", "/oracle"))
VENDOR = HOME / "vendor/LAB-Bench"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_lib"))
from gradelib import serve

# Grading does not instantiate any provider agents from labbench.__init__.
pkg = types.ModuleType("labbench")
pkg.__path__ = [str(VENDOR / "labbench")]
sys.modules["labbench"] = pkg
from labbench import utils
for name in ["BaseEvalInstance", "AgentInput", "get_data_sources"]:
    setattr(pkg, name, getattr(utils, name))
spec = importlib.util.spec_from_file_location("protocolqa", VENDOR / "ProtocolQA/task.py")
task = importlib.util.module_from_spec(spec)
spec.loader.exec_module(task)
random.seed(0)
BOOK = {}
for raw in (VENDOR / "ProtocolQA/protocolqa-v1-public.jsonl").read_text(encoding="utf-8").splitlines():
    item = task.EvalInstance(**json.loads(raw))
    public, expected, unsure = item.get_input_output()
    tid = "lab-bench-" + str(item.id)
    BOOK[tid] = {"id": tid, "prompt": public.question + "\n\n" + "\n".join(public.choices) + "\nSubmit exactly one uppercase letter for your selected option, including the uncertainty option when appropriate.", "target": expected, "unsure": unsure, "choices": len(public.choices)}

def parsed(text, item):
    return len(text) == 1 and text in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[:item["choices"]]

def correct(text, item):
    return text == item["target"]

NODES = {"parsed": parsed, "correct": correct}
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=17925)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        records = []
        for item in BOOK.values():
            wrong = next(x for x in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[:item["choices"]] if x != item["target"])
            ok = parsed(item["target"], item) and correct(item["target"], item) and not correct(wrong, item) and not parsed("No answer", item)
            records.append({"id": item["id"], "passed": ok, "refusalIsCorrect": correct(item["unsure"], item)})
        print(json.dumps({"benchmark": "LAB-Bench", "subset": "public ProtocolQA", "seed": 0, "allPassed": all(r["passed"] for r in records), "tasks": len(BOOK), "records": records}))
        raise SystemExit(0 if all(r["passed"] for r in records) else 1)
    serve(BOOK, lambda item: {k: item[k] for k in ["id", "prompt"]}, NODES, args.port, "lab-bench")
