"""Record confirmed F900 selection without editing the prior review or runners."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/repair-2026-10-08"


def pin(path):
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha}


def save(path, value, raw=False):
    data = value if raw else (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == data
    return pin(path)


def main(output):
    output = Path(os.path.abspath(output))
    assert output.parent == DOC and output.name.startswith("chemiq-f-formal-readiness-") and not output.exists()
    prior = DOC / "chemiq-f-formal-readiness-v1/readiness.json"
    prior_pin = pin(prior)
    assert prior_pin["sha256"] == "6ab710bc86d050dbb985f0c70ddcc349eeed82874dc578cac0b577e12f336818"
    review = json.loads(prior.read_bytes())
    scope_pin = review["formalTarget"]["scopeArtifact"]
    assert pin(Path(scope_pin["path"])) == scope_pin
    assert scope_pin["sha256"] == "8a1d219398fa36877a00a14c253601df9fd38dddc986726233b48c16319e6b12"
    inputs = review["sourceAndInputPins"] + [prior_pin, scope_pin, pin(Path(__file__))]
    assert all(pin(Path(item["path"])) == item for item in inputs)
    review["protocol"] = "chemiq-f-formal-readiness-v2-900s"
    review["createdAtUtc"] = datetime.now(timezone.utc).isoformat()
    review["derivedFrom"] = prior_pin
    review["timeSelection"] = {
        "solveSeconds": 900, "selectedByUser": True,
        "trustedInstruction": "Root relayed the user's explicit selection of900s on2026-10-09; this records preparation only, not a model launch",
        "priorAlternativesRetained": [600, 900], "priorReviewModified": False,
        "oldFDeclaredTimeComparable": True, "entireOldProtocolReproduced": False,
    }
    review["prospectiveSettings"].update({
        "selectedSolveSeconds": 900,
        "timeSelection": "User explicitly selected900s; new entry/recipe/cash guard remain pending",
    })
    review["formalTarget"]["solveSeconds"] = 900
    review["minimumRepresentativeFPilot"]["solveSeconds"] = 900
    review["minimumRepresentativeFPilot"]["queryAndTimeSettings"] = "Confirmed900s; same checks5/branches4/model/decoding/profile to be frozen for pilot and later formalF"
    review["sourceAndInputPins"] = inputs
    review["requiredBeforeRepairedFormalFullF"] = [item.replace("selected600or900s", "selected900s") for item in review["requiredBeforeRepairedFormalFullF"]]
    review["formalPaidReady"] = False
    review["executionRecipeFrozen"] = False
    assert review["formalTarget"]["denominator"] == 816 and len(review["minimumRepresentativeFPilot"]["taskRecords"]) == 16
    assert all(pin(Path(item["path"])) == item for item in inputs)
    output.mkdir()
    report_pin = save(output / "readiness.json", review)
    pilot = review["minimumRepresentativeFPilot"]["taskRecords"]
    table = "\n".join(f"| {item['officialIndex']} | {item['officialId']} | {item['category']}/{item['subCategory']} |" for item in pilot)
    scenarios = [item for item in review["feeTimeByteScenarios"]["scenarios"] if item["scenarioSolveSeconds"] == 900]
    costs = "\n".join(f"| {item['FTaskRuns']} | {float(item['cachedUsdPeakRateScenario']):.2f} | {float(item['noCacheUsdPeakRateScenario']):.2f} | {float(item['cachedCnyAllPeakTokenScenario']):.2f} | {float(item['noCacheCnyAllPeakTokenScenario']):.2f} |" for item in scenarios)
    text = f"""The user explicitly selected **900 seconds** per ChemIQ F task. The full target is **816 tasks in the original order, one F run per task, 816 runs total**; the representative 16-task pilot also uses 900 seconds. This artifact did not generate answers, grade, or start a model; `formalPaidReady=false`, and the independent execution entry point, recipe/source, and cash are not yet frozen.

| Object | Tasks and state | Time/budget | Differences |
|---|---|---|---|
| Old F0731 | 816; 680 stored passes, actually 4 claimed; scorecard reports 0 running | 900 seconds/checks3/K8/search3 | Historical source/checkpoint uncertified, finalvalidity0 |
| Old Fc5kinf0929 | 816; 633 stored passes, actually 6 claimed; all 303 searches returned 402 | 900 seconds/checks5/K100000/search3 | Not new formal results |
| Live 10-task F pilot | 10, with 3 passes; NMR/zinc_2d only | 180 seconds/checks5/branch4/no search | Original shutdown timeout and laterclosing both retained; not representative of 816 |
| New F target | All original 816 IDs retained; not executed | **900 seconds**/checks5/branch4/K100000/no search | New deepseek-flash, 8192/temp0/seed42/reasoningnone; not a reproduction of the old 0731 checkpoint |

