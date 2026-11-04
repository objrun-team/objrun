"""Freeze the already executed F-only controls and the two-key source contract."""
import hashlib
import json
import os
from pathlib import Path
import re

PROJECT = Path(__file__).resolve().parents[2]
DOC = PROJECT/"docs/repair-2026-10-08"
CONTROL = DOC/"minif2f-public-cache-root-carry-controls"


def pin(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


old_path = DOC/"minif2f-public-cache-v3-review.json"
if pin(old_path)["sha256"] != "21ce70fcd2c9665f00981b9c2b2aa47a950a5130f02b866484e1f2ba41672815":
    raise RuntimeError("Frozen V3 review changed")
old = json.loads(old_path.read_bytes())
new_paths = [PROJECT/"scripts/benchmark-repair/minif2f_public_cache_root_carry.py",
             PROJECT/"scripts/benchmark-repair/minif2f_public_cache_root_carry.ps1",
             PROJECT/"test/benchmarks/minif2f_public_cache_root_carry_test.py",
             DOC/"minif2f-public-cache-root-carry-authorization.json"]
new_sources = [pin(path) for path in new_paths]
protected = {}
for expected in old["new_sources"] + old["protected_sources"]:
    actual = pin(expected["path"])
    if actual["sha256"] != expected["sha256"] or actual["bytes"] != expected["bytes"]:
        raise RuntimeError("Original protected source changed: "+actual["path"])
    protected[str(Path(actual["path"]).resolve()).casefold()] = actual
extra = [old_path, DOC/"minif2f-v3-root-carry-archive-binding.json",
         DOC/"minif2f-v3-closed-eof-diagnosis.json", DOC/"minif2f-v3-root-carry-design.json"]
directory = DOC/"minif2f-dependency-failures/public-cache-body-v3-first-attempt-verified-v2"
root_receipt = json.loads((directory/"failure-record.json").read_bytes())
extra += [directory/"failure-record.json"] + [Path(x["archive"]) for x in root_receipt["parts"]+root_receipt["copiedInputs"]]
extra += [CONTROL/"run-1.stdout.txt", CONTROL/"run-1.stderr.txt"]
for path in extra:
    actual = pin(path)
    protected[str(path.resolve()).casefold()] = actual
for actual in new_sources:
    protected.pop(str(Path(actual["path"]).resolve()).casefold(), None)
log = (CONTROL/"run-1.stderr.txt").read_text(encoding="utf-8")
if len(re.findall(r"\.\.\. ok", log)) != 18 or "Ran 18 tests" not in log or not log.rstrip().endswith("OK"):
    raise RuntimeError("Actual18-control log is not a passing exit")
review = dict(protocol="public-cache-root-carry-source-review-v1", validated=True,
              transport_protocol="same-key-root-reviewed-complete-carry-v1",
              authorization_sha256="754e410406ed2d310976435d70774a35bf6f85d462f4f492e1c2ffd84a480771",
              base_helper_sha256="a02c3519b0ccba8a74e577991fedcf75f0c05fb181cfeb617b7e51b060384c2b",
              imported_v3_sha256="23e760d9236037e8c5d14ef686b00fcbe9659d34cf28d7c03624a7775573af83",
              profile_sha256="f23ebc252a02cf9a407db4fb2045f6c8dba064e1706e97d28fc6ff96ac2a5fd3",
              real_acquisition_executed=False, real_gate_executed=False,
              root_must_independently_review_and_launch=True, new_sources=new_sources,
              protected_sources=list(protected.values()),
              controls=dict(passed=18, failed=0, scope="F-only synthetic stream and real fsync/share-deny",
                            successful_payloads_are_synthetic=True, official_blob_complete_body_unverified=True,
                            python_ast_passed=True, powershell_ast_errors=0, network_calls=0, e_writes=0,
                            model_calls=0, docker_calls=0, candidate_or_lean_runs=0,
                            stderr_pin=pin(CONTROL/"run-1.stderr.txt")),
              limits=dict(maximum_new_opener_calls=2, original_gets=1505, maximum_final_objects=3556,
                          may_emit5826_certificate=False, remaining2270_not_authorized=True,
                          deadline_utc="2026-10-08T18:16:26.118992+00:00", maximum_body_bytes=64*1024**2,
                          carried_preservation_operations=6, maximum_with_failed_new_bodies=8,
                          carried_failed_prefix_bytes=292278, prefix_cap_bytes=256*1024**2,
                          directory_cap_bytes=14*1024**3, minimum_e_free_bytes=3*1024**3,
                          minimum_f_free_bytes=1024**3, receipt_row_maximum_bytes=2048),
              legacy_compatibility="Original3554 raw rows and original V2/V3 first-generation journal are immutable. Distinct new carry rows and generation3 have their own strict validator; never masquerade as V3.",
              failure_rule="An intent is consumed even if ambiguous or its fsync fails; one opener only, no reopening/retry/bulk key. Unclosed or unknown artifacts require root preservation and explicit review.")
out = DOC/"minif2f-public-cache-root-carry-review.json"
with out.open("xb") as stream:
    stream.write((json.dumps(review, ensure_ascii=False, indent=2)+"\n").encode())
    stream.flush()
    os.fsync(stream.fileno())
print(json.dumps(pin(out)))
