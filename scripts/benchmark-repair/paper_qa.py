"""Verify the current multi-file paper artifact without changing historical inputs."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "latex/full-v4"
pdf = PAPER / "main.pdf"
tool = shutil.which("pdftotext")
if not tool:
    raise RuntimeError("pdftotext is unavailable; preserve the PDF and do not certify text checks")
text = subprocess.check_output([tool, "-layout", str(pdf), "-"], encoding="utf-8")
normalized = re.sub(r"\s+", " ", text)
log = (PAPER / "main.log").read_text(encoding="utf-8", errors="replace")
counts = {label: text.count(label) for label in ["2024–26", "2024--26", "2024-26"]}
checks = {
    "auditNotice": "Experimental audit, 8 October 2026" in normalized
        and "not certified results of the repaired runtime" in normalized,
    "withdrawnHeadlinesAbsent": "94.4" not in text and "85.1" not in text,
    "aimeWrongLabelsAbsent": not any(counts.values()),
    "deepSWEStoredCountsNote": "91 stored acceptances" in normalized and "112 exported records" in normalized,
    "deepSWEDateCaveat": "54 early and 58 later" in normalized and "go-genai" in normalized,
    "compilerSucceeded": "Output written on main.pdf" in log and "Fatal error" not in log,
    "crossReferenceRerunNeeded": "Rerun to get cross-references right" in log,
}
result = {
    "checkedAt": datetime.now(timezone.utc).isoformat(),
    "pdf": str(pdf),
    "pages": len(text.rstrip("\f").split("\f")),
    "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
    **checks,
    "aimeWrongLabelOccurrences": counts,
    "overfullHBoxWarnings": len(re.findall(r"Overfull \\hbox", log)),
    "limits": ["The checks verify compiled labels and audit notices, not historical numeric validity or a public release.",
               "Existing typesetting warnings are recorded; earlier page previews cover the audit notice and setup table."],
}
output = ROOT / "docs/repair-2026-10-08/paper-qa.json"
output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"output": str(output), "pages": result["pages"], "checks": checks}, ensure_ascii=False))
if not all(value for name, value in checks.items() if name != "crossReferenceRerunNeeded") or checks["crossReferenceRerunNeeded"]:
    raise SystemExit(1)