The same task scope is in the original [task-scope.json](../chemiq-f-formal-readiness-v1/task-scope.json), 209,338 bytes, SHA `{scope_pin['sha256']}`. The original pending-selection version and all input SHAs have not been overwritten; every current byte sequence was verified unchanged again. The scope contains only ID/prompt digests, no reference answers. Matching the old F duration at 900 seconds does not certify equivalence of models, search, budgets, grading, or the old run as a whole.

Revised grading uses pinned local OPSIN2.8.0 + raw-input-length, REST fallback=false, level0. Applying the 200-character atom-mapping limit to raw input fixes 30 false rejections. The official parser/RDKit equivalence check retains its original source. Existing same-source positive controls cover 782/816, with 816 incorrect-value/structure and 816 format negative controls; 34 IUPAC positive references are still missing, 17 random and 17 canonical. All 34 exact IDs are in JSON; they must not be removed from the denominator, counted as incorrect answers, or described as fully repaired. First supply private correct names and verify them; a small pilot cannot replace this step. This protocol differs from old results using an unknown REST service or official parsed-length grading.

The minimum representative pilot is fixed at **16F900**: the first task in original order for each of 14 category/subcategory/grading-rule combinations, plus two 25-atom mapping boundary cases. It covers 8 categories, 14 subcategories/grading rules, and 5 grading methods; all 16 have positive controls, and selection did not use model results. This does not certify the 34 tasks missing references; after positive references are supplied, the two tasks prespecified in JSON can provide additional diagnostics. Whether the pilot belongs to a prespecified formal subset must be decided before generation; changed protocols or selected successful samples must not be spliced together.

| Original task index (0-based) | Pinned taskID | Category/subcategory |
|---|---|---|
{table}

Costs use actual tokens from the original 10 NMR F180 tasks only, scaled by 900/180 as a stress scenario:

| F runs | Cached USD peak-rate estimate | Uncached USD peak-rate estimate | Independent all-peak CNY estimate | Independent uncached all-peak CNY estimate |
|---|---|---|---|---|
{costs}

These numbers are not invoices, currency conversions, hard billing upper bounds, or current balances; NMR is not a representative cost sample. The user's intent to top up does not mean funds have arrived. Root must retrieve the actual balance/TTL near startup, freeze an independent cash envelope, and retain the original 4 unknown costs totaling CNY 8.39218. Before each provider forward, persist raw data, admission, and a cash reservation; complete usage/late receipts, unknown costs, and shared ownerwx must not be bypassed.

checks5 limits explicit checks; physical G calls for automatic runtime grading and independent final grading must be counted separately. Do not claim that all G calls total only 5, or a causal effect under equal U/F budgets. The existing frozen scientific plan still produces U/F, and its 16-task calibration selection differs, so an independent F-only entry point/review is required without changing the original 81 sources. Full-JSON hot rewrites cannot scale directly to 816; the current cash full-history counting and limits of 128MiB per pin / 256MiB cash metadata also need scope assessment based on actual new pilot volumes.

Startup also requires fresh private grader/source/runtime/JAR/queue/positive and negative controls, RAM and disk gates, sealed candidate digests, original trace/wire/token/cost records, explicit time-limit and grading groups, and cleanup under exact ownership. Historical environment observations and 16-task coverage cannot replace evidence from a new run. Every invalid result remains invalid, and partial results must not be labeled complete 816-task results. The paper, old data, original packages, and frozen execution sources were not modified.

Complete [readiness.json](readiness.json): {report_pin['bytes']} bytes, SHA `{report_pin['sha256']}`.
"""
    markdown_pin = save(output / "readiness.md", text.encode(), raw=True)
    print(json.dumps({"report": report_pin, "markdown": markdown_pin, "scope": scope_pin,
                      "source": pin(Path(__file__)), "selectedSolveSeconds": 900,
                      "formalPaidReady": False, "modelCalls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    main(parser.parse_args().output_dir)
