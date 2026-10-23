"""Full planned-set positive/negative/format controls, run without network or LLM."""
import hashlib
import json
import math
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
slug = sys.argv[1]
os.environ[{"cmt": "TGENGIN_CMT_HOME", "chembench": "TGENGIN_CHB_HOME"}[slug]] = f"/oracle/{slug}"
path = ROOT / f"examples/benchmark/{slug}/{'grader.py' if slug == 'cmt' else 'stand.py'}"
namespace = runpy.run_path(str(path), run_name="repair_control_module")
book, judge = namespace["BOOK"], namespace["judge"]
checks = []
if slug == "cmt":
    for idx in sorted(book):
        item = book[idx]
        good = judge(item["solution"], item)
        wrong = judge(r"\boxed{999999999}", item)
        junk = judge("I cannot provide an answer", item)
        checks.append({"id": f"cmt-{idx}", "class": item["type"], "positiveParsed": good[0], "positiveAccepted": good[1],
            "negativeRejected": not wrong[1], "formatRejected": not junk[0],
            "allPassed": bool(good[0] and good[1] and not wrong[1] and not junk[0])})
else:
    for tid in namespace["pick"](500, 0):
        item = book[tid]
        good = judge(namespace["golden_of"](item), item)
        if namespace["is_mcq"](item):
            _, scores = namespace["prompt_of"](item)
            zeros = [key for key, value in scores.items() if value != 1]
            # When every option is correct, a strict subset is a wrong valid delivery.
            wrong_text = "[ANSWER]" + (zeros[0] if zeros else list(scores)[0] if len(scores) > 1 else "Z") + "[/ANSWER]"
        else:
            target = float(item["example"]["target"])
            wrong_text = f"[ANSWER]{target + max(1.0, abs(target) * 1000)}[/ANSWER]"
        wrong = judge(wrong_text, item)
        junk = judge("I am not sure about this.", item)
        checks.append({"id": tid, "class": "mcq" if good["mcq"] else "numeric", "positiveParsed": good["parsed"],
            "positiveAccepted": good["correct"], "negativeRejected": not wrong["correct"], "formatRejected": not junk["parsed"],
            "allPassed": bool(good["parsed"] and good["correct"] and not wrong["correct"] and not junk["parsed"])})
result = {"benchmark": slug, "tasks": len(checks), "allPassed": all(c["allPassed"] for c in checks),
    "failedTaskIds": [c["id"] for c in checks if not c["allPassed"]], "checks": checks,
    "graderFileSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    "taskIdDigest": hashlib.sha256(json.dumps([c["id"] for c in checks], separators=(",", ":")).encode()).hexdigest(),
    "scope": "Reference answer acceptance, deliberately wrong answer rejection, and missing-format rejection across the full planned set; no solver or LLM request."}
output = ROOT / f"docs/repair-2026-10-08/{slug}-full-controls.json"
output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"benchmark": slug, "tasks": len(checks), "allPassed": result["allPassed"], "failedTaskIds": result["failedTaskIds"]}))
raise SystemExit(0 if result["allPassed"] else 1)
