"""Pinned AtmosSci-Bench MCQ10 adapter; open-ended grading is a separate protocol."""
import argparse
import json
import os
from pathlib import Path
import sys
import types

HOME = Path(os.environ.get("TGENGIN_ATMOS_HOME", "/oracle"))
VENDOR = HOME / "vendor/AtmosSci-Bench"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_lib"))
from gradelib import serve
pkg = types.ModuleType("official_evaluators")
pkg.__path__ = [str(VENDOR / "src/evaluate/evaluators")]
sys.modules["official_evaluators"] = pkg
from official_evaluators.mcq_evaluator import MCQEvaluator
judge = MCQEvaluator()
BOOK = {}
for raw in (VENDOR / "data/jsonl/main_1-10.jsonl").read_text(encoding="utf-8").splitlines():
    row = json.loads(raw)
    tid = "atmossci-" + row["id"]
    prompt = row["problem"] + "\n\n" + "\n".join(f"{chr(65+i)}. {option}" for i, option in enumerate(row["options"]))
    BOOK[tid] = {"id": tid, "prompt": prompt + "\nEnd with \\boxed{A}, \\boxed{B}, \\boxed{C}, or \\boxed{D} and submit that answer.", "target": row["correct_option"], "subject": row["type"]}

def parsed(text, item):
    letter = text if len(text) == 1 else judge.extract_mcq_answer(text)
    return letter in "ABCD" if letter else False

def correct(text, item):
    return bool(judge.evaluate(item["target"], text)["is_correct"])

NODES = {"parsed": parsed, "correct": correct}
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=17924)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        records = []
        for item in BOOK.values():
            right = "\\boxed{" + item["target"] + "}"
            wrong = "\\boxed{" + next(x for x in "ABCD" if x != item["target"]) + "}"
            ok = parsed(right, item) and correct(right, item) and not correct(wrong, item) and not parsed("No answer", item)
            records.append({"id": item["id"], "passed": ok})
        print(json.dumps({"benchmark": "AtmosSci-Bench", "subset": "MCQ10", "allPassed": all(r["passed"] for r in records), "tasks": len(BOOK), "records": records}))
        raise SystemExit(0 if all(r["passed"] for r in records) else 1)
    serve(BOOK, lambda item: {k: item[k] for k in ["id", "prompt", "subject"]}, NODES, args.port, "atmossci-bench")
