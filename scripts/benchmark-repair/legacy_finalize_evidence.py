"""Assemble sanitized local repair evidence; never changes legacy run sources."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/repair-2026-10-08"


def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_record(name):
    path = OUT / name
    return {"path": str(path), "sha256": sha(path)}


def main():
    local = read("legacy-regrade-chemiq-local-opsin.json")
    finals = {(r["run"], r["task"], r["candidate_sha256"]): r for r in local["records"] if r["purpose"] == "final_submission"}
    pending = read("legacy-opsin-pending-candidates.json")
    for row in pending["records"]:
        result = finals[(row["run"], row["task"], row["candidate_sha256"])]
        row["local_variant_result"] = {"profile": local["variant"], "jar_sha256": local["jar_sha256_verified"],
            "identity": result["identity"], "regrade": result["regrade"], "source": file_record("legacy-regrade-chemiq-local-opsin.json")}
    pending["external_execution_status"] = "Not sent: automatic approval review rejected external OPSIN candidate transmission. No indirect bypass."
    pending["local_execution_status"] = "All four exact recovered final candidates were independently measured by pinned local OPSIN 2.8 plus official RDKit; old REST version remains unknown."
    pending["local_pending_count"] = 0
    pending["external_requests"] = 0
    write("legacy-opsin-pending-candidates.json", pending)
    mismatches = [r for r in local["controls"] if not r["canonical_match"]]
    assert len(mismatches) == 6
    write("legacy-local-opsin-six-control-differences.json", {"source": file_record("legacy-regrade-chemiq-local-opsin.json"),
        "summary": local["control_summary"], "records": mismatches,
        "limitation": "Five old-positive names unrecognized by local 2.8 and one old cached SMILES invalid in RDKit. These retained differences preclude old-REST equivalence certification; no raw names or reference SMILES appear here."})
    regression = read("legacy-chemiq-opsin-regression.json")
    regression.update({"after_fix_adapter_sha256": sha(ROOT / "examples/benchmark/chemiq/stand.py"),
        "test_script_sha256": sha(ROOT / "scripts/benchmark-repair/legacy_test_chemiq_opsin.py"),
        "tests_after_fix": 13, "passed_after_fix": 13, "failed_after_fix": 0, "skipped_after_fix": 0,
        "green_evidence": file_record("legacy-chemiq-opsin-regression-local-green.log"),
        "scope": "Synthetic HTTP/transport/payload faults, legitimate unrecognized-name rejection, REST prohibition, local cache ownership, and actual local HTTP503 infrastructure failure.",
        "predecessor_local_profile_selftest": {"question_types_passed": 14, "question_types": 14,
            "scope": "Actual pinned local Java conversion and official RDKit, before raw mapping policy was added; full current controls are separately recorded.",
            "log": file_record("legacy-chemiq-local-profile-selftest.log")}})
    write("legacy-chemiq-opsin-regression.json", regression)
    mapping = {"before_implementation": {"tests": 10, "failed_assertions": 34, "log": file_record("legacy-chemiq-mapping-policy-red.log")},
        "after_implementation": {"tests": 10, "failed_assertions": 0, "log": file_record("legacy-chemiq-mapping-policy-green.log")},
        "adapter_sha256": sha(ROOT / "examples/benchmark/chemiq/stand.py"),
        "test_script_sha256": sha(ROOT / "scripts/benchmark-repair/legacy_test_chemiq_mapping_policy.py"),
        "protocol": "Default official-parsed guard retained. Explicit raw-input-length revises list_of_tuples only: original delivery single line and <=200, successful official parser, official _check_list_of_tuples equality; other branches unchanged.",
        "network": "none", "external_requests": 0}
    write("legacy-chemiq-mapping-policy-regression.json", mapping)
    official = read("legacy-chemiq-616-nonopsin-controls.json")
    revised = read("legacy-chemiq-616-nonopsin-controls-raw-length.json")
    revised["reference_selection"] = "Stored official GT; range midpoint; compact raw mapping syntax; official parser and equality implementation. Explicit raw-input-length policy revises mapping guard only."
    revised["limitation"] = "The selected revised mapping protocol is explicit. It is not an official-parsed score. No task is omitted from 816 and no reference control is exposed to a solver."
    revised["description_correction"] = "Corrected the shared control-script's inherited 'guard unchanged' description; executed code SHA and measured results are preserved."
    write("legacy-chemiq-616-nonopsin-controls-raw-length.json", revised)
    iupac = read("legacy-chemiq-200-iupac-controls-raw-length.json")
    assert (revised["tasks"], revised["positive_passed"], revised["wrong_value_rejected"], revised["wrong_format_rejected"]) == (616, 616, 616, 616)
    assert (iupac["tasks"], iupac["positive_passed"], iupac["wrong_structure_rejected"], iupac["wrong_format_rejected"]) == (200, 166, 200, 200)
    dataset_path = ROOT / ".phase1-data/chemiq/vendor/ChemIQ/questions/chemiq.jsonl"
    dataset = {r["uuid"]: r for r in (json.loads(line) for line in dataset_path.read_text(encoding="utf-8").splitlines())}
    gap_records = []
    for row in iupac["records"]:
        if row["reference_found"]:
            continue
        task = dataset[row["uuid"]]
        gap_records.append({"task": row["task"], "category": task["question_category"], "sub_category": task["sub_category"],
            "missing_reason": row["missing_reason"], "metadata_keys": sorted((task.get("meta_data") or {}).keys()),
            "official_reference_smiles_sha256": hashlib.sha256(str(task["answer"]).encode()).hexdigest()})
    pool = read("legacy-local-opsin-reference-pool-private.json")
    vendor = ROOT / ".phase1-data/chemiq/vendor/ChemIQ"
    cached_constructor_paths = sorted(str(p.relative_to(vendor)) for p in vendor.rglob("*.py") if "construct" in p.name.lower() or "generat" in p.name.lower())
    healths = {}
    for port in [17917, 17918]:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as response:
            healths[str(port)] = json.load(response)
    coverage = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "benchmark_denominator": 816,
        "official_parsed_profile": {"positive_controls_passed": official["positive_passed"] + 166,
            "mapping_length_guard_gaps": 30, "iupac_reference_name_gaps": 34,
            "mapping_gap_records": [{k: row[k] for k in ["task", "category", "sub_category", "n_atoms", "positive_raw_length", "positive_parsed_length", "positive_control_gap"]} for row in official["records"] if row["positive_control_gap"]]},
        "revised_raw_input_length_profile": {"positive_controls_passed": 782, "wrong_value_or_structure_controls_rejected": 816,
            "wrong_format_controls_rejected": 816, "nonopsin_positive_controls": 616, "iupac_positive_controls": 166,
            "iupac_reference_name_gaps": 34},
        "local_reference_materials": {"primary_gap_metadata": "All 34 contain only smiles/smiles_random; no reference IUPAC name field",
            "cached_constructor_paths": cached_constructor_paths,
            "fixed_positive_cache_names_converted_by_pinned_2_8": 3111,
            "false_cache_key_supplement": pool["additional_reference_names"],
            "published_model_response_supplement": pool["published_response_reference_names"],
            "source_data_sha256": sha(dataset_path), "pinned_source": json.loads((ROOT / ".phase1-data/chemiq/source.json").read_text(encoding="utf-8"))},
        "iupac_missing_control_records": gap_records, "health": healths,
        "sources": [file_record(name) for name in ["legacy-chemiq-616-nonopsin-controls.json", "legacy-chemiq-616-nonopsin-controls-raw-length.json", "legacy-chemiq-200-iupac-controls-raw-length.json", "legacy-chemiq-mapping-policy-regression.json", "legacy-chemiq-opsin-regression.json"]],
        "external_requests": 0,
        "limits": ["34 missing positive reference names do not establish wrong answers or locally ungradable tasks; controls are unavailable until a true reference name exists.",
            "No question is removed from 816. A local OPSIN2.8 + raw-input-length run is a separately labeled revised grading protocol.",
            "No reference answer/control is provided to a solver or any external service."]}
    write("legacy-chemiq-control-coverage.json", coverage)
    print(json.dumps({"legacy_local_opsin_final_candidates": len(finals), "six_control_differences": len(mismatches),
        "revised_positive_controls": 782, "negative_controls": 816, "format_controls": 816,
        "remaining_iupac_reference_gaps": len(gap_records), "legacy_external_requests": 0}))


if __name__ == "__main__":
    main()
