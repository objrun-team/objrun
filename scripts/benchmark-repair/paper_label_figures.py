"""Re-render the two active AIME figures with corrected years, preserving old inputs."""
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "latex/reports/monkeys-2026-09-29"
OUT = ROOT / "latex/full-v4/repair-figures"
INPUTS = ROOT / "docs/repair-2026-10-08/paper-figure-inputs"
OUT.mkdir(parents=True, exist_ok=True)
INPUTS.mkdir(parents=True, exist_ok=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


files = ["05-reachability-nine.csv", "05-reachability-nine-nulls.csv", "05-reachability-nine.json",
         "hero-3-scale-and-compute.csv", "hero-3-scale-and-compute-tasks.csv", "hero-3-scale-and-compute.json"]
originals = {name: sha(REPORT / "data" / name) for name in files}
for name in files:
    shutil.copyfile(REPORT / "data" / name, INPUTS / name)
sys.path.insert(0, str(REPORT / "common"))
import pub

pub.DATA, pub.FIGS = str(INPUTS), str(OUT)
pub.BENCH9_NAME["aime"] = "AIME 2024–25"
execution = []
for slug in ["05-reachability-nine", "hero-3-scale-and-compute"]:
    script = REPORT / "scripts" / f"{slug}.py"
    text = script.read_text(encoding="utf-8")
    corrected = text.replace("AIME 2024–26", "AIME 2024–25").replace("AIME 2024--26", "AIME 2024--25").replace("AIME 2024-26", "AIME 2024-25")
    saved = INPUTS / f"{slug}-executed.py"
    saved.write_text(corrected, encoding="utf-8")
    exec(compile(corrected, str(script), "exec"), {"__file__": str(script), "__name__": "__main__"})
    execution.append({"slug": slug, "originalScriptSha256": sha(script), "executedScriptSha256": sha(saved),
                      "pdfSha256": sha(OUT / f"{slug}.pdf"), "pngSha256": sha(OUT / f"{slug}.png")})
assert originals == {name: sha(REPORT / "data" / name) for name in files}, "Historical plotting inputs changed"
evidence = {"scope": "Years only; historical numerical inputs retained, no repaired scores inserted",
            "historicalInputsUnchanged": True, "inputs": originals, "execution": execution,
            "styleModuleSha256": sha(REPORT / "common/pub.py")}
(ROOT / "docs/repair-2026-10-08/paper-label-figures.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"historicalInputsUnchanged": True, "figures": len(execution), "output": str(OUT)}))
